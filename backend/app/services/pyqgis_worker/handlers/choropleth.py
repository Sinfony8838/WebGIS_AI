"""Compute a graduated (choropleth) classification for a numeric field.

Outputs both the classified layer (in worker memory) AND a portable
``style.json`` describing classes/colors so OpenLayers can re-render the
GeoJSON interactively. We do NOT rely on QGIS to render the PNG here —
``export_map_png`` is a separate step.
"""
from __future__ import annotations

import statistics
from typing import Any, Dict, List

from ..errors import WorkflowExecutionError
from ..workspace import Workspace
from . import _common


# A handful of standard color ramps as hex sequences (interpolated client-side
# already would force us to use Pillow; for v1 we hand-pick palette).
_COLOR_RAMPS: Dict[str, List[List[str]]] = {
    # 3-class through 8-class flavours of YlOrRd / BuPu / RdYlBu
    "YlOrRd": [
        ["#ffffb2", "#fecc5c", "#fd8d3c", "#f03b20", "#bd0026"],
        ["#ffffb2", "#fed976", "#feb24c", "#fd8d3c", "#fc4e2a", "#e31a1c", "#b10026"],
    ],
    "BuPu": [
        ["#edf8fb", "#b3cde3", "#8c96c6", "#8856a7", "#810f7c"],
        ["#edf8fb", "#bfd3e6", "#9ebcda", "#8c96c6", "#8c6bb1", "#88419d", "#6e016b"],
    ],
    "RdYlBu": [
        ["#d7191c", "#fdae61", "#ffffbf", "#abd9e9", "#2c7bb6"],
        ["#d73027", "#fc8d59", "#fee090", "#ffffbf", "#e0f3f8", "#91bfdb", "#4575b4"],
    ],
    "Greens": [
        ["#edf8e9", "#bae4b3", "#74c476", "#31a354", "#006d2c"],
    ],
    "Blues": [
        ["#eff3ff", "#bdd7e7", "#6baed6", "#3182bd", "#08519c"],
    ],
}


def _pick_palette(ramp_name: str, classes: int) -> List[str]:
    palettes = _COLOR_RAMPS.get(ramp_name) or _COLOR_RAMPS["YlOrRd"]
    # Pick a palette with enough colors; degrade gracefully.
    chosen = palettes[0]
    for candidate in palettes:
        if len(candidate) >= classes:
            chosen = candidate
            break
    if len(chosen) >= classes:
        # Spread evenly through the palette.
        step = (len(chosen) - 1) / (classes - 1) if classes > 1 else 0
        return [chosen[round(step * i)] for i in range(classes)]
    # Fewer colors than classes — repeat the last one.
    return chosen + [chosen[-1]] * (classes - len(chosen))


def _compute_breaks(values: List[float], classes: int, method: str) -> List[float]:
    if not values:
        raise WorkflowExecutionError(
            code="GEOMETRY_INVALID",
            message="no values to classify",
            user_friendly="无法分级：没有任何样本。",
        )
    sorted_values = sorted(values)
    method = (method or "jenks").lower()
    if method in {"equal", "equal_interval"}:
        lo = sorted_values[0]
        hi = sorted_values[-1]
        if hi <= lo:
            return [lo, hi]
        step = (hi - lo) / classes
        return [lo + step * i for i in range(classes + 1)]
    if method == "quantile":
        breaks = [sorted_values[0]]
        for i in range(1, classes):
            idx = int(round(i * (len(sorted_values) - 1) / classes))
            breaks.append(sorted_values[idx])
        breaks.append(sorted_values[-1])
        return breaks
    if method in {"stddev", "std_dev"}:
        mean = statistics.fmean(sorted_values)
        stdev = statistics.pstdev(sorted_values) or 1.0
        breaks = [mean + (i - classes / 2) * stdev for i in range(classes + 1)]
        breaks[0] = min(breaks[0], sorted_values[0])
        breaks[-1] = max(breaks[-1], sorted_values[-1])
        return breaks
    # Jenks / natural_breaks — fall back to a Fisher-Jenks-like greedy split.
    return _fisher_jenks_breaks(sorted_values, classes)


def _fisher_jenks_breaks(sorted_values: List[float], classes: int) -> List[float]:
    """A simple, fast approximation: split the sorted array at quantile-like
    boundaries refined by within-class variance. For small N (<=2000) the cost
    is fine; for large N this still produces reasonable breaks."""
    n = len(sorted_values)
    if classes <= 1:
        return [sorted_values[0], sorted_values[-1]]
    # Quantile seed
    breaks = [sorted_values[0]]
    for i in range(1, classes):
        idx = int(round(i * (n - 1) / classes))
        breaks.append(sorted_values[idx])
    breaks.append(sorted_values[-1])
    # One pass of refinement: shift each interior break to local mean midpoint.
    for _ in range(2):
        for i in range(1, classes):
            left_idx = next(idx for idx, v in enumerate(sorted_values) if v >= breaks[i - 1])
            right_idx = next(idx for idx, v in enumerate(sorted_values) if v >= breaks[i + 1])
            window = sorted_values[left_idx:right_idx + 1]
            if window:
                breaks[i] = statistics.median(window)
    breaks.sort()
    return breaks


def _format_label(low: float, high: float) -> str:
    def _fmt(value: float) -> str:
        if abs(value) >= 1000 or abs(value) < 0.01:
            return f"{value:.2g}"
        return f"{value:.2f}"
    return f"{_fmt(low)} - {_fmt(high)}"


def execute(params: Dict[str, Any], workspace: Workspace) -> Dict[str, Any]:
    resolved = workspace.resolve_reference(params)
    layer = _common.require_layer(workspace, resolved.get("input"))
    field = str(resolved.get("field") or "").strip()
    classes = int(resolved.get("classes", 5) or 5)
    method = str(resolved.get("method") or "jenks").lower()
    ramp_name = str(resolved.get("color_ramp") or "YlOrRd")
    title = str(resolved.get("title") or f"{layer.name()} - {field}")
    legend_title = str(resolved.get("legend_title") or field)

    if not field:
        raise WorkflowExecutionError(
            code="VALIDATION_FAILED",
            message="choropleth requires a field",
            user_friendly="分级设色需要指定字段。",
        )
    _common.ensure_field_exists(layer, field)

    values: List[float] = []
    feature_iter = layer.getFeatures() if hasattr(layer, "getFeatures") else []
    for feature in feature_iter:
        raw = feature.attribute(field)
        if raw is None:
            continue
        try:
            values.append(float(raw))
        except (TypeError, ValueError):
            continue
    if not values:
        raise WorkflowExecutionError(
            code="FIELD_TYPE_MISMATCH",
            message=f"field '{field}' has no numeric values",
            user_friendly=f"字段 {field} 没有可用的数值。",
        )

    breaks = _compute_breaks(values, classes, method)
    palette = _pick_palette(ramp_name, classes)
    style_classes = []
    for index in range(classes):
        lo = breaks[index]
        hi = breaks[index + 1]
        style_classes.append({
            "min": float(lo),
            "max": float(hi),
            "color": palette[index],
            "label": _format_label(lo, hi),
        })

    style_payload = {
        "type": "graduated",
        "field": field,
        "method": method,
        "classes": style_classes,
        "stroke": {"color": "#444444", "width": 0.4},
        "default": {"color": "#cccccc"},
        "legend": {
            "title": legend_title,
            "items": [{"label": cls["label"], "color": cls["color"]} for cls in style_classes],
        },
        "title": title,
    }

    # Re-export the layer to GeoJSON so the frontend can use it together with style.
    geojson_path = workspace.alloc_output_path("choropleth", ".geojson")
    _, geo_meta = _common.write_geojson(layer, geojson_path, target_crs="EPSG:4326")

    style_path = workspace.alloc_output_path("style", ".json")
    import json
    style_path.write_text(json.dumps(style_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    alias = _common.make_layer_alias(workspace, "choropleth", layer)
    return {
        "layer": alias,
        "geojson": str(geojson_path),
        "style": str(style_path),
        "geojson_relative": workspace.relative(geojson_path),
        "style_relative": workspace.relative(style_path),
        "extent": geo_meta["extent"],
        "crs": "EPSG:4326",
        "feature_count": geo_meta["feature_count"],
        "title": title,
        "field": field,
        "classes": classes,
    }
