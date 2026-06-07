"""Append a class-index field to a vector layer.

Unlike ``choropleth`` (which also produces a color style and a GeoJSON
artifact for rendering), ``classify`` only adds a class-id integer field
so downstream steps — joins, filters, aggregate_stats — can group by the
classified bucket without re-deriving it.

Output field naming convention: defaults to ``"<field>_class"`` so the
result of classifying ``population`` is the attribute ``population_class``.
Caller can override via ``output_field``.

Uses the same break-point algorithms as ``choropleth`` via
``_classification.compute_breaks``.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from ..errors import WorkflowExecutionError
from ..workspace import Workspace
from . import _classification, _common


_VALID_FIELD_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


def _safe_field_name(name: str, fallback: str) -> str:
    if isinstance(name, str) and _VALID_FIELD_NAME.match(name):
        return name
    return fallback


def _format_for_expression(value: float) -> str:
    """Render a float so it parses cleanly inside a QGIS expression literal."""
    # 17 digits round-trips IEEE 754 doubles; QGIS accepts standard decimal notation.
    text = repr(float(value))
    # repr can emit "1e+20"; QGIS accepts that too. Leave as-is.
    return text


def _build_class_expression(source_field: str, breaks: List[float]) -> str:
    """Build a CASE WHEN expression returning the class index for ``source_field``.

    Half-open intervals on each class except the last (fully closed) so the
    max sample lands in the top class — mirrors ``_classification.classify_value``.
    """
    if len(breaks) < 2:
        return "0"
    field_ref = f'"{source_field}"'
    last_class = len(breaks) - 2
    lines = ["CASE"]
    for i in range(last_class):
        upper = _format_for_expression(breaks[i + 1])
        lines.append(f"  WHEN {field_ref} < {upper} THEN {i}")
    lines.append(f"  ELSE {last_class}")
    lines.append("END")
    return "\n".join(lines)


def execute(params: Dict[str, Any], workspace: Workspace) -> Dict[str, Any]:
    resolved = workspace.resolve_reference(params)
    layer = _common.require_layer(workspace, resolved.get("input"))
    field = str(resolved.get("field") or "").strip()
    classes = int(resolved.get("classes", 5) or 5)
    method = str(resolved.get("method") or "jenks").lower()
    output_field = _safe_field_name(
        str(resolved.get("output_field") or "").strip(),
        fallback=f"{field}_class" if field else "class_id",
    )

    if not field:
        raise WorkflowExecutionError(
            code="VALIDATION_FAILED",
            message="classify requires a field",
            user_friendly="分级操作需要指定字段。",
        )
    if classes < 2:
        raise WorkflowExecutionError(
            code="VALIDATION_FAILED",
            message=f"classify needs at least 2 classes, got {classes}",
            user_friendly="分级数至少为 2。",
        )
    _common.ensure_field_exists(layer, field)

    # Read values to compute breaks (server-side, single pass).
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

    breaks = _classification.compute_breaks(values, classes, method)
    expression = _build_class_expression(field, breaks)

    import processing  # type: ignore

    try:
        result = processing.run(
            "native:fieldcalculator",
            {
                "INPUT": layer,
                "FIELD_NAME": output_field,
                "FIELD_TYPE": 1,  # Integer
                "FIELD_LENGTH": 4,
                "FIELD_PRECISION": 0,
                "FORMULA": expression,
                "OUTPUT": "memory:classified",
            },
        )
    except Exception as exc:
        raise WorkflowExecutionError(
            code="PROCESSING_FAILED",
            message=f"classify field calculation failed: {exc}",
            user_friendly=f"分级计算失败：{field}",
            details={"field": field, "method": method, "classes": classes, "reason": repr(exc)},
        ) from exc

    out = result["OUTPUT"]
    alias = _common.make_layer_alias(workspace, "classify", out)

    classes_applied = [
        {
            "class_id": i,
            "min": float(breaks[i]),
            "max": float(breaks[i + 1]),
            "label": _classification.format_label(breaks[i], breaks[i + 1]),
        }
        for i in range(len(breaks) - 1)
    ]

    return {
        "layer": alias,
        "crs": out.crs().authid() if out.crs().isValid() else "EPSG:4326",
        "extent": _common.layer_extent_to_list(out),
        "fields": _common.layer_field_names(out),
        "feature_count": out.featureCount(),
        "output_field": output_field,
        "method": method,
        "classes_applied": classes_applied,
        "breaks": [float(b) for b in breaks],
    }
