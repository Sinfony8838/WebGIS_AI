"""Reproject a vector layer."""
from __future__ import annotations

from typing import Any, Dict

from ..workspace import Workspace
from . import _common


def execute(params: Dict[str, Any], workspace: Workspace) -> Dict[str, Any]:
    resolved = workspace.resolve_reference(params)
    layer = _common.require_layer(workspace, resolved.get("input"))
    target_crs = _common.normalize_crs(resolved.get("target_crs"))
    out = _common.reproject_layer_in_memory(layer, target_crs)
    alias = _common.make_layer_alias(workspace, "reproject", out)
    return {
        "layer": alias,
        "crs": target_crs,
        "extent": _common.layer_extent_to_list(out),
        "fields": _common.layer_field_names(out),
        "feature_count": out.featureCount(),
    }
