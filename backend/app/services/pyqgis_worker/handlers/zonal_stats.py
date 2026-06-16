"""Summarize raster values inside polygon zones."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List

from ..errors import WorkflowExecutionError
from ..workspace import Workspace
from . import _common


STAT_CODE_BY_NAME = {
    "count": 0,
    "sum": 1,
    "mean": 2,
    "median": 3,
    "stdev": 4,
    "min": 5,
    "max": 6,
    "range": 7,
    "minority": 8,
    "majority": 9,
    "variety": 10,
    "variance": 11,
}


def execute(params: Dict[str, Any], workspace: Workspace) -> Dict[str, Any]:
    resolved = workspace.resolve_reference(params)
    zones = _common.require_layer(workspace, resolved.get("input"))
    raster_source = resolved.get("raster")
    project_id = str(resolved.get("project_id") or "")
    raster = _load_raster(workspace, raster_source, project_id)
    band = int(resolved.get("band") or 1)
    prefix = str(resolved.get("prefix") or "zs_").strip() or "zs_"
    statistics = _normalize_statistics(resolved.get("statistics") or ["sum", "mean", "min", "max"])

    try:
        import processing  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on QGIS runtime
        raise WorkflowExecutionError(
            code="QGIS_ENV_NOT_READY",
            message=f"processing import failed: {exc}",
            user_friendly="当前 QGIS 运行环境不可用，无法执行栅格分区统计。",
        ) from exc

    try:
        result = processing.run(
            "native:zonalstatisticsfb",
            {
                "INPUT": zones,
                "INPUT_RASTER": raster,
                "RASTER_BAND": band,
                "COLUMN_PREFIX": prefix,
                "STATISTICS": statistics,
                "OUTPUT": "memory:zonal_stats",
            },
        )
    except Exception as exc:  # pragma: no cover - depends on QGIS runtime
        raise WorkflowExecutionError(
            code="PROCESSING_FAILED",
            message=f"zonal statistics failed: {exc}",
            user_friendly="栅格分区统计失败，请确认输入边界与栅格数据有效。",
            details={"statistics": statistics, "band": band},
        ) from exc

    output_layer = result.get("OUTPUT")
    if output_layer is None:
        raise WorkflowExecutionError(
            code="PROCESSING_FAILED",
            message="zonal statistics returned no OUTPUT layer",
            user_friendly="栅格分区统计没有生成结果图层。",
        )

    output_path = workspace.alloc_intermediate_path("zonal_stats", ".geojson")
    _common.write_geojson(output_layer, output_path)
    alias = _common.make_layer_alias(workspace, "zonal_stats", output_layer)
    fields = _common.layer_field_names(output_layer)
    stats_fields = [field for field in fields if field.startswith(prefix)]
    return {
        "layer": alias,
        "path": str(output_path),
        "extent": _common.layer_extent_to_list(output_layer),
        "crs": output_layer.crs().authid() if output_layer.crs().isValid() else "EPSG:4326",
        "fields": fields,
        "stats_fields": stats_fields,
        "feature_count": output_layer.featureCount() if hasattr(output_layer, "featureCount") else None,
    }


def _load_raster(workspace: Workspace, source: Any, project_id: str) -> Any:
    if not isinstance(source, str) or not source.strip():
        raise WorkflowExecutionError(
            code="DATASET_NOT_FOUND",
            message="zonal_stats.raster must be a dataset source string",
            user_friendly="栅格分区统计需要提供 raster 数据源。",
        )
    resolved = workspace.get_layer(source)
    if not isinstance(resolved, str):
        return resolved
    path = _common.resolve_dataset_path(workspace, resolved, project_id=project_id)
    return _common._load_layer_from_path(str(path))


def _normalize_statistics(raw: Any) -> List[int]:
    values: Iterable[Any]
    if isinstance(raw, str):
        values = [part.strip() for part in raw.split(",")]
    elif isinstance(raw, list):
        values = raw
    else:
        values = ["sum", "mean", "min", "max"]

    stats: List[int] = []
    for item in values:
        if isinstance(item, int):
            if item not in STAT_CODE_BY_NAME.values():
                continue
            stats.append(item)
            continue
        key = str(item).strip().lower()
        if key in STAT_CODE_BY_NAME:
            stats.append(STAT_CODE_BY_NAME[key])
    if not stats:
        stats = [STAT_CODE_BY_NAME["sum"], STAT_CODE_BY_NAME["mean"]]
    return list(dict.fromkeys(stats))
