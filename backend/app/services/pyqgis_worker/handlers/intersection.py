"""Geometric intersection of two vector layers.

Wraps ``native:intersection``. Produces a layer whose geometries are the
intersection of input × overlay and whose attribute table merges fields
from both sides. Where field names collide, the overlay layer's columns
are suffixed with ``_2`` by QGIS.

Phase 1.1 scope: layer-to-layer intersection only. Free-form geometry
input is handled by Batch 3's instant_analysis service.
"""
from __future__ import annotations

from typing import Any, Dict

from ..errors import WorkflowExecutionError
from ..workspace import Workspace
from . import _common


def execute(params: Dict[str, Any], workspace: Workspace) -> Dict[str, Any]:
    resolved = workspace.resolve_reference(params)
    input_layer = _common.require_layer(workspace, resolved.get("input"))
    overlay_layer = _common.require_layer(workspace, resolved.get("overlay_layer"))

    import processing  # type: ignore

    original_crs = input_layer.crs().authid() if input_layer.crs().isValid() else "EPSG:4326"

    try:
        result = processing.run(
            "native:intersection",
            {
                "INPUT": input_layer,
                "OVERLAY": overlay_layer,
                "INPUT_FIELDS": [],
                "OVERLAY_FIELDS": [],
                "OUTPUT": "memory:intersected",
            },
        )
    except Exception as exc:
        raise WorkflowExecutionError(
            code="PROCESSING_FAILED",
            message=f"native:intersection failed: {exc}",
            user_friendly="求交集运算失败。",
            details={"reason": repr(exc)},
        ) from exc

    intersected = result["OUTPUT"]
    alias = _common.make_layer_alias(workspace, "intersection", intersected)
    return {
        "layer": alias,
        "crs": intersected.crs().authid() if intersected.crs().isValid() else original_crs,
        "extent": _common.layer_extent_to_list(intersected),
        "fields": _common.layer_field_names(intersected),
        "feature_count": intersected.featureCount(),
    }
