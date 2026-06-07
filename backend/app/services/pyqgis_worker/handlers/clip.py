"""Clip a vector layer by another vector layer.

Wraps ``native:clip``. The input layer's geometries are clipped to the
extent of ``clip_layer``'s features; attributes of the input are preserved.
QGIS handles CRS reconciliation internally when the two layers differ —
we still record the input layer's CRS as the output CRS for downstream
consistency.

Phase 1.1 scope: layer-to-layer clipping only. Free-form geometry clipping
(e.g. clip by a drawn polygon) is handled by Batch 3's instant_analysis
service which first materialises the geometry into a temporary layer.
"""
from __future__ import annotations

from typing import Any, Dict

from ..errors import WorkflowExecutionError
from ..workspace import Workspace
from . import _common


def execute(params: Dict[str, Any], workspace: Workspace) -> Dict[str, Any]:
    resolved = workspace.resolve_reference(params)
    input_layer = _common.require_layer(workspace, resolved.get("input"))
    clip_layer = _common.require_layer(workspace, resolved.get("clip_layer"))

    import processing  # type: ignore

    original_crs = input_layer.crs().authid() if input_layer.crs().isValid() else "EPSG:4326"

    try:
        result = processing.run(
            "native:clip",
            {
                "INPUT": input_layer,
                "OVERLAY": clip_layer,
                "OUTPUT": "memory:clipped",
            },
        )
    except Exception as exc:
        raise WorkflowExecutionError(
            code="PROCESSING_FAILED",
            message=f"native:clip failed: {exc}",
            user_friendly="裁剪计算失败。",
            details={"reason": repr(exc)},
        ) from exc

    clipped = result["OUTPUT"]
    alias = _common.make_layer_alias(workspace, "clip", clipped)
    return {
        "layer": alias,
        "crs": clipped.crs().authid() if clipped.crs().isValid() else original_crs,
        "extent": _common.layer_extent_to_list(clipped),
        "fields": _common.layer_field_names(clipped),
        "feature_count": clipped.featureCount(),
    }
