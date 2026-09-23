"""Read-only parameter resolution shared by preview and submission."""
from __future__ import annotations

import json
import math
import re
from typing import Any, Dict

from .workflow_executor import _resolve_dataset_for_preflight, run_preflight
from .workflow_templates import detect_template, expand_template
from .workflow_validator import validate_workflow

_DEFAULTS = {
    "facility_buffer": "builtin:population/population_centroids.geojson",
    "classify_field": "builtin:one_map/population/china_province_population_density.geojson",
}
_METHODS = {"等距": "equal", "equal": "equal", "equal_interval": "equal",
            "分位数": "quantile", "quantile": "quantile", "自然断点": "jenks",
            "jenks": "jenks", "natural_breaks": "jenks", "标准差": "stddev", "stddev": "stddev"}


def _numeric(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def inspect_fields(config, project_id: str, source: str):
    path = _resolve_dataset_for_preflight(config, source, project_id)
    if path is None or not path.is_file():
        raise ValueError("找不到当前项目可访问的数据集，请重新选择。")
    if path.suffix.lower() not in {".geojson", ".json"} or path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("参数预览支持不超过 32 MB 的 GeoJSON；请先导入为项目矢量图层。")
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
        raise ValueError("数据必须为 GeoJSON FeatureCollection。")
    values: Dict[str, list] = {}
    for feature in payload.get("features", []):
        for field, value in (feature.get("properties") or {}).items():
            bucket = values.setdefault(str(field), [0, 0])
            if value is not None:
                bucket[1] += 1
                bucket[0] += int(_numeric(value))
    return [{"name": field, "numeric": counts[0] > 0,
             "numeric_count": counts[0], "non_null_count": counts[1]} for field, counts in values.items()]


def prepare_workflow(config, project_id: str, message: str, template_id: str = "", parameters=None):
    params = dict(parameters or {})
    if params.get("project_id") is not None and str(params["project_id"]) != project_id:
        raise ValueError("parameters.project_id 与请求项目不一致")
    params["project_id"] = project_id
    message = message.replace(chr(96), "")
    chosen = template_id or detect_template(message) or "population_choropleth"
    issues = []
    fields = []
    origins = {}
    resolved = dict(params)

    def issue(field, text):
        issues.append({"field": field, "message": text, "user_friendly": text})

    def value(key, parsed, default):
        if key in params and params[key] is not None:
            origins[key] = "manual"
            return params[key]
        if parsed is not None:
            origins[key] = "message"
            return parsed
        origins[key] = "default"
        return default

    if chosen in _DEFAULTS:
        source = params.get("facility_dataset") if chosen == "facility_buffer" else params.get("input_dataset")
        source = str(params.get("dataset") or source or _DEFAULTS[chosen])
        resolved["dataset"] = source
        if chosen == "facility_buffer":
            resolved["facility_dataset"] = source
        try:
            fields = inspect_fields(config, project_id, source)
        except (ValueError, OSError) as exc:
            issue("dataset", str(exc))
        names = [f["name"] for f in fields]
        numeric = {f["name"] for f in fields if f["numeric"]}
        if chosen == "facility_buffer":
            distance_matches = list(re.finditer(r"(-?\d+(?:\.\d+)?)\s*(km|公里|千米|m|米)", message, re.I))
            specified = {float(m[1]) * (1000 if m[2].lower() in {"km", "公里", "千米"} else 1) for m in distance_matches}
            if len(specified) > 1 and "distance_m" not in params:
                issue("distance_m", "文字涉及多个距离，请在参数区明确缓冲距离。")
            match = distance_matches[0] if distance_matches else None
            parsed = float(match[1]) * (1000 if match[2].lower() in {"km", "公里", "千米"} else 1) if match else None
            resolved["distance_m"] = value("distance_m", parsed, 1000)
            try:
                distance = float(resolved["distance_m"])
                if isinstance(resolved["distance_m"], bool) or not math.isfinite(distance) or not 0 < distance <= 500000:
                    raise ValueError()
                resolved["distance_m"] = distance
            except (TypeError, ValueError):
                issue("distance_m", "距离必须大于 0 且不超过 500 公里。")
            merge = False if re.search(r"不合并|不融合|分别缓冲", message) else (True if re.search(r"合并|融合", message) else None)
            resolved["dissolve"] = value("dissolve", merge, True)
            if not isinstance(resolved["dissolve"], bool):
                issue("dissolve", "合并选项必须为布尔值。")
            label = next((name for name in ("name", "place", "title") if name in names), "")
            resolved["label_field"] = value("label_field", None, label)
            if resolved["label_field"] and resolved["label_field"] not in names:
                issue("label_field", "所选标签字段不存在，请重新选择或使用要素编号。")
        else:
            source_text = re.sub(r"(?:写入|输出字段(?:为|是)?|output_field\s*[=:]?)\s*[A-Za-z_]\w*", "", message)
            hits = [name for name in names if re.search(r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])", source_text)]
            explicit = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\s*(?:[（(][^）)]*[）)])?\s*字段", source_text)
            parsed_field = explicit[1] if explicit else (hits[0] if len(hits) == 1 else None)
            if len(hits) > 1 and "field" not in params and not explicit:
                issue("field", "文字涉及多个字段，请在参数区选择分级字段。")
            default_field = "population" if "population" in numeric and source == _DEFAULTS[chosen] else ""
            resolved["field"] = value("field", parsed_field, default_field)
            if not isinstance(resolved["field"], str) or resolved["field"] not in numeric:
                issue("field", "请选择数据中含有有效数值的分级字段。")
            count = re.search(r"(\d+|十二|十一|十|[二三四五六七八九两])\s*级", message)
            chinese = {"两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12}
            parsed_count = (int(count[1]) if count[1].isdigit() else chinese[count[1]]) if count else None
            resolved["classes"] = value("classes", parsed_count, 5)
            try:
                number = float(resolved["classes"])
                if not number.is_integer() or not 2 <= number <= 12:
                    raise ValueError()
                resolved["classes"] = int(number)
            except (TypeError, ValueError):
                issue("classes", "分级数必须是 2 到 12 的整数。")
            methods = {_METHODS[token] for token in _METHODS if re.search(r"(?<![A-Za-z_])" + token + r"(?![A-Za-z_])", message, re.I)}
            if len(methods) > 1 and "method" not in params:
                issue("method", "文字涉及多个分级方法，请在参数区选择。")
            method = value("method", next(iter(methods)) if len(methods) == 1 else None, "jenks")
            resolved["method"] = _METHODS.get(str(method).lower(), str(method).lower())
            if resolved["method"] not in {"equal", "quantile", "jenks", "stddev"}:
                issue("method", "请选择等距、分位数、自然断点或标准差。")
            output = re.search(r"(?:写入|输出字段(?:为|是)?|output_field\s*[=:]?)\s*[‘“\"']?([A-Za-z_]\w*)", message)
            default_output = f"{resolved['field']}_class" if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(resolved["field"])) else "class_id"
            resolved["output_field"] = value("output_field", output[1] if output else None, default_output)
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", str(resolved["output_field"])):
                issue("output_field", "输出字段请使用不超过 63 字符的英文字母、数字和下划线，不能以数字开头。")
            elif resolved["output_field"] in names:
                issue("output_field", "输出字段已存在，请使用新的字段名。")

    preview = {"status": "success", "valid": not issues, "template_id": chosen, "parameters": resolved,
               "parameter_sources": origins, "fields": fields, "issues": issues}
    if issues:
        return preview, None
    match = expand_template(chosen, message, resolved)
    validation = validate_workflow(match.workflow)
    if not validation.valid:
        issues.extend(e.to_dict() for e in validation.errors)
    else:
        errors, _warnings = run_preflight(config, match.workflow)
        issues.extend(e.to_dict() for e in errors)
    preview.update(valid=not issues, intent=match.intent)
    return preview, match
