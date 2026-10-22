"""Small, deterministic capability retrieval for interaction planning."""
from __future__ import annotations
import re
from typing import Any, Dict, List

GROUPS = {
    "map": ("地图、底图、视角、图层与标注", "地图|地球|三维|二维|底图|图层|透明|放大|缩小|定位|标注|视角|颜色|面板", {"set_view", "switch_view_mode", "switch_basemap", "toggle_layer", "focus_layer", "set_layer_opacity", "style_layer", "reorder_layer", "draw_annotation", "open_panel", "apply_template", "measure"}),
    "profiles": ("测距与沿线人口地形双曲线", "测距|测线|连线|剖面|曲线|地形|北京|上海", {"create_measurement", "generate_profile", "compare_profiles"}),
    "analysis": ("空间分析与结构化查询", "分析|统计|缓冲|分级|覆盖|空间|人口|密度|设施|对比|比较|查询|搜索|筛选|结果|工作流|top", {"run_workflow", "build_workflow", "run_visual_query", "query_features", "search_poi", "explain_current_view"}),
    "teaching": ("创建独立教学草稿与探究题", "教案|教学|设计|题|探究|课|草稿|生成|编写|做成", {"draft_teaching", "explain_current_view"}),
    "classroom": ("现有班课与教学环节控制", "上课|下课|课堂|班课|环节|下一步|上一步", {"start_class_session", "end_class_session", "enter_lesson_stage"}),
    "materials": ("教学地图、资料与图片生成", "资料|素材|图片|插画|示意图|海报|课本|教材|教学地图", {"open_material", "toggle_teaching_map", "generate_image"}),
    "export": ("导出当前地图", "导出|截图|快照|保存地图", {"export_snapshot"}),
}

# The same DSL is executed by the existing whitelist-based QGIS worker.
OP_PARAMS = {
    "load_layer": "source=layer:<id> or a listed dataset id; layer_name?",
    "inspect_layer": "input; sample_size?",
    "reproject": "input,target_crs",
    "fix_geometries": "input",
    "filter_features": "input,expression (QGIS expression)",
    "calculate_field": "input,field,expression,type? (QGIS expression, never Python)",
    "buffer": "input,distance (meters),segments?,dissolve?",
    "choropleth": "input,field,classes?,method?,color_ramp?,title?",
    "aggregate_stats": "input,fields?,label_field?,top?,title?",
    "export_geojson": "input,name?,target_crs?",
    "export_style_json": "input,name?",
    "export_map_png": "layers (reference array),name?,width?,height?,extent?,background?",
    "clip": "input,clip_layer",
    "intersection": "input,overlay_layer",
    "spatial_join": "input,join_layer,predicate?,method?,fields_to_keep?,prefix?,discard_no_match?",
    "classify": "input,field,method?,classes?,output_field?",
    "zonal_stats": "input,raster (listed dataset id or layer reference),band?,statistics?,prefix?",
}
OP_KEYS = {
 "load_layer": {"source", "layer_name"}, "inspect_layer": {"input", "sample_size"},
 "reproject": {"input", "target_crs"}, "fix_geometries": {"input"},
 "filter_features": {"input", "expression"},
 "calculate_field": {"input", "field", "expression", "type", "field_length", "field_precision"},
 "buffer": {"input", "distance", "segments", "dissolve"},
 "choropleth": {"input", "field", "classes", "method", "color_ramp", "title", "legend_title"},
 "aggregate_stats": {"input", "fields", "label_field", "top", "title"},
 "export_geojson": {"input", "name", "target_crs"}, "export_style_json": {"input", "name"},
 "export_map_png": {"layers", "name", "width", "height", "extent", "background"},
 "clip": {"input", "clip_layer"}, "intersection": {"input", "overlay_layer"},
 "spatial_join": {"input", "join_layer", "predicate", "method", "fields_to_keep", "join_fields", "prefix", "discard_no_match"},
 "classify": {"input", "field", "classes", "method", "output_field"},
 "zonal_stats": {"input", "raster", "band", "statistics", "prefix"},
}


def select_catalog(message: str, tools: List[Dict[str, Any]], context: Dict[str, Any]) -> tuple:
    matched = [name for name, (_, pattern, _) in GROUPS.items() if re.search(pattern, message, re.I)]
    if not matched:
        matched = ["map"]
    names = set().union(*(GROUPS[group][2] for group in matched))
    # Current classroom constraints are checked again by the executor.
    selected = [tool for tool in tools if tool["name"] in names]
    available = {tool["name"] for tool in tools}
    return selected, [{"id": name, "description": description} for name, (description, _, names) in GROUPS.items() if names & available and (name != "teaching" or "draft_teaching" in available)]


def layer_catalog(project: Any) -> list:
    result = []
    for layer in project.layers:
        rows = (layer.data or {}).get("features") or []
        fields = sorted({str(key) for row in rows[:30] if isinstance(row, dict) for key in (row.get("properties") or {})})
        result.append({"layer_id": layer.layer_id, "source": "layer:" + layer.layer_id,
                       "name": layer.name, "fields": fields, "visible": layer.visible,
                       "geometry_type": layer.geometry_type, "data_rev": layer.data_rev,
                       "feature_count": len(rows) if "features" in (layer.data or {}) else None, "crs": "EPSG:4326"})
    return result
