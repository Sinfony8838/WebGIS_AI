"""Shared helpers for PyQGIS handlers.

Convenience wrappers that:

* resolve dataset sources (project upload directories, builtin teaching maps,
  workflow-internal references) into concrete file paths;
* fetch QGIS layers from the worker workspace;
* normalise CRS strings;
* build the ``outputs`` dict expected by the executor.

This module imports ``qgis.core`` lazily because handlers must run inside the
worker subprocess.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..errors import WorkflowExecutionError
from ..workspace import Workspace


def workspace_root() -> Path:
    """Locate the shared data root (uploads / builtin / workflows base).

    The main process exports ``WEBGIS_AI_DATA_DIR`` (see
    ``backend.app.config.resolve_data_root``), so an env value is authoritative.
    Fallback walks up to the repository layout ``<repo>/backend/data``; the
    ``backend`` component must be matched explicitly because
    ``backend/app/data`` (builtin assets) otherwise shadows the real data dir.
    """
    candidate = os.environ.get("WEBGIS_AI_DATA_DIR", "")
    if candidate and Path(candidate).exists():
        return Path(candidate)
    here = Path(__file__).resolve()
    for parent in here.parents:
        data_root = parent / "backend" / "data"
        if data_root.exists():
            return data_root
    return Path("data")


def builtin_root() -> Path:
    """Builtin teaching data lives under the repo source tree.

    It is source-controlled content (``backend/app/data/builtin``), NOT
    part of the mutable data root, so it must be derived from this module's
    location instead of ``workspace_root().parent`` — otherwise a relocated
    data root (``WEBGIS_AI_DATA_DIR``) would hide every builtin dataset.
    """
    return Path(__file__).resolve().parents[3] / "data" / "builtin"


def _path_within(candidate: Path, root: Path) -> bool:
    """Containment on resolved paths (symlink/junction aware)."""
    try:
        Path(candidate).resolve().relative_to(Path(root).resolve())
    except ValueError:
        return False
    return True


def workspace_data_root(workspace: Workspace) -> Path:
    """Data root for the given workflow workspace.

    ``WorkflowExecutor`` hands the manager ``workflows_root = <data>/workflows``
    and the worker builds ``Workspace(workflow_id, workflows_root/<id>)``, so
    the workspace's grandparent is the data root. Deriving it per-workspace
    keeps resolution independent of process-global state (env) and correct
    for relocated data roots.
    """
    candidate = (Path(workspace.root_dir).parent.parent).resolve()
    if (candidate / "workflows").exists():
        return candidate
    return workspace_root()


def resolve_dataset_path(workspace: Workspace, source: str, project_id: str = "") -> Path:
    """Resolve a dataset identifier to a concrete file path.

    Supported source forms:
    - ``upload:<project_id>/<filename>`` (preferred form, used by frontend)
    - ``builtin:<relative_path>`` (resolves under ``data/builtin/``)
    - ``<filename>``  — tried under ``data/uploads/<project_id>/`` and builtin
    - absolute path under the workflow dir (already resolved by reference logic)
    """
    if not isinstance(source, str) or not source.strip():
        raise WorkflowExecutionError(
            code="DATASET_NOT_FOUND",
            message="empty dataset source",
            user_friendly="数据集来源为空。",
        )
    cleaned = source.strip()
    base_data = workspace_data_root(workspace)

    if cleaned.startswith("upload:"):
        rest = cleaned.removeprefix("upload:").lstrip("/").replace("\\", "/")
        # Upload references are pinned to the step's trusted project: the
        # first path segment must name the project the workflow belongs to,
        # so one project can never reach another project's uploads.
        owner_project = (rest.split("/", 1) or [""])[0]
        if project_id and owner_project != project_id:
            raise WorkflowExecutionError(
                code="DATASET_NOT_ALLOWED",
                message=f"upload reference does not belong to project: {cleaned}",
                user_friendly="上传数据引用不属于当前项目，已拒绝访问。",
            )
        uploads_root = (base_data / "uploads").resolve()
        owner_root = (uploads_root / owner_project).resolve()
        candidate = (base_data / "uploads" / rest).resolve()
        try:
            candidate.relative_to(owner_root)
        except ValueError:
            raise WorkflowExecutionError(
                code="DATASET_NOT_ALLOWED",
                message=f"upload reference escapes the owning project directory: {cleaned}",
                user_friendly="上传数据引用越界，已拒绝访问。",
            )
        if candidate.exists():
            return candidate
        raise WorkflowExecutionError(
            code="DATASET_NOT_FOUND",
            message=f"upload not found: {cleaned}",
            user_friendly=f"未找到上传数据：{rest}",
        )

    if cleaned.startswith("builtin:"):
        rest = cleaned.removeprefix("builtin:").lstrip("/").replace("\\", "/")
        for builtin_root_dir in (base_data / "builtin", builtin_root()):
            candidate = (builtin_root_dir / rest).resolve()
            try:
                candidate.relative_to(builtin_root_dir.resolve())
            except ValueError:
                continue
            if candidate.exists():
                return candidate
        raise WorkflowExecutionError(
            code="DATASET_NOT_FOUND",
            message=f"builtin not found: {cleaned}",
            user_friendly=f"未找到内置数据：{rest}",
        )

    # Absolute / workflow-internal path: only files generated inside the
    # current workflow's own workspace (previous-step outputs and similar)
    # may be passed as absolute paths. Anything else on the server is off
    # limits, even when it exists and is readable.
    if cleaned.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", cleaned):
        candidate = Path(cleaned)
        workflow_root = Path(workspace.root_dir).resolve()
        if not candidate.is_absolute() or not _path_within(candidate, workflow_root):
            raise WorkflowExecutionError(
                code="DATASET_NOT_ALLOWED",
                message=f"absolute path outside the workflow workspace: {cleaned}",
                user_friendly="绝对路径数据源不属于当前工作流，已拒绝访问。",
            )
        if candidate.exists():
            return candidate

    # Search under uploads/<project_id>/
    if project_id:
        candidate = (base_data / "uploads" / project_id / cleaned).resolve()
        if candidate.exists():
            return candidate

    # Search builtin
    for builtin_root_dir in (base_data / "builtin", builtin_root()):
        try:
            candidate = (builtin_root_dir / cleaned).resolve()
            if candidate.exists():
                return candidate
        except Exception:
            continue

    raise WorkflowExecutionError(
        code="DATASET_NOT_FOUND",
        message=f"dataset not found: {source}",
        user_friendly=f"未找到数据集：{source}",
    )


def require_layer(workspace: Workspace, ref: Any) -> Any:
    """Resolve ``ref`` to a real QgsMapLayer.

    Reference can be a worker-internal alias (string returned by a previous
    handler), a path on disk, or a layer object that was already passed in.
    """
    resolved = workspace.resolve_reference(ref)
    layer_obj = workspace.get_layer(resolved)
    if isinstance(layer_obj, str):
        if layer_obj.startswith("_layer__") and not workspace.has_layer(layer_obj):
            # The alias came from this workflow, but the in-memory layer is
            # gone (worker restarted after a crash, or the workflow was
            # released). Fail with the accurate cause instead of pretending
            # the alias is a file path.
            raise WorkflowExecutionError(
                code="WORKER_RESTARTED",
                message=f"worker-internal layer '{layer_obj}' no longer exists",
                user_friendly="上游步骤的内存图层已丢失（Worker 已重启或工作流已释放），请重新运行整个工作流。",
                details={"alias": layer_obj},
            )
        # treat as a path; load lazily
        return _load_layer_from_path(layer_obj)
    return layer_obj


def _load_layer_from_path(path: str):
    from qgis.core import QgsVectorLayer, QgsRasterLayer  # type: ignore

    suffix = Path(path).suffix.lower()
    if suffix in {".tif", ".tiff", ".img", ".vrt"}:
        layer = QgsRasterLayer(path, Path(path).stem)
    else:
        layer = QgsVectorLayer(path, Path(path).stem, "ogr")
    if not layer.isValid():
        raise WorkflowExecutionError(
            code="DATASET_NOT_FOUND",
            message=f"layer at {path} is invalid",
            user_friendly=f"无法加载图层：{path}",
        )
    return layer


def normalize_crs(crs: Any, default: str = "EPSG:4326") -> str:
    if not isinstance(crs, str) or not crs.strip():
        return default
    cleaned = crs.strip().upper()
    if not cleaned.startswith("EPSG:"):
        return default
    return cleaned


def layer_extent_to_list(layer) -> List[float]:
    extent = layer.extent()
    return [extent.xMinimum(), extent.yMinimum(), extent.xMaximum(), extent.yMaximum()]


def layer_field_names(layer) -> List[str]:
    try:
        fields = layer.fields()
    except Exception:
        return []
    return [field.name() for field in fields]


def ensure_field_exists(layer, name: str) -> None:
    if name in layer_field_names(layer):
        return
    raise WorkflowExecutionError(
        code="FIELD_NOT_FOUND",
        message=f"layer has no field '{name}'",
        user_friendly=f"图层中找不到字段 {name}。",
        details={"available": layer_field_names(layer)},
    )


def reproject_layer_in_memory(layer, target_crs: str):
    """Reproject ``layer`` to ``target_crs`` via processing. Returns a memory layer."""
    from qgis.core import QgsCoordinateReferenceSystem  # type: ignore
    import processing  # type: ignore

    target = QgsCoordinateReferenceSystem(target_crs)
    if not target.isValid():
        raise WorkflowExecutionError(
            code="CRS_NOT_SUPPORTED",
            message=f"invalid CRS: {target_crs}",
            user_friendly=f"目标坐标系无效：{target_crs}",
        )
    result = processing.run(
        "native:reprojectlayer",
        {"INPUT": layer, "TARGET_CRS": target, "OUTPUT": "memory:reprojected"},
    )
    return result["OUTPUT"]


def make_layer_alias(workspace: Workspace, step_id: str, layer) -> str:
    """Store ``layer`` in the worker workspace with a per-step unique alias."""
    alias = f"_layer__{step_id}__{id(layer):x}"
    workspace.store_layer(alias, layer)
    return alias


def write_geojson(layer, target_path: Path, target_crs: str = "EPSG:4326") -> Tuple[Path, Dict[str, Any]]:
    """Write a vector layer to GeoJSON at ``target_path`` in ``target_crs``.

    Newer SIP bindings (QGIS 3.34+) reject ``options.ct = None`` — that
    setter is typed ``const QgsCoordinateTransform &`` and refuses ``None``,
    surfacing as ``NoneType cannot be converted to QgsCoordinateTransform``.
    Instead of constructing a transform here, we leave ``options.ct``
    unset (an empty invalid transform) and provide ``destCRS`` +
    ``transformContext`` so QGIS builds the right transform internally.
    """
    from qgis.core import QgsCoordinateReferenceSystem, QgsVectorFileWriter, QgsProject  # type: ignore

    target_path.parent.mkdir(parents=True, exist_ok=True)
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "GeoJSON"
    options.fileEncoding = "UTF-8"
    crs_obj = QgsCoordinateReferenceSystem(target_crs)
    options.destCRS = crs_obj
    transform_context = QgsProject.instance().transformContext() if QgsProject.instance() else None
    if transform_context is None:
        from qgis.core import QgsCoordinateTransformContext  # type: ignore
        transform_context = QgsCoordinateTransformContext()
    # Prefer the V3 API on modern QGIS (returns a tuple where the second
    # element is the user-friendly error message); fall back to V2 on older
    # builds. Both accept the same (layer, dest, context, options) signature.
    writer = getattr(
        QgsVectorFileWriter,
        "writeAsVectorFormatV3",
        getattr(QgsVectorFileWriter, "writeAsVectorFormatV2", None),
    )
    if writer is None:  # pragma: no cover - very old QGIS
        raise WorkflowExecutionError(
            code="EXPORT_FAILED",
            message="QgsVectorFileWriter has no writeAsVectorFormatV2/V3 method",
            user_friendly="QGIS 版本过旧，无法导出 GeoJSON。",
        )
    result = writer(layer, str(target_path), transform_context, options)
    error_code = result[0] if isinstance(result, tuple) else result
    if error_code not in (0, QgsVectorFileWriter.NoError):
        raise WorkflowExecutionError(
            code="EXPORT_FAILED",
            message=f"GeoJSON export failed: {result}",
            user_friendly="导出 GeoJSON 失败。",
            details={"error": str(result)},
        )
    return target_path, {
        "feature_count": layer.featureCount(),
        "extent": layer_extent_to_list(layer),
    }
