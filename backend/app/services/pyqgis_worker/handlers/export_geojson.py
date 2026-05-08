"""Export a vector layer to GeoJSON in EPSG:4326."""
from __future__ import annotations

from typing import Any, Dict

from ..workspace import Workspace
from . import _common


def execute(params: Dict[str, Any], workspace: Workspace) -> Dict[str, Any]:
    resolved = workspace.resolve_reference(params)
    layer = _common.require_layer(workspace, resolved.get("input"))
    target_crs = _common.normalize_crs(resolved.get("target_crs"), default="EPSG:4326")
    name = str(resolved.get("name") or "result")

    output_path = workspace.alloc_output_path(name, ".geojson")
    _, meta = _common.write_geojson(layer, output_path, target_crs=target_crs)
    return {
        "geojson": str(output_path),
        "geojson_relative": workspace.relative(output_path),
        "path": str(output_path),
        "extent": meta["extent"],
        "crs": target_crs,
        "feature_count": meta["feature_count"],
    }
