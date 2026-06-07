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
    dataset = str(params.get("dataset") or "builtin:population/china_provinces.geojson")
    population_field = str(params.get("population_field") or "population")
    # area_field optional: if empty, we skip the derivation step and classify
    # directly on density_field (or population_field as fallback). This makes
    # the template usable against datasets that already carry a density column.
    area_field = str(params.get("area_field") or "").strip()
    density_field = str(params.get("density_field") or "density")
    classes = int(params.get("classes", 5) or 5)
    method = str(params.get("method") or "jenks")
    color_ramp = str(params.get("color_ramp") or "YlOrRd")
    project_id = str(params.get("project_id") or "")

    steps: List[Dict[str, Any]] = [
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
    ]

    if area_field:
        steps.append({
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
        })
        thematic_input_id = "s3"
        thematic_field = density_field
    else:
        thematic_input_id = "s2"
        thematic_field = density_field or population_field

    steps.extend([
        {
            "id": "s4",
            "op": "choropleth",
            "params": {
                "input": f"${{{thematic_input_id}.layer}}",
                "field": thematic_field,
                "method": method,
                "classes": classes,
                "color_ramp": color_ramp,
                "title": "人口密度分级设色图",
                "legend_title": "人口密度",
            },
            "depends_on": [thematic_input_id],
            "output_bindings": {"geojson": "thematic_geojson", "style": "thematic_style"},
        },
        {
            "id": "s5",
            "op": "aggregate_stats",
            "params": {
                "input": f"${{{thematic_input_id}.layer}}",
                "fields": [population_field, thematic_field] if thematic_field != population_field else [population_field],
                "label_field": "name",
                "top": 10,
                "title": "人口密度统计",
            },
            "depends_on": [thematic_input_id],
            "output_bindings": {"stats": "stats"},
        },
        {
            "id": "s6",
            "op": "export_map_png",
            "params": {
                "layers": [f"${{{thematic_input_id}.layer}}"],
                "extent": f"${{{thematic_input_id}.extent}}",
                "name": "thematic_map",
                "width": 1280,
                "height": 960,
            },
            "depends_on": ["s4"],
            "output_bindings": {"png": "thematic_png"},
            "on_error": "skip",
        },
    ])

    workflow = {
        "version": "1.0",
        "intent": "制作人口密度分级设色图",
        "context": {"project_id": project_id, "user_message": message},
        "steps": steps,
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
    facility_dataset = str(
        params.get("facility_dataset")
        or params.get("dataset")
        or "builtin:population/population_centroids.geojson"
    )
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
    province_dataset = str(
        params.get("province_dataset") or "builtin:population/china_provinces.geojson"
    )
    population_field = str(params.get("population_field") or "population")
    area_field = str(params.get("area_field") or "").strip()
    density_field = str(params.get("density_field") or "density")
    project_id = str(params.get("project_id") or "")

    steps: List[Dict[str, Any]] = [
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
    ]

    if area_field:
        steps.append({
            "id": "s3",
            "op": "calculate_field",
            "params": {
                "input": "${s2.layer}",
                "field": density_field,
                "expression": f'CASE WHEN "{area_field}" > 0 THEN "{population_field}" / "{area_field}" ELSE 0 END',
                "type": "double",
            },
            "depends_on": ["s2"],
            "output_bindings": {"layer": "provinces_with_density"},
        })
        thematic_input_id = "s3"
        thematic_field = density_field
    else:
        thematic_input_id = "s2"
        thematic_field = density_field or population_field

    steps.extend([
        {
            "id": "s4",
            "op": "choropleth",
            "params": {
                "input": f"${{{thematic_input_id}.layer}}",
                "field": thematic_field,
                "method": "jenks",
                "classes": 5,
                "color_ramp": "RdYlBu",
                "title": "胡焕庸线两侧人口密度",
            },
            "depends_on": [thematic_input_id],
            "output_bindings": {"geojson": "thematic_geojson", "style": "thematic_style"},
        },
        {
            "id": "s5",
            "op": "aggregate_stats",
            "params": {
                "input": f"${{{thematic_input_id}.layer}}",
                "fields": [population_field, thematic_field] if thematic_field != population_field else [population_field],
                "label_field": "name",
                "top": 10,
                "title": "胡焕庸线两侧统计",
            },
            "depends_on": [thematic_input_id],
            "output_bindings": {"stats": "stats"},
        },
    ])

    workflow = {
        "version": "1.0",
        "intent": "胡焕庸线对比分析",
        "context": {"project_id": project_id, "user_message": message},
        "steps": steps,
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
            "density_field": density_field,
        },
    )


# ---------------------------------------------------------------------------
# Template registry + matcher
# ---------------------------------------------------------------------------


def _template_clip_to_region(message: str, params: Dict[str, Any]) -> TemplateMatch:
    """Clip an input layer down to the geometry of a region layer.

    Typical classroom use: "把全国 POI 裁剪到长三角范围", "把人口分布裁剪到黄河流域".
    Parameter override hooks:
      - ``input_dataset`` / ``dataset``: dataset id for the input being clipped
      - ``region_dataset``: dataset id for the clipping region
      - ``layer_name``: friendly name for the clipped output
    """
    input_dataset = str(
        params.get("input_dataset")
        or params.get("dataset")
        or "builtin:population/population_centroids.geojson"
    )
    region_dataset = str(
        params.get("region_dataset")
        or "builtin:population/china_provinces.geojson"
    )
    output_name = str(params.get("layer_name") or "clipped")
    project_id = str(params.get("project_id") or "")

    workflow = {
        "version": "1.0",
        "intent": "区域裁剪分析",
        "context": {"project_id": project_id, "user_message": message},
        "steps": [
            {
                "id": "s1",
                "op": "load_layer",
                "params": {"source": input_dataset, "project_id": project_id, "layer_name": "input"},
                "output_bindings": {"layer": "input_layer"},
            },
            {
                "id": "s2",
                "op": "fix_geometries",
                "params": {"input": "${s1.layer}"},
                "depends_on": ["s1"],
                "output_bindings": {"layer": "input_fixed"},
            },
            {
                "id": "s3",
                "op": "load_layer",
                "params": {"source": region_dataset, "project_id": project_id, "layer_name": "region"},
                "output_bindings": {"layer": "region_layer"},
            },
            {
                "id": "s4",
                "op": "fix_geometries",
                "params": {"input": "${s3.layer}"},
                "depends_on": ["s3"],
                "output_bindings": {"layer": "region_fixed"},
            },
            {
                "id": "s5",
                "op": "clip",
                "params": {"input": "${s2.layer}", "clip_layer": "${s4.layer}"},
                "depends_on": ["s2", "s4"],
                "output_bindings": {"layer": "clipped"},
            },
            {
                "id": "s6",
                "op": "export_geojson",
                "params": {"input": "${s5.layer}", "name": output_name, "target_crs": "EPSG:4326"},
                "depends_on": ["s5"],
                "output_bindings": {"geojson": "clipped_geojson"},
            },
            {
                "id": "s7",
                "op": "aggregate_stats",
                "params": {"input": "${s5.layer}", "title": "裁剪后要素摘要", "top": 20},
                "depends_on": ["s5"],
                "output_bindings": {"stats": "stats"},
            },
        ],
        "outputs": {
            "geojson": "${s6.geojson}",
            "stats": "${s7.stats}",
        },
    }
    return TemplateMatch(
        template_id="clip_to_region",
        intent="区域裁剪分析",
        workflow=workflow,
        parameters={"input_dataset": input_dataset, "region_dataset": region_dataset},
    )


def _template_overlay_intersection(message: str, params: Dict[str, Any]) -> TemplateMatch:
    """Compute the geometric intersection of two layers, merging attributes.

    Typical use: 把人口分布与气候带求交集 → 每块人口落在哪个气候带。
    """
    input_dataset = str(
        params.get("input_dataset")
        or params.get("dataset")
        or "builtin:population/migration_flows.geojson"
    )
    overlay_dataset = str(
        params.get("overlay_dataset")
        or "builtin:population/china_provinces.geojson"
    )
    output_name = str(params.get("layer_name") or "intersected")
    project_id = str(params.get("project_id") or "")

    workflow = {
        "version": "1.0",
        "intent": "图层求交集",
        "context": {"project_id": project_id, "user_message": message},
        "steps": [
            {
                "id": "s1",
                "op": "load_layer",
                "params": {"source": input_dataset, "project_id": project_id, "layer_name": "input"},
                "output_bindings": {"layer": "input_layer"},
            },
            {
                "id": "s2",
                "op": "fix_geometries",
                "params": {"input": "${s1.layer}"},
                "depends_on": ["s1"],
                "output_bindings": {"layer": "input_fixed"},
            },
            {
                "id": "s3",
                "op": "load_layer",
                "params": {"source": overlay_dataset, "project_id": project_id, "layer_name": "overlay"},
                "output_bindings": {"layer": "overlay_layer"},
            },
            {
                "id": "s4",
                "op": "fix_geometries",
                "params": {"input": "${s3.layer}"},
                "depends_on": ["s3"],
                "output_bindings": {"layer": "overlay_fixed"},
            },
            {
                "id": "s5",
                "op": "intersection",
                "params": {"input": "${s2.layer}", "overlay_layer": "${s4.layer}"},
                "depends_on": ["s2", "s4"],
                "output_bindings": {"layer": "intersected"},
            },
            {
                "id": "s6",
                "op": "export_geojson",
                "params": {"input": "${s5.layer}", "name": output_name, "target_crs": "EPSG:4326"},
                "depends_on": ["s5"],
                "output_bindings": {"geojson": "intersected_geojson"},
            },
            {
                "id": "s7",
                "op": "aggregate_stats",
                "params": {"input": "${s5.layer}", "title": "交集要素摘要", "top": 20},
                "depends_on": ["s5"],
                "output_bindings": {"stats": "stats"},
            },
        ],
        "outputs": {
            "geojson": "${s6.geojson}",
            "stats": "${s7.stats}",
        },
    }
    return TemplateMatch(
        template_id="overlay_intersection",
        intent="图层求交集",
        workflow=workflow,
        parameters={"input_dataset": input_dataset, "overlay_dataset": overlay_dataset},
    )


def _template_spatial_join_attributes(message: str, params: Dict[str, Any]) -> TemplateMatch:
    """Spatial-join right layer's attributes onto left features by predicate.

    Typical use: 把学校点和行政区做空间连接, 让每所学校带上所在区县属性。
    """
    input_dataset = str(
        params.get("input_dataset")
        or params.get("dataset")
        or "builtin:population/population_centroids.geojson"
    )
    join_dataset = str(
        params.get("join_dataset")
        or "builtin:population/china_provinces.geojson"
    )
    predicate = str(params.get("predicate") or "intersects").lower()
    output_name = str(params.get("layer_name") or "spatial_joined")
    project_id = str(params.get("project_id") or "")

    workflow = {
        "version": "1.0",
        "intent": "图层空间连接",
        "context": {"project_id": project_id, "user_message": message},
        "steps": [
            {
                "id": "s1",
                "op": "load_layer",
                "params": {"source": input_dataset, "project_id": project_id, "layer_name": "input"},
                "output_bindings": {"layer": "input_layer"},
            },
            {
                "id": "s2",
                "op": "fix_geometries",
                "params": {"input": "${s1.layer}"},
                "depends_on": ["s1"],
                "output_bindings": {"layer": "input_fixed"},
            },
            {
                "id": "s3",
                "op": "load_layer",
                "params": {"source": join_dataset, "project_id": project_id, "layer_name": "join"},
                "output_bindings": {"layer": "join_layer"},
            },
            {
                "id": "s4",
                "op": "fix_geometries",
                "params": {"input": "${s3.layer}"},
                "depends_on": ["s3"],
                "output_bindings": {"layer": "join_fixed"},
            },
            {
                "id": "s5",
                "op": "spatial_join",
                "params": {
                    "input": "${s2.layer}",
                    "join_layer": "${s4.layer}",
                    "predicate": predicate,
                    "method": "1_to_1",
                },
                "depends_on": ["s2", "s4"],
                "output_bindings": {"layer": "joined"},
            },
            {
                "id": "s6",
                "op": "export_geojson",
                "params": {"input": "${s5.layer}", "name": output_name, "target_crs": "EPSG:4326"},
                "depends_on": ["s5"],
                "output_bindings": {"geojson": "joined_geojson"},
            },
            {
                "id": "s7",
                "op": "aggregate_stats",
                "params": {"input": "${s5.layer}", "title": "连接后要素摘要", "top": 20},
                "depends_on": ["s5"],
                "output_bindings": {"stats": "stats"},
            },
        ],
        "outputs": {
            "geojson": "${s6.geojson}",
            "stats": "${s7.stats}",
        },
    }
    return TemplateMatch(
        template_id="spatial_join_attributes",
        intent="图层空间连接",
        workflow=workflow,
        parameters={"input_dataset": input_dataset, "join_dataset": join_dataset, "predicate": predicate},
    )


def _template_classify_field(message: str, params: Dict[str, Any]) -> TemplateMatch:
    """Bin a numeric field into N classes; add class_id column.

    Typical use: 把人口密度分成 5 级, 把降水量按四等分分级。
    Pure data transformation; downstream steps can group_by the class_id.
    """
    dataset = str(params.get("dataset") or "builtin:population/china_provinces.geojson")
    field = str(params.get("field") or "population")
    classes = int(params.get("classes", 5) or 5)
    method = str(params.get("method") or "jenks").lower()
    project_id = str(params.get("project_id") or "")
    output_field = str(params.get("output_field") or f"{field}_class")

    workflow = {
        "version": "1.0",
        "intent": "字段分级",
        "context": {"project_id": project_id, "user_message": message},
        "steps": [
            {
                "id": "s1",
                "op": "load_layer",
                "params": {"source": dataset, "project_id": project_id, "layer_name": "input"},
                "output_bindings": {"layer": "input_layer"},
            },
            {
                "id": "s2",
                "op": "fix_geometries",
                "params": {"input": "${s1.layer}"},
                "depends_on": ["s1"],
                "output_bindings": {"layer": "input_fixed"},
            },
            {
                "id": "s3",
                "op": "classify",
                "params": {
                    "input": "${s2.layer}",
                    "field": field,
                    "classes": classes,
                    "method": method,
                    "output_field": output_field,
                },
                "depends_on": ["s2"],
                "output_bindings": {"layer": "classified"},
            },
            {
                "id": "s4",
                "op": "export_geojson",
                "params": {"input": "${s3.layer}", "name": "classified", "target_crs": "EPSG:4326"},
                "depends_on": ["s3"],
                "output_bindings": {"geojson": "classified_geojson"},
            },
            {
                "id": "s5",
                "op": "aggregate_stats",
                "params": {"input": "${s3.layer}", "title": f"按 {field} 分级", "top": 20},
                "depends_on": ["s3"],
                "output_bindings": {"stats": "stats"},
            },
        ],
        "outputs": {
            "geojson": "${s4.geojson}",
            "stats": "${s5.stats}",
        },
    }
    return TemplateMatch(
        template_id="classify_field",
        intent=f"对 {field} 字段进行 {classes} 分级",
        workflow=workflow,
        parameters={"dataset": dataset, "field": field, "classes": classes, "method": method},
    )


TEMPLATES: Dict[str, Callable[[str, Dict[str, Any]], TemplateMatch]] = {
    "population_choropleth": _template_population_choropleth,
    "facility_buffer": _template_facility_buffer,
    "hu_line_compare": _template_hu_line_compare,
    "clip_to_region": _template_clip_to_region,
    "overlay_intersection": _template_overlay_intersection,
    "spatial_join_attributes": _template_spatial_join_attributes,
    "classify_field": _template_classify_field,
}


def list_templates() -> List[Dict[str, Any]]:
    return [
        {"id": "population_choropleth", "title": "人口密度分级设色图", "description": "按人口/面积计算密度并分级设色"},
        {"id": "facility_buffer", "title": "设施缓冲区分析", "description": "对学校/医院/服务点做服务范围缓冲区"},
        {"id": "hu_line_compare", "title": "胡焕庸线对比分析", "description": "比较胡焕庸线两侧的人口分布"},
        {"id": "clip_to_region", "title": "区域裁剪分析", "description": "把一个图层按区域图层裁剪到指定范围内"},
        {"id": "overlay_intersection", "title": "图层求交集", "description": "对两个图层求几何交集并合并属性"},
        {"id": "spatial_join_attributes", "title": "图层空间连接", "description": "按空间关系把右侧图层属性连接到左侧要素"},
        {"id": "classify_field", "title": "字段分级", "description": "对数值字段按 jenks/quantile/equal 等方法分级并写入新字段"},
    ]


def detect_template(message: str) -> Optional[str]:
    """Pick a template id by keyword matching. Returns None if nothing matches."""
    if not message:
        return None
    text = message.strip()
    # population_choropleth (graduated + color) is more specific than bare classify,
    # so it must be tested first.
    if _has_any(text, ("人口密度", "分级设色", "choropleth", "人口分布图", "密度分布")):
        return "population_choropleth"
    if _has_any(text, ("胡焕庸线", "胡线", "hu_line", "huhuanyong")):
        return "hu_line_compare"
    if _has_any(text, ("缓冲区", "缓冲", "服务范围", "service area", "buffer")):
        return "facility_buffer"
    # spatial_join MUST be tested before clip_to_region: phrases like
    # "落在哪个区" are intent-bearing for the join, while clip_to_region
    # keywords are about trimming geometry to a region.
    if _has_any(text, ("空间连接", "spatial join", "属性连接", "按位置连接", "落在哪个")):
        return "spatial_join_attributes"
    if _has_any(text, ("裁剪到", "裁到", "clip to", "范围内的", "区域裁剪")):
        return "clip_to_region"
    if _has_any(text, ("求交集", "交集", "intersection", "重叠区域", "相交部分")):
        return "overlay_intersection"
    if _has_any(text, ("分级", "分类", "classify", "等分", "quantile", "jenks")):
        return "classify_field"
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
