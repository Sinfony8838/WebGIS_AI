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
    {"name": "toggle_teaching_map", "description": "叠加或隐藏教学地图（课本插图）。", "parameters": {"map_id": "string", "visible": "boolean?"}},
    {"name": "open_material", "description": "打开课堂素材或外部教学资料。", "parameters": {"material_id": "string?", "material": "object?"}},
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


VOICE_VIEW_KEYWORDS = (
    "转向", "转到", "定位到", "定位", "聚焦", "飞到",
    "看看", "看下", "看一下",
    "目光转向", "目光转到",
    "视角转向", "视角转到", "视角头向",  # 常见语音误识别
    "头向",  # "转向"误识别
    "视角",  # 单独触发视角意图
    "跳到", "移到", "移向", "切到",
    "去看", "去到",
    "放大到", "拉到",
)
VOICE_QUESTION_KEYWORDS = ("为什么", "为何", "怎么", "怎样", "解释", "分析", "讲解", "读图", "说明")
VOICE_TEMPLATE_KEYWORDS = ("来看", "显示", "打开", "叠加", "切到", "切换到")
VOICE_FILLER_TOKENS = (
    "我们把目光",
    "我们把视角",
    "把目光",
    "把视角",
    "视角头向",
    "视角转向",
    "视角转到",
    "目光转向",
    "目光转到",
    "目光",
    "视角",
    "转向",
    "转到",
    "头向",
    "定位到",
    "定位",
    "聚焦到",
    "聚焦",
    "飞到",
    "跳到",
    "移到",
    "移向",
    "切到",
    "去看",
    "去到",
    "看一下",
    "看下",
    "看看",
    "放大到",
    "拉到",
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

BUILTIN_REGION_ANCHORS: Tuple[Dict[str, Any], ...] = (
    {"name": "长三角", "aliases": ["长江三角洲", "长三角地区", "江浙沪"], "center": [120.5, 31.0], "zoom": 7, "extent": [118.0, 29.0, 123.0, 33.0]},
    {"name": "珠三角", "aliases": ["珠江三角洲", "珠三角地区", "粤港澳大湾区", "大湾区"], "center": [113.5, 22.8], "zoom": 8, "extent": [112.0, 21.5, 115.5, 24.0]},
    {"name": "京津冀", "aliases": ["京津冀地区", "首都圈"], "center": [116.5, 39.5], "zoom": 7, "extent": [114.0, 37.5, 119.5, 42.0]},
    {"name": "东北地区", "aliases": ["东北", "东三省"], "center": [126.0, 45.0], "zoom": 5, "extent": [118.0, 38.0, 135.0, 54.0]},
    {"name": "西北地区", "aliases": ["西北", "大西北"], "center": [95.0, 40.0], "zoom": 5, "extent": [73.0, 32.0, 112.0, 50.0]},
    {"name": "西南地区", "aliases": ["西南"], "center": [102.0, 27.0], "zoom": 5, "extent": [92.0, 21.0, 112.0, 34.0]},
    {"name": "华东地区", "aliases": ["华东"], "center": [119.0, 30.0], "zoom": 6, "extent": [115.0, 25.0, 123.0, 35.0]},
    {"name": "华南地区", "aliases": ["华南"], "center": [110.0, 23.0], "zoom": 6, "extent": [104.0, 18.0, 118.0, 27.0]},
    {"name": "华北地区", "aliases": ["华北"], "center": [115.0, 39.0], "zoom": 6, "extent": [110.0, 35.0, 120.0, 43.0]},
    {"name": "华中地区", "aliases": ["华中"], "center": [113.0, 30.0], "zoom": 6, "extent": [108.0, 26.0, 118.0, 34.0]},
    {"name": "中原地区", "aliases": ["中原"], "center": [113.5, 34.5], "zoom": 7, "extent": [110.0, 32.0, 117.0, 37.0]},
    {"name": "四川盆地", "aliases": ["四川", "川渝"], "center": [105.0, 30.5], "zoom": 7, "extent": [101.0, 27.0, 109.0, 34.0]},
    {"name": "青藏高原", "aliases": ["青藏", "西藏高原"], "center": [90.0, 33.0], "zoom": 5, "extent": [73.0, 26.0, 104.0, 40.0]},
    {"name": "黄土高原", "aliases": ["黄土"], "center": [108.0, 37.0], "zoom": 6, "extent": [103.0, 34.0, 114.0, 41.0]},
    {"name": "云贵高原", "aliases": ["云贵"], "center": [104.0, 26.0], "zoom": 6, "extent": [98.0, 22.0, 110.0, 30.0]},
    {"name": "内蒙古高原", "aliases": ["内蒙古", "内蒙"], "center": [112.0, 43.0], "zoom": 5, "extent": [97.0, 37.0, 127.0, 50.0]},
    {"name": "塔里木盆地", "aliases": ["塔里木"], "center": [83.0, 39.0], "zoom": 6, "extent": [73.0, 35.0, 93.0, 43.0]},
    {"name": "准噶尔盆地", "aliases": ["准噶尔"], "center": [86.0, 45.0], "zoom": 7, "extent": [80.0, 43.0, 92.0, 48.0]},
    {"name": "东南沿海", "aliases": ["东南沿海地区", "沿海"], "center": [119.0, 26.0], "zoom": 6, "extent": [115.0, 21.0, 123.0, 32.0]},
    {"name": "台湾海峡", "aliases": ["台海"], "center": [119.5, 24.5], "zoom": 7, "extent": [117.0, 22.0, 122.0, 27.0]},
    {"name": "南海", "aliases": ["南海地区", "南中国海"], "center": [114.0, 15.0], "zoom": 5, "extent": [105.0, 3.0, 122.0, 23.0]},
    {"name": "渤海湾", "aliases": ["渤海"], "center": [119.5, 39.0], "zoom": 7, "extent": [117.0, 37.0, 122.0, 41.0]},
    {"name": "新疆", "aliases": ["新疆地区"], "center": [86.0, 41.0], "zoom": 5, "extent": [73.0, 35.0, 97.0, 50.0]},
    {"name": "黑龙江", "aliases": ["黑龙江省"], "center": [127.0, 47.0], "zoom": 6, "extent": [121.0, 43.0, 135.0, 54.0]},
    {"name": "海南", "aliases": ["海南岛", "海南省"], "center": [109.8, 19.2], "zoom": 8, "extent": [108.5, 18.0, 111.5, 20.5]},
    {"name": "山东半岛", "aliases": ["山东"], "center": [119.0, 36.5], "zoom": 7, "extent": [115.0, 34.0, 123.0, 39.0]},
    {"name": "辽东半岛", "aliases": ["辽东"], "center": [122.0, 39.5], "zoom": 8, "extent": [120.0, 38.5, 124.0, 41.0]},
    {"name": "长江中下游", "aliases": ["长江中下游平原", "长江流域"], "center": [115.0, 30.0], "zoom": 6, "extent": [108.0, 27.0, 122.0, 34.0]},
    {"name": "黄河流域", "aliases": ["黄河"], "center": [108.0, 37.0], "zoom": 5, "extent": [96.0, 32.0, 119.0, 42.0]},
    {"name": "东亚", "aliases": ["东亚地区"], "center": [115.0, 35.0], "zoom": 4, "extent": [100.0, 20.0, 145.0, 50.0]},
    {"name": "东南亚", "aliases": ["东南亚地区"], "center": [110.0, 5.0], "zoom": 4, "extent": [92.0, -10.0, 140.0, 25.0]},
    {"name": "中亚", "aliases": ["中亚地区"], "center": [65.0, 42.0], "zoom": 4, "extent": [50.0, 35.0, 80.0, 50.0]},
    {"name": "南亚", "aliases": ["南亚地区", "印度次大陆"], "center": [80.0, 22.0], "zoom": 4, "extent": [60.0, 5.0, 98.0, 38.0]},
    {"name": "欧洲", "aliases": ["欧洲地区"], "center": [10.0, 50.0], "zoom": 4, "extent": [-12.0, 35.0, 40.0, 72.0]},
    {"name": "非洲", "aliases": ["非洲大陆"], "center": [20.0, 2.0], "zoom": 3, "extent": [-18.0, -35.0, 52.0, 38.0]},
    {"name": "北美洲", "aliases": ["北美"], "center": [-100.0, 45.0], "zoom": 3, "extent": [-170.0, 15.0, -50.0, 72.0]},
    {"name": "南美洲", "aliases": ["南美"], "center": [-60.0, -15.0], "zoom": 3, "extent": [-82.0, -56.0, -34.0, 12.0]},
    {"name": "大洋洲", "aliases": ["澳大利亚"], "center": [135.0, -25.0], "zoom": 4, "extent": [110.0, -47.0, 180.0, -5.0]},
)

Coordinate = Tuple[float, float]
Extent = Tuple[float, float, float, float]


TEACHING_MAP_SHOW_KEYWORDS = ("叠加", "加载", "覆盖")
TEACHING_MAP_HIDE_KEYWORDS = ("取消叠加", "移除", "关掉")
TEACHING_MAP_TRIGGER_KEYWORDS = (
    "教学地图", "课本地图", "课本插图", "教材图",
    "人口分布图", "人口密度分布图", "人口密度图", "人口图", "气温图", "降水图", "降水量图", "地形图",
    "温度带", "土壤图", "绿洲",
    "胡焕庸线图",
    "东北地区", "塔里木",
)

TEACHING_MAP_COMMAND_ALIASES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("shanghai_population_density", ("上海人口密度分布图", "上海人口密度图", "上海人口分布图")),
    ("china_population_hu_line", ("中国人口密度分布图", "中国人口分布图", "人口密度分布图", "人口密度图", "胡焕庸线图")),
    ("china_precipitation", ("中国年平均降水量图", "中国年降水量图", "年平均降水量图", "年降水量分布图", "降水量图")),
    ("china_jan_temperature", ("中国1月平均气温图", "中国一月平均气温图", "1月平均气温图", "一月平均气温图", "冬季气温图")),
    ("china_topography", ("中国地形图", "中国地形分布图", "地形图")),
)

HU_HUANYONG_VIDEO_MATERIAL = {
    "id": "hu_huanyong_bilibili_video",
    "title": "胡焕庸线科普视频：一条线将中国划分为两个财富世界",
    "type": "video",
    "source": "bilibili",
    "url": "https://www.bilibili.com/video/BV13p4y1X7Lu/?share_source=copy_web",
    "thumbnail_url": "",
    "description": "用于课堂引入胡焕庸线与中国人口、财富空间差异的科普视频。",
    "region_binding": {"name": "china"},
    "sort_order": 10,
    "created_at": "2026-05-05T00:00:00+08:00",
}


class AssistantService:
    def __init__(self, config: AppConfig):
        self.config = config
        self.teaching_map_service: Any = None
        self.minimax_client: Any = None  # wired by runtime for LLM fallback
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
        is_material_video_request = "视频" in lowered
        target_layer = None if is_material_video_request else self._resolve_target_layer(message, project)
        active_layer = next((layer for layer in project.layers if layer.layer_id == project.active_layer_id), None)
        search_result = self._resolve_search_result(message, project)

        template_action = None if "视频" in lowered else self._resolve_template_action(lowered)
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

        material_action = self._resolve_material_action(message, lowered)
        if material_action:
            actions.append(material_action["action"])
            narrative_parts.append(material_action["narrative"])

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

        if any(keyword in lowered for keyword in ["讲解", "解释", "分析", "读图", "说明", "汇总", "总结", "答案"]):
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

        for tm_action in self._resolve_teaching_map_actions(message, lowered):
            actions.append(tm_action["action"])
            narrative_parts.append(tm_action["narrative"])

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

        template_action = None if "视频" in lowered else self._resolve_voice_template_action(lowered)
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

        if not template_action or any(token in normalized_message for token in ("中国", "上海", "课本", "教材")):
            for voice_tm in self._resolve_teaching_map_actions(normalized_message, lowered):
                actions.append(voice_tm["action"])
                narrative_parts.append(voice_tm["narrative"])

        voice_material = self._resolve_material_action(normalized_message, lowered)
        if voice_material:
            actions.append(voice_material["action"])
            narrative_parts.append(voice_material["narrative"])

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

    def _resolve_teaching_map_action(self, message: str, lowered: str) -> Optional[Dict[str, Any]]:
        actions = self._resolve_teaching_map_actions(message, lowered)
        return actions[0] if actions else None

    def _resolve_teaching_map_actions(self, message: str, lowered: str) -> List[Dict[str, Any]]:
        if self.teaching_map_service is None:
            return []
        if "视频" in lowered:
            return []
        is_hide = any(kw in lowered for kw in TEACHING_MAP_HIDE_KEYWORDS)
        visible = not is_hide
        verb = "叠加" if visible else "隐藏"
        resolved: List[Dict[str, Any]] = []
        seen: set[str] = set()

        def append_map(map_id: str) -> None:
            if map_id in seen:
                return
            get_map = getattr(self.teaching_map_service, "get_map", None)
            match = get_map(map_id) if callable(get_map) else None
            if not match:
                return
            seen.add(map_id)
            resolved.append(
                {
                    "action": {"tool_name": "toggle_teaching_map", "tool_params": {"map_id": map_id, "visible": visible}},
                    "narrative": f'{verb}教学地图"{match["name"]}"。',
                }
            )

        compact_message = "".join((message or "").split()).lower()
        for map_id, aliases in TEACHING_MAP_COMMAND_ALIASES:
            if any(alias.lower() in compact_message for alias in aliases):
                append_map(map_id)

        has_trigger = any(kw in lowered for kw in TEACHING_MAP_TRIGGER_KEYWORDS)
        if resolved or not has_trigger:
            return resolved
        match = self.teaching_map_service.find_by_keyword(message)
        if match is None:
            return resolved
        if match.get("id") in seen:
            return resolved
        resolved.append({
            "action": {"tool_name": "toggle_teaching_map", "tool_params": {"map_id": match["id"], "visible": visible}},
            "narrative": f'{verb}教学地图"{match["name"]}"。',
        })
        return resolved

    def _resolve_material_action(self, message: str, lowered: str) -> Optional[Dict[str, Any]]:
        if "视频" not in lowered and "bilibili" not in lowered.lower():
            return None
        if not any(token in message for token in ("胡焕庸", "一条线", "人口分布")):
            return None
        return {
            "action": {
                "tool_name": "open_material",
                "tool_params": {
                    "material_id": HU_HUANYONG_VIDEO_MATERIAL["id"],
                    "material": HU_HUANYONG_VIDEO_MATERIAL,
                },
            },
            "narrative": "打开胡焕庸线科普视频。",
        }

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
        # --- Region anchors (matched first, higher priority) ---
        focus_points: List[Dict[str, Any]] = []
        for region in BUILTIN_REGION_ANCHORS:
            entry: Dict[str, Any] = {
                "name": region["name"],
                "center": tuple(region["center"]),
                "zoom": region["zoom"],
            }
            if region.get("extent"):
                entry["extent"] = tuple(region["extent"])
            if region.get("aliases"):
                entry["aliases"] = list(region["aliases"])
            focus_points.append(entry)

        # --- City-level points from GeoJSON file ---
        path = self.config.builtin_dir / "classroom" / "classroom_focus_points.geojson"
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                for feature in payload.get("features", []):
                    properties = feature.get("properties", {})
                    geometry = feature.get("geometry", {})
                    coordinates = geometry.get("coordinates", [])
                    if not isinstance(properties.get("name"), str) or len(coordinates) < 2:
                        continue
                    focus_points.append(
                        {
                            "name": properties["name"].strip(),
                            "center": (float(coordinates[0]), float(coordinates[1])),
                            "zoom": int(properties.get("zoom", 8)),
                        }
                    )
            except (OSError, json.JSONDecodeError):
                pass
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

        # --- Pass 1: hardcoded region + city anchors (instant, offline) ---
        for focus_point in self.focus_points:
            name = str(focus_point["name"])
            matched = name and (name in normalized_place or name in normalized_message)
            if not matched:
                for alias in focus_point.get("aliases", []):
                    if alias in normalized_place or alias in normalized_message:
                        matched = True
                        break
            if matched:
                result: Dict[str, Any] = {
                    "name": name,
                    "center": focus_point["center"],
                    "zoom": focus_point["zoom"],
                }
                if focus_point.get("extent"):
                    result["extent"] = focus_point["extent"]
                return result

        # --- Pass 2: named features in visible project layers ---
        for candidate in self._iter_named_feature_candidates(project):
            name = str(candidate["name"])
            if not name:
                continue
            if name not in normalized_place and name not in normalized_message:
                continue
            return candidate

        # --- Pass 3: LLM geocoding fallback (any place the LLM knows) ---
        return self._llm_geocode(message)

    def _llm_geocode(self, message: str) -> Optional[Dict[str, Any]]:
        """Ask the LLM to extract a place name and return approximate coordinates."""
        if self.minimax_client is None or not self.config.minimax_enabled():
            return None
        try:
            prompt = (
                "从以下用户语音指令中提取地理位置名称，并返回该地点的经纬度坐标和适合的地图缩放级别。\n"
                "仅返回纯JSON，不要输出任何其他文字、不要用```包裹、不要输出<think>标签：\n"
                '{"name": "地名", "center": [经度, 纬度], "zoom": 缩放级别}\n\n'
                "缩放级别参考：街道=12-14, 城市=8-10, 省份/地形区=6-7, 国家=4-5, 大洲=3\n"
                '如果无法识别任何地理位置，返回 {"name": null}\n'
            )
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": message},
            ]
            raw = self.minimax_client.chat_completion(messages, temperature=0.1)
            cleaned = self._clean_llm_json(raw)
            parsed = json.loads(cleaned)
            name = parsed.get("name")
            center = parsed.get("center")
            if not name or not isinstance(center, list) or len(center) < 2:
                return None
            result: Dict[str, Any] = {
                "name": str(name),
                "center": [float(center[0]), float(center[1])],
                "zoom": int(parsed.get("zoom") or 8),
            }
            extent = parsed.get("extent")
            if isinstance(extent, list) and len(extent) >= 4:
                result["extent"] = [float(v) for v in extent[:4]]
            return result
        except Exception:
            return None

    @staticmethod
    def _clean_llm_json(raw: str) -> str:
        """Strip think tags, code fences, and other wrappers from LLM output."""
        import re as _re
        text = _re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=_re.IGNORECASE).strip()
        if text.startswith("```"):
            text = _re.sub(r"^```(?:json)?", "", text, flags=_re.IGNORECASE).strip()
            text = _re.sub(r"```\s*$", "", text).strip()
        return text

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
    visible_layer_names = [layer.name for layer in visible_layers]
    has_population_map = any("人口" in name for name in visible_layer_names)
    has_precipitation_map = any("降水" in name for name in visible_layer_names)
    has_temperature_map = any("1月" in name and "气温" in name for name in visible_layer_names)
    has_topography_map = any("地形" in name for name in visible_layer_names)
    if has_population_map and (has_precipitation_map or has_temperature_map or has_topography_map):
        lines.append("- 综合人口、降水、1月气温和地形图层，中国人口分布总体呈现东南密集、西北稀疏，核心解释是自然承载条件与社会经济机会共同叠加。")
        lines.append("- 东部季风区降水较多、热量条件较好、平原和丘陵开发条件相对优越，农业基础、交通网络和城市产业进一步强化人口集聚。")
        lines.append("- 西北内陆和青藏高原受干旱、高寒、地形起伏与交通可达性限制，人口密度普遍较低，绿洲、河谷和资源型城镇形成局部集聚。")
        explained = True
    elif has_population_map:
        lines.append("- 中国人口分布特点可概括为东南多、西北少，沿海、平原、河流下游和城市群附近更密集。")
        explained = True
    if has_precipitation_map and not has_population_map:
        lines.append("- 年降水量图适合解释东南向西北递减的水分条件差异，并联系农业与人口承载力。")
        explained = True
    if has_temperature_map and not has_population_map:
        lines.append("- 1月平均气温图适合识别冬季南北温差，并联系纬度位置、冬季风和地形屏障。")
        explained = True
    if has_topography_map and not has_population_map:
        lines.append("- 地形图适合解释平原、盆地、河谷更利于聚落和交通布局，高原山地人口承载条件相对受限。")
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
