"""Bounded source/method context from the authorized project's visible layers."""
from __future__ import annotations

from collections import Counter
from typing import Any
from urllib.parse import urlsplit

from ..models import ProjectRecord
from ..geo import CLASSIC_START, CLASSIC_END, HU_LINE_METHODS

FACT_FIELDS = (
    "source_name", "source_year", "coverage", "description", "period",
    "resolution_degrees", "units", "isohyet_mm", "method", "limitations",
    "reference_description", "fitted_description", "style_field",
)


def visible_project_layers(project: ProjectRecord, context: dict[str, Any]):
    # An explicit empty client view is meaningful (e.g. the 3D renderer).
    requested = context.get("visible_layers")
    ids = None if not isinstance(requested, list) else {
        item.get("layer_id") if isinstance(item, dict) else item
        for item in requested if isinstance(item, (dict, str))
        and isinstance(item.get("layer_id") if isinstance(item, dict) else item, str)
    }
    return [layer for layer in project.layers if layer.visible and (ids is None or layer.layer_id in ids)]


def _bounded(value: Any):
    if isinstance(value, str):
        return value[:700]
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, list):
        return [str(item)[:200] for item in value[:6] if isinstance(item, (str, int, float))]
    return None


def build_layer_evidence(project: ProjectRecord, context: dict[str, Any]) -> list[dict[str, Any]]:
    if context.get("image_attachment"):
        return []  # An uploaded image is not the live project's map.
    layers = visible_project_layers(project, context)
    active_id = context.get("active_layer_id")
    layers.sort(key=lambda layer: layer.layer_id != active_id)
    evidence = []
    for layer in layers[:6]:
        metadata = {**(layer.metadata or {}), **(layer.data.get("metadata") or {})}
        # Old saved template layers predate the descriptive metadata. Only
        # recognize the classic segment when its actual geometry matches the
        # generator, so an edited line cannot acquire that provenance by name.
        if layer.source == "generated" and metadata.get("template_id") == "hu_line_comparison":
            classic = [feature for feature in layer.data.get("features", [])
                       if (feature.get("properties") or {}).get("line_type") == "classic"]
            if len(classic) == 1 and (classic[0].get("geometry") or {}).get("coordinates") == [list(CLASSIC_START), list(CLASSIC_END)]:
                metadata = {**metadata, **HU_LINE_METHODS}
                # This method belongs to the optional fitted line, not the
                # classic reference segment. Keep its meaning in fitted_description.
                metadata.pop("method", None)
        facts = {key: _bounded(metadata[key]) for key in FACT_FIELDS if metadata.get(key) is not None}
        facts = {key: value for key, value in facts.items() if value not in (None, "", [])}
        if not facts:
            continue
        # Summarize actual geometries, without passing full coordinates or
        # treating a first feature's attributes as values for the whole layer.
        features = layer.data.get("features") or []
        types = Counter()
        closed_lines = 0
        for feature in features[:10000]:
            geometry = feature.get("geometry") or {}
            kind = geometry.get("type", "unknown")
            types[kind] += 1
            if kind == "LineString":
                coords = geometry.get("coordinates") or []
                closed_lines += int(len(coords) > 2 and coords[0] == coords[-1])
        citations = []
        for key in ("source_url", "reference_url"):
            url = str(metadata.get(key) or "")
            try:
                parsed = urlsplit(url)
            except ValueError:
                continue
            if parsed.scheme in {"https", "http"} and parsed.hostname and not parsed.username and not parsed.password:
                citations.append({"title": f"图层资料：{layer.name[:80]}", "url": url[:1500]})
        evidence.append({"name": layer.name[:100], "facts": facts,
                         "stored_geometry": {"feature_types": dict(types), "closed_lines": closed_lines,
                                      "sampled": len(features) > 10000},
                         "citations": citations})
    return evidence
