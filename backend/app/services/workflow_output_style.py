"""Attach workflow rendering metadata without changing analytical attributes."""
from __future__ import annotations

import json
import math


def artifact_style(config, record):
    if record is None:
        return {}
    root = config.workflow_dir(record.workflow_id).resolve()
    for artifact in record.artifacts:
        if artifact.get("kind") != "style":
            continue
        path = (root / str(artifact.get("relative_path") or "")).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if value.get("type") in {"simple", "graduated"}:
                return value
        except (OSError, ValueError):
            continue
    return {}


def decorate_features(data, style):
    for feature in data.get("features", []):
        props = feature.get("properties") or {}
        feature["properties"] = props
        color = style.get("color", "#60a5fa")
        if style.get("type") == "graduated":
            color = (style.get("default") or {}).get("color", "#cccccc")
            value = props.get(style.get("field"))
            try:
                number = float(value) if value is not None and value != "" else math.nan
            except (TypeError, ValueError):
                number = math.nan
            for entry in style.get("classes", []):
                if math.isfinite(number) and entry["min"] <= number <= entry["max"]:
                    color = entry["color"]
                    break
        props["__fillColor"] = color
        props["__fillOpacity"] = 0.85 if style.get("type") == "graduated" else 0.3
        props["__strokeColor"] = (style.get("stroke") or {}).get("color", "#1d4ed8")
        props["__strokeWidth"] = (style.get("stroke") or {}).get("width", 1.6)
        props["__radius"] = (style.get("point") or {}).get("radius", 6)
