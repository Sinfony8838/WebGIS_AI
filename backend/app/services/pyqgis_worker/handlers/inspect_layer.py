"""Inspect a loaded layer (fields, extent, CRS, feature count, sample row)."""
from __future__ import annotations

from typing import Any, Dict, List

from ..workspace import Workspace
from . import _common


def execute(params: Dict[str, Any], workspace: Workspace) -> Dict[str, Any]:
    resolved = workspace.resolve_reference(params)
    layer = _common.require_layer(workspace, resolved.get("input"))
    sample_size = int(resolved.get("sample_size", 5) or 5)

    summary: Dict[str, Any] = {
        "name": layer.name(),
        "type": "raster" if "Raster" in type(layer).__name__ else "vector",
        "crs": layer.crs().authid() if layer.crs().isValid() else "",
        "extent": _common.layer_extent_to_list(layer),
        "fields": _common.layer_field_names(layer),
    }

    if hasattr(layer, "featureCount"):
        summary["feature_count"] = layer.featureCount()
        sample: List[Dict[str, Any]] = []
        try:
            for index, feature in enumerate(layer.getFeatures()):
                if index >= max(0, sample_size):
                    break
                attrs: Dict[str, Any] = {}
                for field in layer.fields():
                    value = feature.attribute(field.name())
                    if hasattr(value, "isoformat"):
                        value = value.isoformat()
                    attrs[field.name()] = _coerce_scalar(value)
                sample.append(attrs)
        except Exception:
            sample = []
        summary["sample"] = sample

    return {
        "layer": resolved.get("input"),
        "summary": summary,
        "extent": summary["extent"],
        "crs": summary["crs"],
        "fields": summary["fields"],
    }


def _coerce_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
