from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from ..config import AppConfig
from ..models import ProjectRecord


ASSISTANT_TOOL_SCHEMA = [
    {"name": "set_view", "description": "调整课堂地图视角。", "parameters": {"center": "number[2]", "zoom": "number", "extent": "number[4]?"}},
    {"name": "toggle_layer", "description": "显示或隐藏指定图层。", "parameters": {"layer_id": "string", "visible": "boolean"}},
    {"name": "reorder_layer", "description": "调整图层前后顺序。", "parameters": {"layer_id": "string", "z_index": "number"}},
    {"name": "style_layer", "description": "修改图层颜色、透明度、标注等样式。", "parameters": {"layer_id": "string", "style": "object"}},
    {"name": "query_features", "description": "查询当前图层或关注要素的属性摘要。", "parameters": {"layer_id": "string?", "limit": "number?"}},
    {"name": "draw_annotation", "description": "在当前课堂地图上写入标注。", "parameters": {"text": "string", "position": "number[2]?"}},
    {"name": "measure", "description": "输出当前视域或选中对象的距离/尺度说明。", "parameters": {"mode": "string", "extent": "number[4]?"}},
    {"name": "apply_template", "description": "加载或切换教学模板。", "parameters": {"template_id": "string"}},
    {"name": "export_snapshot", "description": "触发课堂截图导出。", "parameters": {"title": "string?"}},
    {"name": "explain_current_view", "description": "围绕当前地图画面给出讲解话术。", "parameters": {"focus": "string?"}},
    {"name": "switch_basemap", "description": "切换课堂底图风格。", "parameters": {"basemap_id": "string"}},
    {"name": "search_poi", "description": "在当前视域或手绘区域内检索 POI。", "parameters": {"keyword": "string", "mode": "string?", "extent": "number[4]?", "geometry": "object?"}},
]


COLOR_MAP = {
    "yellow": "#facc15",
    "黄色": "#facc15",
    "blue": "#3b82f6",
    "蓝色": "#3b82f6",
    "red": "#ef4444",
    "红色": "#ef4444",
    "green": "#22c55e",
    "绿色": "#22c55e",
    "orange": "#f97316",
    "橙色": "#f97316",
    "white": "#f8fafc",
    "白色": "#f8fafc",
    "black": "#0f172a",
    "黑色": "#0f172a",
}


BASEMAP_MAP = {
    "标准": "amap_vector",
    "普通": "amap_vector",
    "地图": "amap_vector",
    "浅灰": "amap_light",
    "浅色": "amap_light",
    "灰色": "amap_light",
    "影像": "amap_imagery",
    "卫星": "amap_imagery",
    "遥感": "amap_imagery",
}


class AssistantService:
    def __init__(self, config: AppConfig):
        self.config = config

    def plan_actions(
        self,
        message: str,
        project: ProjectRecord,
        map_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        map_context = map_context or {}
        lowered = (message or "").lower()
        actions: List[Dict[str, Any]] = []
        narrative_parts: List[str] = []
        target_layer = self._resolve_target_layer(message, project)
        active_layer = next((layer for layer in project.layers if layer.layer_id == project.active_layer_id), None)
        search_result = self._resolve_search_result(message, project)

        template_action = self._resolve_template_action(lowered)
        if template_action:
            actions.append(template_action)
            narrative_parts.append(template_action["narrative"])

        basemap_id = self._extract_basemap_id(message)
        if basemap_id:
            actions.append({"tool_name": "switch_basemap", "tool_params": {"basemap_id": basemap_id}})
            narrative_parts.append("我会先切换到更合适的课堂底图。")

        if any(keyword in lowered for keyword in ["隐藏", "关闭", "hide"]) and target_layer:
            actions.append({"tool_name": "toggle_layer", "tool_params": {"layer_id": target_layer["layer_id"], "visible": False}})
            narrative_parts.append(f"我会先隐藏图层“{target_layer['name']}”。")
        elif any(keyword in lowered for keyword in ["显示", "打开", "show"]) and target_layer:
            actions.append({"tool_name": "toggle_layer", "tool_params": {"layer_id": target_layer["layer_id"], "visible": True}})
            narrative_parts.append(f"我会把图层“{target_layer['name']}”重新显示出来。")

        requested_color = self._extract_requested_color(message)
        if requested_color:
            style_target = target_layer or (active_layer.to_dict() if active_layer else None)
            if style_target:
                actions.append(
                    {
                        "tool_name": "style_layer",
                        "tool_params": {
                            "layer_id": style_target["layer_id"],
                            "style": {"fillColor": requested_color, "strokeColor": "#ffffff"},
                        },
                    }
                )
                narrative_parts.append(f"我会把图层“{style_target['name']}”改成你要求的颜色。")

        if any(keyword in lowered for keyword in ["置顶", "最上面", "顶层"]) and target_layer:
            max_z = max([layer.z_index for layer in project.layers] or [0])
            actions.append({"tool_name": "reorder_layer", "tool_params": {"layer_id": target_layer["layer_id"], "z_index": max_z + 10}})
            narrative_parts.append(f"我会把图层“{target_layer['name']}”移到更上层。")

        if any(keyword in lowered for keyword in ["回到中国", "查看中国", "复位", "reset"]) or "china" in lowered:
            actions.append(
                {
                    "tool_name": "set_view",
                    "tool_params": {"center": [104.0, 35.0], "zoom": 4, "extent": [78.0, 18.0, 132.0, 50.5]},
                }
            )
            narrative_parts.append("我会先把视角拉回中国范围。")

        poi_action = self._resolve_poi_action(message, lowered, map_context)
        if poi_action:
            actions.append(poi_action)
            narrative_parts.append("我会在当前课堂范围内执行 POI 检索。")

        if search_result and any(keyword in lowered for keyword in ["定位", "飞到", "聚焦", "跳到"]):
            actions.append(
                {
                    "tool_name": "set_view",
                    "tool_params": {
                        "center": search_result["coordinates"],
                        "zoom": max(int(map_context.get("zoom") or project.view.get("zoom") or 4), 11),
                    },
                }
            )
            narrative_parts.append(f"我会把视角飞到“{search_result['name']}”附近。")

        if any(keyword in lowered for keyword in ["讲解", "解释", "分析", "读图", "说明"]):
            actions.append({"tool_name": "explain_current_view", "tool_params": {"focus": message.strip()}})
            narrative_parts.append("然后我会根据当前画面给出可直接上课使用的讲解。")

        if any(keyword in lowered for keyword in ["图层", "属性", "有哪些", "query"]) and "课堂" not in lowered:
            actions.append({"tool_name": "query_features", "tool_params": {"layer_id": target_layer["layer_id"] if target_layer else project.active_layer_id, "limit": 5}})
            narrative_parts.append("我会补充当前图层的要素摘要。")

        if any(keyword in lowered for keyword in ["标注", "注释", "annotation"]):
            text = self._extract_annotation_text(message)
            position = map_context.get("center") or project.view.get("center") or [104.0, 35.0]
            actions.append({"tool_name": "draw_annotation", "tool_params": {"text": text, "position": position}})
            narrative_parts.append("我会在当前视图位置添加课堂标注。")

        if any(keyword in lowered for keyword in ["测量", "尺度", "距离", "measure"]):
            actions.append({"tool_name": "measure", "tool_params": {"mode": "extent", "extent": map_context.get("extent")}})
            narrative_parts.append("我会补充当前视域的尺度说明。")

        if any(keyword in lowered for keyword in ["截图", "导出", "snapshot", "export"]):
            actions.append({"tool_name": "export_snapshot", "tool_params": {"title": "课堂导图"}})
            narrative_parts.append("最后我会提示你导出当前课堂画面。")

        if not actions:
            actions.append({"tool_name": "explain_current_view", "tool_params": {"focus": message.strip()}})
            narrative_parts.append("我先基于当前地图画面给出可直接使用的讲解。")

        return {"assistant_message": "".join(narrative_parts), "actions": actions}

    def compose_explanation(
        self,
        project: ProjectRecord,
        map_context: Optional[Dict[str, Any]] = None,
        focus: str = "",
    ) -> str:
        visible_layers = [layer for layer in project.layers if layer.visible]
        layer_names = "、".join(layer.name for layer in visible_layers[:4]) or "当前底图"
        lines = [f"当前画面以 {layer_names} 为主。"]
        enabled = set(project.enabled_templates)
        if "population_distribution" in enabled or any("人口分布" in layer.name for layer in visible_layers):
            lines.append("从人口分布看，东部与中部人口明显更集中，而西北地区人口规模和密度都更低。")
        if "population_density" in enabled or any("人口密度" in layer.name for layer in visible_layers):
            lines.append("点状密度符号可以帮助学生快速识别高密度中心，观察集聚与扩散的空间差异。")
        if "population_migration" in enabled or any("人口迁移" in layer.name for layer in visible_layers):
            lines.append("迁移流线显示人口持续向沿海和核心城市带集中，这背后对应就业机会和交通可达性的差异。")
        if "hu_line_comparison" in enabled or any("胡焕庸线" in layer.name for layer in visible_layers):
            lines.append("胡焕庸线把中国人口格局分成东南密集、西北稀疏两大区域，是人口地理最直观的综合分界。")
        if "generic_classroom_pack" in enabled or any("欧亚区域框架" in layer.name for layer in visible_layers):
            lines.append("如果把课堂焦点放在欧亚区域框架上，可以顺带讲清海陆位置、交通廊道和区域联系。")
        poi_layer = next((layer for layer in visible_layers if layer.layer_id == "poi_search_results"), None)
        if poi_layer:
            keyword = poi_layer.metadata.get("keyword") or "课堂检索结果"
            lines.append(f"当前画面还叠加了“{keyword}”相关 POI 结果，适合结合区位条件做即时读图分析。")
        if focus:
            lines.append(f"本次讲解重点是：{focus.strip()}。")
        return "\n".join(lines)

    def compose_feature_summary(self, project: ProjectRecord, layer_id: str = "", limit: int = 5) -> str:
        target = None
        for layer in project.layers:
            if layer.layer_id == layer_id:
                target = layer
                break
        if target is None:
            target = next((layer for layer in project.layers if layer.visible), None)
        if target is None:
            return "当前项目中还没有可查询的图层。"
        features = target.data.get("features", [])
        if not features:
            return f"图层“{target.name}”目前没有可直接读取的要素。"
        rows = []
        for feature in features[:limit]:
            properties = feature.get("properties", {})
            name = properties.get("name") or properties.get("origin") or "未命名要素"
            key_values = []
            for key in ("population", "density", "migrants", "theme", "focus", "address", "district"):
                if key in properties and str(properties[key]).strip():
                    key_values.append(f"{key}={properties[key]}")
            row = f"- {name}"
            if key_values:
                row += f"（{'，'.join(key_values)}）"
            rows.append(row)
        return f"图层“{target.name}”当前要素摘要：\n" + "\n".join(rows)

    def compose_measurement(self, extent: Optional[List[float]]) -> str:
        if not extent or len(extent) != 4:
            return "当前没有足够的视域信息，暂时无法给出尺度说明。"
        west, south, east, north = [float(value) for value in extent]
        width_degrees = abs(east - west)
        height_degrees = abs(north - south)
        mid_latitude = (north + south) / 2.0
        approximate_width_km = width_degrees * 111.32 * max(0.1, math.cos(math.radians(mid_latitude)))
        approximate_height_km = height_degrees * 111.32
        return "当前视域的近似尺度为：" f"东西约 {approximate_width_km:.0f} 千米，南北约 {approximate_height_km:.0f} 千米。"

    def build_export_hint(self) -> str:
        return "当前任务包含导出意图。请点击顶部“导出截图”，系统会把当前课堂画面保存为本地成果。"

    def build_poi_hint(self, keyword: str, count: int) -> str:
        if count <= 0:
            return f"当前范围内没有检索到“{keyword}”相关结果。"
        return f"当前范围内已找到 {count} 条“{keyword}”相关结果，结果已经同步到左侧检索面板和地图点位。"

    def _resolve_target_layer(self, message: str, project: ProjectRecord) -> Optional[Dict[str, Any]]:
        lowered = (message or "").lower()
        for layer in project.layers:
            if layer.name.lower() in lowered:
                return layer.to_dict()
        if project.active_layer_id:
            for layer in project.layers:
                if layer.layer_id == project.active_layer_id:
                    return layer.to_dict()
        return None

    def _resolve_template_action(self, lowered: str) -> Optional[Dict[str, Any]]:
        if any(keyword in lowered for keyword in ["人口专题", "人口包", "population pack"]):
            return {"tool_name": "apply_template", "tool_params": {"template_id": "population_classroom_pack"}, "narrative": "我先切到人口专题课堂包。"}
        if any(keyword in lowered for keyword in ["通用课堂", "区域框架", "欧亚", "generic"]):
            return {"tool_name": "apply_template", "tool_params": {"template_id": "generic_classroom_pack"}, "narrative": "我先加载通用地理课堂包。"}
        if any(keyword in lowered for keyword in ["人口分布", "分布图"]):
            return {"tool_name": "apply_template", "tool_params": {"template_id": "population_distribution"}, "narrative": "我先切到人口分布模板。"}
        if any(keyword in lowered for keyword in ["人口密度", "密度图", "热力"]):
            return {"tool_name": "apply_template", "tool_params": {"template_id": "population_density"}, "narrative": "我先切到人口密度模板。"}
        if any(keyword in lowered for keyword in ["人口迁移", "迁移图", "迁移"]):
            return {"tool_name": "apply_template", "tool_params": {"template_id": "population_migration"}, "narrative": "我先切到人口迁移模板。"}
        if any(keyword in lowered for keyword in ["胡焕庸", "hu line"]):
            return {"tool_name": "apply_template", "tool_params": {"template_id": "hu_line_comparison"}, "narrative": "我先叠加胡焕庸线对比模板。"}
        return None

    def _extract_requested_color(self, message: str) -> str:
        lowered = (message or "").lower()
        for key, value in COLOR_MAP.items():
            if key in lowered:
                return value
        return ""

    def _extract_annotation_text(self, message: str) -> str:
        text = (message or "").strip()
        for separator in ("：", ":"):
            if separator in text:
                return text.split(separator, 1)[1].strip() or "课堂标注"
        return "课堂标注"

    def _extract_basemap_id(self, message: str) -> str:
        lowered = (message or "").lower()
        for key, basemap_id in BASEMAP_MAP.items():
            if key in lowered:
                return basemap_id
        return ""

    def _resolve_poi_action(self, message: str, lowered: str, map_context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not any(keyword in lowered for keyword in ["搜索", "查找", "poi", "附近", "找一下", "查一下"]):
            return None
        keyword = self._extract_poi_keyword(message)
        if not keyword:
            return None
        if any(token in lowered for token in ["手绘", "圈选", "绘制区域", "多边形", "区域内"]) and map_context.get("search_area_geometry"):
            return {
                "tool_name": "search_poi",
                "tool_params": {"keyword": keyword, "mode": "polygon", "geometry": map_context.get("search_area_geometry")},
            }
        return {
            "tool_name": "search_poi",
            "tool_params": {"keyword": keyword, "mode": "view", "extent": map_context.get("extent")},
        }

    def _extract_poi_keyword(self, message: str) -> str:
        cleaned = (message or "").strip()
        if "并" in cleaned:
            cleaned = cleaned.split("并", 1)[0]
        replacements = [
            "搜索当前区域内",
            "搜索当前视域内",
            "搜索当前视野内",
            "搜索当前范围内",
            "查找当前区域内",
            "查找当前范围内",
            "查找",
            "搜索",
            "帮我找",
            "帮我搜索",
            "一下",
            "附近的",
            "当前区域内",
            "当前范围内",
            "当前视域内",
            "区域内",
        ]
        for token in replacements:
            cleaned = cleaned.replace(token, "")
        return cleaned.strip("：:，,。. ")

    def _resolve_search_result(self, message: str, project: ProjectRecord) -> Optional[Dict[str, Any]]:
        lowered = (message or "").lower()
        layer = next((item for item in project.layers if item.layer_id == "poi_search_results"), None)
        if layer is None:
            return None
        for feature in layer.data.get("features", []):
            properties = feature.get("properties", {})
            name = str(properties.get("name") or "")
            if name and name.lower() in lowered:
                coordinates = feature.get("geometry", {}).get("coordinates", [])
                if len(coordinates) >= 2:
                    return {"name": name, "coordinates": [float(coordinates[0]), float(coordinates[1])]}
        return None


class RuleBasedPlanner(AssistantService):
    pass
