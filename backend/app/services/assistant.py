from __future__ import annotations

import json
import math
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..config import AppConfig, WEATHER_BASEMAP_ID
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


BASEMAP_KEYWORDS = {
    "amap_vector": ("\u6807\u51c6", "\u666e\u901a"),
    "amap_light": ("\u6d45\u7070", "\u6d45\u8272", "\u7070\u8272"),
    "amap_imagery": ("\u5f71\u50cf", "\u536b\u661f", "\u9065\u611f"),
    "weather_clouds": ("\u4e91\u56fe", "\u4e91\u91cf", "\u4e91\u5c42"),
    "weather_temperature": ("\u6e29\u5ea6", "\u6c14\u6e29"),
    "weather_wind": ("\u98ce\u901f", "\u98ce\u573a", "\u5927\u98ce"),
    "weather_pressure": ("\u6c14\u538b", "\u6d77\u5e73\u9762\u6c14\u538b"),
    WEATHER_BASEMAP_ID: (
        "\u5929\u6c14",
        "\u5929\u6c14\u56fe",
        "\u5929\u6c14\u5730\u56fe",
        "\u6c14\u8c61",
        "\u964d\u6c34",
        "\u964d\u96e8",
        "\u96e8\u56fe",
    ),
}


TEMPLATE_KEYWORDS = [
    ("generic_classroom_pack", ["通用课堂", "区域框架", "欧亚", "generic"], "我先加载通用地理课堂包。"),
]


VOICE_VIEW_KEYWORDS = ("转向", "转到", "定位到", "定位", "聚焦", "飞到", "看看", "看下", "看一下", "目光转向")
VOICE_QUESTION_KEYWORDS = ("为什么", "为何", "怎么", "怎样", "解释", "分析", "讲解", "读图", "说明")
VOICE_TEMPLATE_KEYWORDS = ("来看", "显示", "叠加", "切到", "切换到")
VOICE_FILLER_TOKENS = (
    "我们把目光",
    "把目光",
    "目光",
    "转向",
    "转到",
    "定位到",
    "定位",
    "聚焦到",
    "聚焦",
    "飞到",
    "看一下",
    "看下",
    "看看",
    "我们",
    "一下",
    "区域",
    "地区",
    "视图",
    "周边",
    "附近",
    "那里",
    "那边",
)
VOICE_SHOW_KEYWORDS = ("显示", "打开", "叠加")
VOICE_HIDE_KEYWORDS = ("隐藏", "关闭")

Coordinate = Tuple[float, float]
Extent = Tuple[float, float, float, float]


class AssistantService:
    def __init__(self, config: AppConfig):
        self.config = config
        self.focus_points = self._load_focus_points()

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

    def plan_voice_actions(
        self,
        message: str,
        project: ProjectRecord,
        map_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        map_context = map_context or {}
        normalized_message = self._normalize_voice_text(message)
        lowered = normalized_message.lower()
        actions: List[Dict[str, Any]] = []
        narrative_parts: List[str] = []

        template_action = self._resolve_voice_template_action(lowered)
        if template_action:
            actions.append({"tool_name": template_action["tool_name"], "tool_params": dict(template_action["tool_params"])})
            narrative_parts.append(template_action["narrative"])

        basemap_id = self._extract_basemap_id(normalized_message)
        if basemap_id:
            actions.append({"tool_name": "switch_basemap", "tool_params": {"basemap_id": basemap_id}})
            narrative_parts.append("已按语音指令切换课堂底图。")

        target_layer = self._resolve_target_layer(normalized_message, project, include_active_fallback=False)
        if not template_action and target_layer:
            if any(keyword in lowered for keyword in VOICE_HIDE_KEYWORDS):
                actions.append({"tool_name": "toggle_layer", "tool_params": {"layer_id": target_layer["layer_id"], "visible": False}})
                narrative_parts.append(f"已按语音指令隐藏图层“{target_layer['name']}”。")
            elif any(keyword in lowered for keyword in VOICE_SHOW_KEYWORDS):
                actions.append({"tool_name": "toggle_layer", "tool_params": {"layer_id": target_layer["layer_id"], "visible": True}})
                narrative_parts.append(f"已按语音指令显示图层“{target_layer['name']}”。")

        place_target = self._resolve_voice_place(normalized_message, project)
        if place_target and self._is_voice_view_command(lowered):
            tool_params: Dict[str, Any] = {
                "center": list(place_target["center"]),
                "zoom": int(place_target["zoom"]),
            }
            if place_target.get("extent"):
                tool_params["extent"] = list(place_target["extent"])
            actions.append({"tool_name": "set_view", "tool_params": tool_params})
            narrative_parts.append(f"已按语音指令聚焦到“{place_target['name']}”。")

        if self._is_voice_question(normalized_message):
            actions.append({"tool_name": "explain_current_view", "tool_params": {"focus": message.strip()}})
            narrative_parts.append("我会结合当前画面给出文字讲解。")

        if actions:
            return {"assistant_message": " ".join(part for part in narrative_parts if part).strip(), "actions": actions}

        return {
            "assistant_message": "我暂时没听清具体操作，请换一种说法，例如“转到上海”或“来看人口分布图”。",
            "actions": [],
        }

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
                row += f"（{', '.join(key_values)}）"
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
        return f"当前视域的近似尺度为：东西约 {approximate_width_km:.0f} 千米，南北约 {approximate_height_km:.0f} 千米。"

    def build_export_hint(self) -> str:
        return "当前任务包含导出意图。请点击顶部“导出截图”，系统会把当前课堂画面保存为本地成果。"

    def build_poi_hint(self, keyword: str, count: int) -> str:
        if count <= 0:
            return f"当前范围内没有检索到“{keyword}”相关结果。"
        return f"当前范围内已找到 {count} 条“{keyword}”相关结果，结果已经同步到左侧检索面板和地图点位。"

    def _resolve_target_layer(
        self,
        message: str,
        project: ProjectRecord,
        include_active_fallback: bool = True,
    ) -> Optional[Dict[str, Any]]:
        lowered = (message or "").lower()
        for layer in project.layers:
            if layer.name.lower() in lowered:
                return layer.to_dict()
        if include_active_fallback and project.active_layer_id:
            for layer in project.layers:
                if layer.layer_id == project.active_layer_id:
                    return layer.to_dict()
        return None

    def _resolve_template_action(self, lowered: str) -> Optional[Dict[str, Any]]:
        template_keywords = [
            ("population_classroom_pack", ["\u4eba\u53e3\u4e13\u9898", "\u4eba\u53e3\u5305", "population pack"], "\u6211\u5148\u5207\u5230\u4eba\u53e3\u4e13\u9898\u8bfe\u5802\u5305\u3002"),
            ("population_distribution", ["\u4eba\u53e3\u5206\u5e03", "\u5206\u5e03\u56fe"], "\u6211\u5148\u5207\u5230\u4eba\u53e3\u5206\u5e03\u6a21\u677f\u3002"),
            ("population_density", ["\u4eba\u53e3\u5bc6\u5ea6", "\u5bc6\u5ea6\u56fe", "\u70ed\u529b"], "\u6211\u5148\u5207\u5230\u4eba\u53e3\u5bc6\u5ea6\u6a21\u677f\u3002"),
            ("population_migration", ["\u4eba\u53e3\u8fc1\u79fb", "\u8fc1\u79fb\u56fe", "\u8fc1\u79fb"], "\u6211\u5148\u5207\u5230\u4eba\u53e3\u8fc1\u79fb\u6a21\u677f\u3002"),
            ("hu_line_comparison", ["\u80e1\u7115\u5eb8", "hu line"], "\u6211\u5148\u53e0\u52a0\u80e1\u7115\u5eb8\u7ebf\u5bf9\u6bd4\u6a21\u677f\u3002"),
            *TEMPLATE_KEYWORDS,
        ]
        for template_id, keywords, narrative in template_keywords:
            if any(keyword in lowered for keyword in keywords):
                return {"tool_name": "apply_template", "tool_params": {"template_id": template_id}, "narrative": narrative}
        return None

    def _resolve_voice_template_action(self, lowered: str) -> Optional[Dict[str, Any]]:
        if not any(keyword in lowered for keyword in VOICE_TEMPLATE_KEYWORDS):
            return None
        return self._resolve_template_action(lowered)

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
        available_ids = {item["id"] for item in self.config.basemap_catalog()["items"]}
        for basemap_id, keywords in BASEMAP_KEYWORDS.items():
            if basemap_id not in available_ids:
                continue
            if any(keyword in lowered for keyword in keywords):
                return basemap_id
        return ""

    def _resolve_poi_action(self, message: str, lowered: str, map_context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not any(keyword in lowered for keyword in ["搜索", "查找", "poi", "附近", "找一个", "查一个"]):
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
            "一个",
            "附近的",
            "当前区域内",
            "当前范围内",
            "当前视域内",
            "区域内",
        ]
        for token in replacements:
            cleaned = cleaned.replace(token, "")
        return cleaned.strip("（）()。 ")

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

    def _load_focus_points(self) -> List[Dict[str, Any]]:
        path = self.config.builtin_dir / "classroom" / "classroom_focus_points.geojson"
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

        features = payload.get("features", [])
        focus_points = []
        for feature in features:
            properties = feature.get("properties", {})
            geometry = feature.get("geometry", {})
            coordinates = geometry.get("coordinates", [])
            if not isinstance(properties.get("name"), str) or len(coordinates) < 2:
                continue
            focus_points.append(
                {
                    "name": properties["name"].strip(),
                    "center": (float(coordinates[0]), float(coordinates[1])),
                    "zoom": 8,
                }
            )
        return focus_points

    def _normalize_voice_text(self, message: str) -> str:
        normalized = (message or "").strip()
        for source, target in (
            ("，", " "),
            ("。", " "),
            ("！", " "),
            ("？", " "),
            ("、", " "),
            ("\n", " "),
            ("\t", " "),
        ):
            normalized = normalized.replace(source, target)
        return " ".join(part for part in normalized.split() if part)

    def _normalize_voice_place_text(self, message: str) -> str:
        normalized = self._normalize_voice_text(message)
        for token in sorted(VOICE_FILLER_TOKENS, key=len, reverse=True):
            normalized = normalized.replace(token, "")
        return "".join(normalized.split()).strip()

    def _is_voice_view_command(self, lowered: str) -> bool:
        return any(keyword in lowered for keyword in VOICE_VIEW_KEYWORDS)

    def _is_voice_question(self, message: str) -> bool:
        lowered = (message or "").lower()
        if any(keyword in lowered for keyword in VOICE_QUESTION_KEYWORDS):
            return True
        return lowered.endswith("?") or lowered.endswith("？")

    def _resolve_voice_place(self, message: str, project: ProjectRecord) -> Optional[Dict[str, Any]]:
        normalized_message = self._normalize_voice_text(message)
        normalized_place = self._normalize_voice_place_text(message)

        for focus_point in self.focus_points:
            name = str(focus_point["name"])
            if name and (name in normalized_place or name in normalized_message):
                return {
                    "name": name,
                    "center": focus_point["center"],
                    "zoom": focus_point["zoom"],
                }

        for candidate in self._iter_named_feature_candidates(project):
            name = str(candidate["name"])
            if not name:
                continue
            if name not in normalized_place and name not in normalized_message:
                continue
            return candidate
        return None

    def _iter_named_feature_candidates(self, project: ProjectRecord) -> Iterable[Dict[str, Any]]:
        for layer in project.layers:
            if not layer.visible:
                continue
            features = layer.data.get("features", [])
            for feature in features:
                properties = feature.get("properties", {})
                name = str(properties.get("name") or "").strip()
                if not name:
                    continue
                geometry = feature.get("geometry", {})
                geometry_type = str(geometry.get("type") or layer.geometry_type or "")
                extent = self._geometry_extent(geometry)
                if extent is None:
                    continue
                center = self._extent_center(extent)
                if geometry_type.endswith("Point") or geometry_type == "Point":
                    zoom = 10 if layer.layer_id == "poi_search_results" else 8
                    yield {"name": name, "center": center, "zoom": zoom}
                    continue
                yield {
                    "name": name,
                    "center": center,
                    "zoom": self._zoom_for_extent(extent),
                    "extent": extent,
                }

    def _geometry_extent(self, geometry: Dict[str, Any]) -> Optional[Extent]:
        coordinates = list(self._iter_coordinates(geometry.get("coordinates")))
        if not coordinates:
            return None
        xs = [point[0] for point in coordinates]
        ys = [point[1] for point in coordinates]
        return (min(xs), min(ys), max(xs), max(ys))

    def _iter_coordinates(self, value: Any) -> Iterable[Coordinate]:
        if isinstance(value, (list, tuple)):
            if len(value) >= 2 and all(isinstance(item, (int, float)) for item in value[:2]):
                yield (float(value[0]), float(value[1]))
                return
            for item in value:
                yield from self._iter_coordinates(item)

    def _extent_center(self, extent: Extent) -> Coordinate:
        west, south, east, north = extent
        return ((west + east) / 2.0, (south + north) / 2.0)

    def _zoom_for_extent(self, extent: Extent) -> int:
        west, south, east, north = extent
        span = max(abs(east - west), abs(north - south))
        if span <= 0.8:
            return 10
        if span <= 2.0:
            return 8
        if span <= 5.0:
            return 7
        if span <= 10.0:
            return 6
        return 5


def _compose_contextual_explanation(
    self: AssistantService,
    project: ProjectRecord,
    map_context: Optional[Dict[str, Any]] = None,
    focus: str = "",
) -> str:
    map_context = map_context or {}
    visible_layers = [layer for layer in project.layers if layer.visible]
    layer_names = "、".join(layer.name for layer in visible_layers[:5]) or "当前底图"
    center = map_context.get("center") or project.view.get("center") or []
    zoom = map_context.get("zoom") or project.view.get("zoom") or ""
    extent = map_context.get("extent") or project.view.get("extent") or []
    basemap_id = map_context.get("basemap_id") or project.base_map.get("id") or ""

    center_text = ""
    if isinstance(center, list) and len(center) >= 2:
        lon = float(center[0])
        lat = float(center[1])
        center_text = f"中心约为经度 {lon:.3f}、纬度 {lat:.3f}"
        if 120.7 <= lon <= 122.2 and 30.6 <= lat <= 31.9:
            center_text += "，当前视域落在上海及周边"

    lines = [
        "画面事实：",
        f"- 当前底图为 {basemap_id or '默认底图'}，可见图层包括 {layer_names}。",
        f"- 当前缩放级别约为 {zoom}。{center_text}",
    ]
    if isinstance(extent, list) and len(extent) == 4:
        lines.append(f"- 当前视域范围约为 {float(extent[0]):.2f}, {float(extent[1]):.2f}, {float(extent[2]):.2f}, {float(extent[3]):.2f}。")

    lines.extend(["", "空间关系："])
    if visible_layers:
        lines.append("- 先看底图中的城市、道路、水系和海岸线，再看叠加图层与这些地理要素的对应关系。")
    else:
        lines.append("- 当前没有额外业务图层，读图应主要依赖底图中的城市、道路、水系、地形或海岸线信息。")

    lines.extend(["", "地理解释："])
    explained = False
    enabled = set(project.enabled_templates)
    if "population_distribution" in enabled or any("人口" in layer.name for layer in visible_layers):
        lines.append("- 人口主题读图应关注人口是否沿城市群、交通走廊和平原地区集聚。")
        explained = True
    if "population_migration" in enabled:
        lines.append("- 迁移读图要把流向与就业机会、产业基础和交通可达性联系起来。")
        explained = True
    if "hu_line_comparison" in enabled:
        lines.append("- 胡焕庸线可作为人口地理差异的参照线，但解释时还要落到自然环境和社会经济条件。")
        explained = True
    if any("Koppen" in layer.name or "柯本" in layer.name or "World_Koppen" in layer.name for layer in visible_layers):
        lines.append("- 当前叠加了柯本气候分区影像层，适合从纬度、海陆位置、洋流和地形解释气候带分异。")
        explained = True
    poi_layer = next((layer for layer in visible_layers if layer.layer_id == "poi_search_results"), None)
    if poi_layer:
        keyword = poi_layer.metadata.get("keyword") or "课堂检索结果"
        lines.append(f"- 当前叠加了“{keyword}”相关 POI 结果，适合结合区位条件做即时读图分析。")
        explained = True
    if not explained:
        lines.append("- 可从位置、联系、差异和原因四个角度组织讲解。")

    lines.extend(["", "课堂提问：", "- 这个区域的核心地理要素是什么？它们为什么在这里集聚或分散？", "- 如果切换图层或放大一级，哪些结论会更可靠？"])
    if focus:
        lines.extend(["", f"注意事项：本次讲解重点是：{focus.strip()}。"])
    return "\n".join(lines)


AssistantService.compose_explanation = _compose_contextual_explanation
class RuleBasedPlanner(AssistantService):
    pass
