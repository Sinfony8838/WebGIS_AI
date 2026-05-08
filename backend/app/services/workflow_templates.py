"""Built-in workflow templates.

For Phase 1 we don't let the AI emit free-form workflow JSON. Instead the
backend matches the user message against a small library of templates and
fills in their parameters. Each template is responsible for producing a
ready-to-validate workflow JSON document.

The matching logic is intentionally rule-based so the system runs even
without a working LLM; the AI layer can later override / refine the chosen
template's parameters.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple


@dataclass
class TemplateMatch:
    template_id: str
    intent: str
    workflow: Dict[str, Any]
    parameters: Dict[str, Any]


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------

_NUM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(km|公里|千米|m|米)", re.IGNORECASE)


def _detect_distance_meters(text: str, default: float) -> float:
    match = _NUM_RE.search(text)
    if not match:
        return default
    value = float(match.group(1))
    unit = match.group(2).lower()
    if unit in {"km", "公里", "千米"}:
        return value * 1000.0
    return value


def _has_any(text: str, tokens: Tuple[str, ...]) -> bool:
    lower = text.lower()
    return any(t.lower() in lower for t in tokens)


# ---------------------------------------------------------------------------
# Template builders
# ---------------------------------------------------------------------------


def _template_population_choropleth(message: str, params: Dict[str, Any]) -> TemplateMatch:
    dataset = str(params.get("dataset") or "china_provinces.geojson")
    population_field = str(params.get("population_field") or "population")
    area_field = str(params.get("area_field") or "area_km2")
    density_field = str(params.get("density_field") or "density")
    classes = int(params.get("classes", 5) or 5)
    method = str(params.get("method") or "jenks")
    color_ramp = str(params.get("color_ramp") or "YlOrRd")
    project_id = str(params.get("project_id") or "")

    workflow = {
        "version": "1.0",
        "intent": "制作人口密度分级设色图",
        "context": {"project_id": project_id, "user_message": message},
        "steps": [
            {
                "id": "s1",
                "op": "load_layer",
                "params": {
                    "source": dataset,
                    "project_id": project_id,
                    "layer_name": "population_layer",
                },
                "depends_on": [],
                "output_bindings": {"layer": "population_layer"},
            },
            {
                "id": "s2",
                "op": "fix_geometries",
                "params": {"input": "${s1.layer}"},
                "depends_on": ["s1"],
                "output_bindings": {"layer": "population_fixed"},
            },
            {
                "id": "s3",
                "op": "calculate_field",
                "params": {
                    "input": "${s2.layer}",
                    "field": density_field,
                    "expression": f'CASE WHEN "{area_field}" > 0 THEN "{population_field}" / "{area_field}" ELSE 0 END',
                    "type": "double",
                },
                "depends_on": ["s2"],
                "output_bindings": {"layer": "population_with_density"},
            },
            {
                "id": "s4",
                "op": "choropleth",
                "params": {
                    "input": "${s3.layer}",
                    "field": density_field,
                    "method": method,
                    "classes": classes,
                    "color_ramp": color_ramp,
                    "title": "人口密度分级设色图",
                    "legend_title": "人口密度",
                },
                "depends_on": ["s3"],
                "output_bindings": {"geojson": "thematic_geojson", "style": "thematic_style"},
            },
            {
                "id": "s5",
                "op": "aggregate_stats",
                "params": {
                    "input": "${s3.layer}",
                    "fields": [population_field, density_field],
                    "label_field": "name",
                    "top": 10,
                    "title": "人口密度统计",
                },
                "depends_on": ["s3"],
                "output_bindings": {"stats": "stats"},
            },
            {
                "id": "s6",
                "op": "export_map_png",
                "params": {
                    "layers": ["${s3.layer}"],
                    "extent": "${s3.extent}",
                    "name": "thematic_map",
                    "width": 1280,
                    "height": 960,
                },
                "depends_on": ["s4"],
                "output_bindings": {"png": "thematic_png"},
                "on_error": "skip",
            },
        ],
        "outputs": {
            "geojson": "${s4.geojson}",
            "style": "${s4.style}",
            "stats": "${s5.stats}",
            "png": "${s6.png}",
        },
    }
    return TemplateMatch(
        template_id="population_choropleth",
        intent="制作人口密度分级设色图",
        workflow=workflow,
        parameters={
            "dataset": dataset,
            "population_field": population_field,
            "area_field": area_field,
            "density_field": density_field,
            "classes": classes,
            "method": method,
            "color_ramp": color_ramp,
        },
    )


def _template_facility_buffer(message: str, params: Dict[str, Any]) -> TemplateMatch:
    facility_dataset = str(params.get("facility_dataset") or params.get("dataset") or "facilities.geojson")
    distance_m = float(params.get("distance_m") or _detect_distance_meters(message, 1000.0))
    project_id = str(params.get("project_id") or "")

    workflow = {
        "version": "1.0",
        "intent": "学校 / 医院缓冲区分析",
        "context": {"project_id": project_id, "user_message": message},
        "steps": [
            {
                "id": "s1",
                "op": "load_layer",
                "params": {"source": facility_dataset, "project_id": project_id, "layer_name": "facilities"},
                "output_bindings": {"layer": "facilities"},
            },
            {
                "id": "s2",
                "op": "fix_geometries",
                "params": {"input": "${s1.layer}"},
                "depends_on": ["s1"],
                "output_bindings": {"layer": "facilities_fixed"},
            },
            {
                "id": "s3",
                "op": "buffer",
                "params": {
                    "input": "${s2.layer}",
                    "distance": distance_m,
                    "segments": 16,
                    "auto_project": True,
                    "dissolve": True,
                },
                "depends_on": ["s2"],
                "output_bindings": {"layer": "service_area"},
            },
            {
                "id": "s4",
                "op": "export_geojson",
                "params": {"input": "${s3.layer}", "name": "service_area", "target_crs": "EPSG:4326"},
                "depends_on": ["s3"],
                "output_bindings": {"geojson": "service_area_geojson"},
            },
            {
                "id": "s5",
                "op": "aggregate_stats",
                "params": {"input": "${s2.layer}", "label_field": "name", "top": 20, "title": "设施清单"},
                "depends_on": ["s2"],
                "output_bindings": {"stats": "stats"},
            },
        ],
        "outputs": {
            "geojson": "${s4.geojson}",
            "stats": "${s5.stats}",
        },
    }
    return TemplateMatch(
        template_id="facility_buffer",
        intent=f"对设施进行 {int(distance_m)} 米缓冲区分析",
        workflow=workflow,
        parameters={"facility_dataset": facility_dataset, "distance_m": distance_m},
    )


def _template_hu_line_compare(message: str, params: Dict[str, Any]) -> TemplateMatch:
    province_dataset = str(params.get("province_dataset") or "china_provinces.geojson")
    population_field = str(params.get("population_field") or "population")
    area_field = str(params.get("area_field") or "area_km2")
    project_id = str(params.get("project_id") or "")

    workflow = {
        "version": "1.0",
        "intent": "胡焕庸线对比分析",
        "context": {"project_id": project_id, "user_message": message},
        "steps": [
            {
                "id": "s1",
                "op": "load_layer",
                "params": {"source": province_dataset, "project_id": project_id, "layer_name": "provinces"},
                "output_bindings": {"layer": "provinces"},
            },
            {
                "id": "s2",
                "op": "fix_geometries",
                "params": {"input": "${s1.layer}"},
                "depends_on": ["s1"],
                "output_bindings": {"layer": "provinces_fixed"},
            },
            {
                "id": "s3",
                "op": "calculate_field",
                "params": {
                    "input": "${s2.layer}",
                    "field": "density",
                    "expression": f'CASE WHEN "{area_field}" > 0 THEN "{population_field}" / "{area_field}" ELSE 0 END',
                    "type": "double",
                },
                "depends_on": ["s2"],
                "output_bindings": {"layer": "provinces_with_density"},
            },
            {
                "id": "s4",
                "op": "choropleth",
                "params": {
                    "input": "${s3.layer}",
                    "field": "density",
                    "method": "jenks",
                    "classes": 5,
                    "color_ramp": "RdYlBu",
                    "title": "胡焕庸线两侧人口密度",
                },
                "depends_on": ["s3"],
                "output_bindings": {"geojson": "thematic_geojson", "style": "thematic_style"},
            },
            {
                "id": "s5",
                "op": "aggregate_stats",
                "params": {
                    "input": "${s3.layer}",
                    "fields": [population_field, "density"],
                    "label_field": "name",
                    "top": 10,
                    "title": "胡焕庸线两侧统计",
                },
                "depends_on": ["s3"],
                "output_bindings": {"stats": "stats"},
            },
        ],
        "outputs": {
            "geojson": "${s4.geojson}",
            "style": "${s4.style}",
            "stats": "${s5.stats}",
        },
    }
    return TemplateMatch(
        template_id="hu_line_compare",
        intent="胡焕庸线对比分析",
        workflow=workflow,
        parameters={
            "province_dataset": province_dataset,
            "population_field": population_field,
            "area_field": area_field,
        },
    )


# ---------------------------------------------------------------------------
# Template registry + matcher
# ---------------------------------------------------------------------------


TEMPLATES: Dict[str, Callable[[str, Dict[str, Any]], TemplateMatch]] = {
    "population_choropleth": _template_population_choropleth,
    "facility_buffer": _template_facility_buffer,
    "hu_line_compare": _template_hu_line_compare,
}


def list_templates() -> List[Dict[str, Any]]:
    return [
        {"id": "population_choropleth", "title": "人口密度分级设色图", "description": "按人口/面积计算密度并分级设色"},
        {"id": "facility_buffer", "title": "设施缓冲区分析", "description": "对学校/医院/服务点做服务范围缓冲区"},
        {"id": "hu_line_compare", "title": "胡焕庸线对比分析", "description": "比较胡焕庸线两侧的人口分布"},
    ]


def detect_template(message: str) -> Optional[str]:
    """Pick a template id by keyword matching. Returns None if nothing matches."""
    if not message:
        return None
    text = message.strip()
    if _has_any(text, ("人口密度", "分级设色", "choropleth", "人口分布图", "密度分布")):
        return "population_choropleth"
    if _has_any(text, ("胡焕庸线", "胡线", "hu_line", "huhuanyong")):
        return "hu_line_compare"
    if _has_any(text, ("缓冲区", "缓冲", "服务范围", "service area", "buffer")):
        return "facility_buffer"
    return None


def expand_template(
    template_id: str,
    message: str,
    parameters: Optional[Dict[str, Any]] = None,
) -> TemplateMatch:
    builder = TEMPLATES.get(template_id)
    if builder is None:
        raise KeyError(f"unknown template: {template_id}")
    return builder(message, dict(parameters or {}))
