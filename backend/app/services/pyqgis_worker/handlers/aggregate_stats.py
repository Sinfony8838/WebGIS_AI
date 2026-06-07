"""Compute summary statistics over a layer's attributes."""
from __future__ import annotations

import json
import statistics
from typing import Any, Dict, List

from ..errors import WorkflowExecutionError
from ..workspace import Workspace
from . import _common


def execute(params: Dict[str, Any], workspace: Workspace) -> Dict[str, Any]:
    resolved = workspace.resolve_reference(params)
    layer = _common.require_layer(workspace, resolved.get("input"))
    fields_param = resolved.get("fields") or []
    if isinstance(fields_param, str):
        fields_param = [fields_param]
    label_field = str(resolved.get("label_field") or "").strip()
    top = int(resolved.get("top", 10) or 10)
    title = str(resolved.get("title") or f"{layer.name()} 统计")

    available = _common.layer_field_names(layer)
    if not fields_param:
        # default: take numeric-looking fields
        for fname in available:
            if any(token in fname.lower() for token in ("density", "population", "pop", "value", "amount", "area")):
                fields_param.append(fname)
        if not fields_param:
            fields_param = available[:3]
    fields_param = [str(f) for f in fields_param if isinstance(f, str)]
    for fname in fields_param:
        if fname not in available:
            raise WorkflowExecutionError(
                code="FIELD_NOT_FOUND",
                message=f"field '{fname}' not in layer",
                user_friendly=f"图层中没有字段 {fname}。",
                details={"available": available},
            )

    if label_field and label_field not in available:
        label_field = ""

    rows: List[Dict[str, Any]] = []
    numeric_columns: Dict[str, List[float]] = {f: [] for f in fields_param}
    if hasattr(layer, "getFeatures"):
        for feature in layer.getFeatures():
            row: Dict[str, Any] = {}
            if label_field:
                row[label_field] = _coerce_scalar(feature.attribute(label_field))
            for fname in fields_param:
                value = feature.attribute(fname)
                if value is not None:
                    try:
                        numeric_columns[fname].append(float(value))
                    except (TypeError, ValueError):
                        pass
                row[fname] = _coerce_scalar(value)
            rows.append(row)

    summary: Dict[str, Any] = {"count": len(rows)}
    for fname, values in numeric_columns.items():
        if not values:
            continue
        summary[f"{fname}_min"] = float(min(values))
        summary[f"{fname}_max"] = float(max(values))
        summary[f"{fname}_mean"] = float(statistics.fmean(values))
        summary[f"{fname}_sum"] = float(sum(values))

    rows_sorted = rows
    if fields_param and rows:
        primary = fields_param[0]
        rows_sorted = sorted(
            rows,
            key=lambda r: (-(r.get(primary) if isinstance(r.get(primary), (int, float)) else float("-inf"))),
        )
    top_rows = rows_sorted[: max(0, top)]

    out_payload = {
        "title": title,
        "fields": ([label_field] if label_field else []) + list(fields_param),
        "rows": top_rows,
        "all_rows_count": len(rows),
        "summary": summary,
    }

    stats_path = workspace.alloc_output_path("stats", ".json")
    stats_path.write_text(json.dumps(out_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "stats": str(stats_path),
        "stats_relative": workspace.relative(stats_path),
        "summary": summary,
        "fields": out_payload["fields"],
        "row_count": len(rows),
    }


def _coerce_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (int, float, bool, str)):
        return value
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return str(value)
