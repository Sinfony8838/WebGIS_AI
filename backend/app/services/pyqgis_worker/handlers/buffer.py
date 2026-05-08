"""Buffer a vector layer.

Supports ``auto_project=True``: if the input CRS is geographic (e.g. EPSG:4326)
the layer is reprojected to EPSG:3857 before applying the buffer, then
returned in the original CRS so subsequent steps see consistent coordinates.
"""
from __future__ import annotations

from typing import Any, Dict

from ..errors import WorkflowExecutionError
from ..workspace import Workspace
from . import _common


def execute(params: Dict[str, Any], workspace: Workspace) -> Dict[str, Any]:
    resolved = workspace.resolve_reference(params)
    layer = _common.require_layer(workspace, resolved.get("input"))
    distance = float(resolved.get("distance", 0))
    if distance <= 0:
        raise WorkflowExecutionError(
            code="VALIDATION_FAILED",
            message="buffer.distance must be positive",
            user_friendly="缓冲区距离必须大于 0。",
        )
    segments = int(resolved.get("segments", 8) or 8)
    dissolve = bool(resolved.get("dissolve", False))
    auto_project = bool(resolved.get("auto_project", True))

    import processing  # type: ignore
    from qgis.core import QgsCoordinateReferenceSystem  # type: ignore

    source = layer
    original_crs = layer.crs().authid() if layer.crs().isValid() else "EPSG:4326"
    needs_reproject = auto_project and layer.crs().isGeographic()

    if needs_reproject:
        source = _common.reproject_layer_in_memory(layer, "EPSG:3857")

    try:
        result = processing.run(
            "native:buffer",
            {
                "INPUT": source,
                "DISTANCE": distance,
                "SEGMENTS": segments,
                "END_CAP_STYLE": 0,
                "JOIN_STYLE": 0,
                "MITER_LIMIT": 2,
                "DISSOLVE": dissolve,
                "OUTPUT": "memory:buffered",
            },
        )
    except Exception as exc:
        raise WorkflowExecutionError(
            code="PROCESSING_FAILED",
            message=f"native:buffer failed: {exc}",
            user_friendly="缓冲区计算失败。",
            details={"reason": repr(exc)},
        ) from exc

    buffered = result["OUTPUT"]

    # Reproject back to original CRS if we changed it for the buffer math.
    final = buffered
    if needs_reproject and original_crs and original_crs != "EPSG:3857":
        final = _common.reproject_layer_in_memory(buffered, original_crs)

    alias = _common.make_layer_alias(workspace, "buffer", final)
    return {
        "layer": alias,
        "crs": final.crs().authid() if final.crs().isValid() else original_crs,
        "extent": _common.layer_extent_to_list(final),
        "fields": _common.layer_field_names(final),
        "feature_count": final.featureCount(),
    }
