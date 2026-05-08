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
    """Best-effort: locate the project's data dir from env. The worker stores
    workflows under ``data/workflows/{wf_id}``; uploads live in
    ``data/uploads/{project_id}/``. We need to be able to resolve a
    user-supplied dataset id against either ``data/uploads`` or builtin folders.
    """
    candidate = os.environ.get("WEBGIS_AI_DATA_DIR", "")
    if candidate and Path(candidate).exists():
        return Path(candidate)
    # Default: walk up two levels from this file to backend/, then data/
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "data").exists():
            return parent / "data"
    return Path("data")


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
    base_data = workspace_root()

    if cleaned.startswith("upload:"):
        rest = cleaned.removeprefix("upload:").lstrip("/").replace("\\", "/")
        candidate = (base_data / "uploads" / rest).resolve()
        if str(candidate).startswith(str((base_data / "uploads").resolve())) and candidate.exists():
            return candidate
        raise WorkflowExecutionError(
            code="DATASET_NOT_FOUND",
            message=f"upload not found: {cleaned}",
            user_friendly=f"未找到上传数据：{rest}",
        )

    if cleaned.startswith("builtin:"):
        rest = cleaned.removeprefix("builtin:").lstrip("/").replace("\\", "/")
        for builtin_root in (base_data / "builtin", workspace_root().parent / "app" / "data" / "builtin"):
            candidate = (builtin_root / rest).resolve()
            try:
                candidate.relative_to(builtin_root.resolve())
            except ValueError:
                continue
            if candidate.exists():
                return candidate
        raise WorkflowExecutionError(
            code="DATASET_NOT_FOUND",
            message=f"builtin not found: {cleaned}",
            user_friendly=f"未找到内置数据：{rest}",
        )

    # Absolute / workflow-internal path passed through resolve_reference
    if cleaned.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", cleaned):
        candidate = Path(cleaned)
        if candidate.exists():
            return candidate

    # Search under uploads/<project_id>/
    if project_id:
        candidate = (base_data / "uploads" / project_id / cleaned).resolve()
        if candidate.exists():
            return candidate

    # Search builtin
    for builtin_root in (base_data / "builtin", workspace_root().parent / "app" / "data" / "builtin"):
        try:
            candidate = (builtin_root / cleaned).resolve()
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
    """Write a vector layer to GeoJSON at ``target_path`` in ``target_crs``."""
    from qgis.core import QgsCoordinateReferenceSystem, QgsVectorFileWriter, QgsProject  # type: ignore

    target_path.parent.mkdir(parents=True, exist_ok=True)
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "GeoJSON"
    options.fileEncoding = "UTF-8"
    options.ct = None
    crs_obj = QgsCoordinateReferenceSystem(target_crs)
    options.destCRS = crs_obj
    transform_context = QgsProject.instance().transformContext() if QgsProject.instance() else None
    if transform_context is None:
        from qgis.core import QgsCoordinateTransformContext  # type: ignore
        transform_context = QgsCoordinateTransformContext()
    error = QgsVectorFileWriter.writeAsVectorFormatV2(
        layer, str(target_path), transform_context, options
    )
    if isinstance(error, tuple) and error[0] not in (0, QgsVectorFileWriter.NoError):
        raise WorkflowExecutionError(
            code="EXPORT_FAILED",
            message=f"GeoJSON export failed: {error}",
            user_friendly="导出 GeoJSON 失败。",
            details={"error": str(error)},
        )
    return target_path, {
        "feature_count": layer.featureCount(),
        "extent": layer_extent_to_list(layer),
    }
