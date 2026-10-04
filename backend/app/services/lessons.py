"""Lesson workspace service: structured lessons, stage map scenes, imports.

A lesson is a sequence of stages; each stage carries a pre-baked map
"scene" (basemap + templates + layer visibility + view + annotations +
optional visual query).  Applying a scene is a purely local, synchronous
operation — no LLM call — so in-class stage switching is instant.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional

from ..config import AppConfig
from ..models import LayerRecord, LessonRecord
from ..store import RuntimeStore
from .minimax_client import MiniMaxClient
from .templates import TemplateService
from .visual_query import VisualQueryService


LESSON_ANNOTATION_LAYER_ID = "lesson_stage_annotations"

# 课堂环节类型：驱动课中面板的 ✍（练习）/？（提问）类型徽标。
# 空字符串表示未标注，由前端按环节内容回落推断。
STAGE_KINDS = frozenset({"presentation", "practice", "question", "summary"})

LESSON_IMPORT_SCHEMA_HINT = {
    "title": "string",
    "subject": "string",
    "grade": "string",
    "objectives": ["string"],
    "stages": [
        {
            "stage_id": "s1",
            "title": "string",
            "minutes": 5,
            "scene": {
                "basemap_id": "amap_light",
                "templates": ["population_distribution"],
                "layer_visibility": {"builtin_population_regions": True},
                "catalog_layers": ["china_climate_types"],
                "catalog_layer_focus": "china_climate_types",
                "view": {"center": [104.0, 35.0], "zoom": 4},
                "annotations": [{"text": "string", "position": [104.0, 35.0]}],
                "visual_query": None,
                "globe": {"enabled": True, "themes": ["string"], "camera": {"lon": 104.0, "lat": 35.0}},
            },
            "script": ["string"],
            "questions": [
                {
                    "question_id": "s1q1",
                    "type": "choice | open",
                    "text": "string",
                    "options": ["string"],
                    "answer_index": 0,
                    "expected_points": ["string"],
                    "misconceptions": [{"tag": "string", "description": "string"}],
                }
            ],
            "assistant_prompts": ["string"],
            "brainstorm": {
                "title": "string",
                "prompt": "string",
                "regions": ["string"],
                "button_label": "string",
            },
        }
    ],
}


def normalize_teaching_maps(raw: Any) -> List[Dict[str, Any]]:
    items, seen = [], set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", str(item.get("id") or "")) or item["id"] in seen:
            continue
        try:
            opacity = min(1., max(0., float(item.get("opacity", .5))))
        except (TypeError, ValueError):
            opacity = .5
        seen.add(item["id"])
        items.append({"id": item["id"], "opacity": opacity})
    return items[:8]


def normalize_lesson_actions(raw: Any) -> List[Dict[str, Any]]:
    from copy import deepcopy
    items, seen = [], set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or item.get("type") not in {"scene", "video", "activity", "statistics", "summary", "workflow"}:
            continue
        aid = str(item.get("action_id") or "")
        if aid in seen or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", aid):
            continue
        seen.add(aid)
        action = {k: deepcopy(item[k]) for k in ("action_id", "label", "type", "note", "prompt", "url", "resource_rows", "source_id") if k in item}
        if item.get("type") == "video" and not str(item.get("url") or "").startswith("https://www.bilibili.com/video/"):
            continue
        if isinstance(item.get("scene"), dict):
            action["scene"] = {**default_scene(), **deepcopy(item["scene"])}
            action["scene"]["teaching_maps"] = normalize_teaching_maps(item["scene"].get("teaching_maps"))
        items.append(action)
    return items[:30]


def default_scene() -> Dict[str, Any]:
    return {
        "basemap_id": "",
        "templates": [],
        "layer_visibility": {},
        "catalog_layers": [],
        "catalog_layer_focus": "",
        "teaching_maps": [],
        "view": {},
        "annotations": [],
        "visual_query": None,
        "globe": {},
    }


def normalize_scene_globe(raw: Any) -> Dict[str, Any]:
    """Normalize a stage's optional 3D scene declaration.

    The backend only persists this intent.  A later frontend change will
    interpret theme ids and camera fields when it applies a lesson scene.
    """
    if not isinstance(raw, dict) or "enabled" not in raw:
        return {}
    enabled = bool(raw.get("enabled"))
    result: Dict[str, Any] = {"enabled": enabled}
    if not enabled:
        return result
    result["themes"] = [str(item) for item in raw.get("themes") or []]
    camera_raw = raw.get("camera") if isinstance(raw.get("camera"), dict) else {}
    camera: Dict[str, float] = {}
    for key in ("lon", "lat", "altitudeMeters", "pitchDeg"):
        value = camera_raw.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            camera[key] = float(value)
    if camera:
        result["camera"] = camera
    return result


def normalize_evidence_refs(raw: Any) -> List[Dict[str, str]]:
    refs: List[Dict[str, str]] = []
    seen = set()
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, str):
            source_id = item.strip()
            payload = {"source_id": source_id}
        elif isinstance(item, dict):
            source_id = str(item.get("source_id") or item.get("id") or "").strip()
            payload = {
                "source_id": source_id,
                "title": str(item.get("title") or ""),
                "source_year": str(item.get("source_year") or ""),
                "fingerprint": str(item.get("fingerprint") or ""),
            }
        else:
            continue
        if not source_id or source_id in seen:
            continue
        seen.add(source_id)
        refs.append(payload)
    return refs


def normalize_teacher_guidance(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    result = {
        key: str(raw.get(key) or "")
        for key in (
            "observation_prompt",
            "oral_question",
            "expected_response",
            "misconception_cue",
            "closing",
            "fallback",
        )
        if str(raw.get(key) or "")
    }
    points = raw.get("evidence_points")
    if isinstance(points, list):
        result["evidence_points"] = [str(item) for item in points if str(item)]
    return result


PRESENTATION_BLOCK_TYPES = frozenset({"text", "image", "video", "question", "chart", "map"})


def _clamp01(value: Any, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return min(1.0, max(0.0, number))


def normalize_presentation(raw: Any) -> Dict[str, Any]:
    """环节展示布局：区块有稳定 ID、素材引用、层级与归一化位置尺寸。

    非法区块整体丢弃；坐标越界收敛到 [0,1]；未知字段不保留。
    """
    if not isinstance(raw, dict):
        return {}
    raw_blocks = raw.get("blocks")
    if not isinstance(raw_blocks, list):
        return {}
    blocks: List[Dict[str, Any]] = []
    for index, item in enumerate(raw_blocks, start=1):
        if not isinstance(item, dict):
            continue
        block_type = str(item.get("type") or "")
        if block_type not in PRESENTATION_BLOCK_TYPES:
            continue
        block_id = str(item.get("id") or "").strip()
        if not block_id:
            continue
        block: Dict[str, Any] = {
            "id": block_id,
            "type": block_type,
            "text": str(item.get("text") or ""),
            "z": max(0, int(item.get("z") or 0)) if str(item.get("z") or "0").lstrip("-").isdigit() else 0,
            "order": max(0, int(item.get("order") or index)),
        }
        x = _clamp01(item.get("x"), 0.0)
        y = _clamp01(item.get("y"), 0.0)
        w = _clamp01(item.get("w"), 0.4)
        h = _clamp01(item.get("h"), 0.2)
        block.update({
            "x": min(x, 1 - max(0.04, w)), "y": min(y, 1 - max(0.04, h)),
            "w": max(0.04, w), "h": max(0.04, h),
        })
        if item.get("teacher_reveal") is True:
            block["teacher_reveal"] = True
        asset = item.get("asset")
        if isinstance(asset, dict) and block_type in {"image", "video", "question", "chart", "map"}:
            normalized_asset: Dict[str, Any] = {}
            url = str(asset.get("url") or "").strip()
            if url:
                normalized_asset["url"] = url
            if asset.get("mime_type"):
                normalized_asset["mime_type"] = str(asset["mime_type"])
            if asset.get("name"):
                normalized_asset["name"] = str(asset["name"])
            if asset.get("question_id"):
                normalized_asset["question_id"] = str(asset["question_id"])
            if asset.get("chart_ref"):
                normalized_asset["chart_ref"] = str(asset["chart_ref"])
            if normalized_asset:
                block["asset"] = normalized_asset
        blocks.append(block)
    if not blocks and raw_blocks:
        return {}
    return {"blocks": blocks}


PROFILE_WINDOW_KINDS = frozenset({"population", "terrain"})


def normalize_profile_preset(raw: Any) -> Dict[str, Any]:
    """课前剖面预设：测线 + 窗口布局。

    窗口坐标保存为视口占比（x/y/w/h ∈ [0,1]），课堂加载时按实际屏幕换算，
    保证不同分辨率下可见且可拖动。没有可用测线时返回空对象。
    """
    if not isinstance(raw, dict):
        return {}
    lines: List[Dict[str, Any]] = []
    line_indices: Dict[int, int] = {}
    for original_index, item in enumerate(raw.get("lines") or []):
        if not isinstance(item, dict):
            continue
        raw_points = item.get("coordinates")
        if not isinstance(raw_points, list):
            continue
        coordinates: List[List[float]] = []
        for point in raw_points:
            if not isinstance(point, (list, tuple)) or len(point) != 2:
                continue
            try:
                lon, lat = float(point[0]), float(point[1])
            except (TypeError, ValueError):
                continue
            if -180 <= lon <= 180 and -90 <= lat <= 90:
                coordinates.append([lon, lat])
        if len(coordinates) < 2:
            continue
        try:
            total_km = float(item.get("total_km") or 0)
        except (TypeError, ValueError):
            total_km = 0
        line_indices[original_index] = len(lines)
        lines.append({
            "id": str(item.get("id") or "")[:48],
            "name": str(item.get("name") or "")[:48],
            "coordinates": coordinates,
            "total_km": round(total_km, 3),
            "color": str(item.get("color") or "#2f6fd6")[:24],
        })
    if not lines:
        return {}
    windows: List[Dict[str, Any]] = []
    for item in raw.get("windows") or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "")
        if kind not in PROFILE_WINDOW_KINDS:
            continue
        try:
            record_index = int(item.get("record_index") or 0)
        except (TypeError, ValueError):
            record_index = 0
        if record_index not in line_indices:
            continue
        record_index = line_indices[record_index]
        try:
            width_fraction = min(max(_clamp01(item.get("w"), 0.3), 0.14), 0.9)
            height_fraction = min(max(_clamp01(item.get("h"), 0.42), 0.2), 0.9)
            windows.append({
                "kind": kind,
                "record_index": record_index,
                "source_id": str(item.get("source_id") or "")[:48],
                "x": min(_clamp01(item.get("x"), 0.04), 1 - width_fraction),
                "y": min(max(_clamp01(item.get("y"), 0.1), 0.0), 1 - height_fraction),
                "w": width_fraction,
                "h": height_fraction,
            })
        except (TypeError, ValueError):
            continue
    return {"lines": lines, "windows": windows}


def normalize_brainstorm(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    prompt = str(raw.get("prompt") or "").strip()
    raw_regions = raw.get("regions")
    regions = list(dict.fromkeys(item.strip() for item in raw_regions if isinstance(item, str) and item.strip())) if isinstance(raw_regions, list) else []
    if not prompt or not regions:
        return {}
    return {
        "title": str(raw.get("title") or "GeoBot 头脑风暴").strip(),
        "prompt": prompt,
        "regions": regions,
        "button_label": str(raw.get("button_label") or "转动并生成探究").strip(),
    }


class LessonService:
    def __init__(
        self,
        config: AppConfig,
        store: RuntimeStore,
        template_service: TemplateService,
        visual_query_service: VisualQueryService,
        minimax_client: Optional[MiniMaxClient] = None,
        catalog_layer_loader: Optional[Callable[[str, str], Any]] = None,
        teaching_map_service: Any = None,
    ):
        self.config = config
        self.store = store
        self.template_service = template_service
        self.visual_query_service = visual_query_service
        self.minimax_client = minimax_client
        self.catalog_layer_loader = catalog_layer_loader
        self.teaching_map_service = teaching_map_service
        self.ensure_builtin_lessons()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def ensure_builtin_lessons(self) -> None:
        lessons_dir = self.config.builtin_dir / "lessons"
        if not lessons_dir.is_dir():
            return
        for path in sorted(lessons_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            lesson_id = str(payload.get("lesson_id") or "")
            if not lesson_id:
                continue
            existing = self.store.get_lesson(lesson_id)
            if existing is not None:
                # 仅当内置教案文件声明了新的 builtin_version 时才覆盖已入库副本，
                # 避免覆盖教师对旧版本做过的课堂内编辑。
                file_version = str((payload.get("metadata") or {}).get("builtin_version") or "")
                stored_version = str((existing.metadata or {}).get("builtin_version") or "")
                if not file_version or file_version == stored_version:
                    continue
            lesson = LessonRecord.create(
                lesson_id=lesson_id,
                title=str(payload.get("title") or path.stem),
                subject=str(payload.get("subject") or "地理"),
                grade=str(payload.get("grade") or ""),
                objectives=[str(item) for item in payload.get("objectives", [])],
                stages=self._normalize_stages(payload.get("stages", [])),
                source="builtin",
                metadata=dict(payload.get("metadata") or {}),
                plan=dict(payload.get("plan") or {}),
            )
            self.store.upsert_lesson(lesson)

    def list_lessons(self, owner_user_id: str = "", include_all: bool = False) -> Dict[str, Any]:
        lessons = self.store.list_lessons()
        if owner_user_id and not include_all:
            lessons = [
                lesson
                for lesson in lessons
                if lesson.source == "builtin" or lesson.owner_user_id == owner_user_id
            ]
        lessons.sort(key=lambda lesson: (lesson.lesson_id != "lesson_builtin_population_teacher_revised", not bool(lesson.metadata.get("recommended"))))
        return {"status": "success", "items": [lesson.to_dict() for lesson in lessons]}

    def get_lesson(self, lesson_id: str) -> LessonRecord:
        lesson = self.store.get_lesson(lesson_id)
        if not lesson:
            raise KeyError(f"Unknown lesson: {lesson_id}")
        return lesson

    def create_lesson(
        self,
        payload: Dict[str, Any],
        source: str = "manual",
        owner_user_id: str = "",
    ) -> LessonRecord:
        lesson = LessonRecord.create(
            title=str(payload.get("title") or "未命名课时"),
            owner_user_id=owner_user_id,
            subject=str(payload.get("subject") or "地理"),
            grade=str(payload.get("grade") or ""),
            objectives=[str(item) for item in payload.get("objectives", [])],
            stages=self._normalize_stages(payload.get("stages", [])),
            source=source,
            metadata=dict(payload.get("metadata") or {}),
            plan=dict(payload.get("plan") or {}),
        )
        return self.store.upsert_lesson(lesson)

    def update_lesson(self, lesson_id: str, payload: Dict[str, Any]) -> LessonRecord:
        lesson = self.get_lesson(lesson_id)
        if "title" in payload and str(payload["title"]).strip():
            lesson.title = str(payload["title"]).strip()
        if "subject" in payload:
            lesson.subject = str(payload["subject"])
        if "grade" in payload:
            lesson.grade = str(payload["grade"])
        if "objectives" in payload and isinstance(payload["objectives"], list):
            lesson.objectives = [str(item) for item in payload["objectives"]]
        if "stages" in payload and isinstance(payload["stages"], list):
            lesson.stages = self._normalize_stages(payload["stages"])
        if "metadata" in payload and isinstance(payload["metadata"], dict):
            lesson.metadata = {**lesson.metadata, **payload["metadata"]}
        if "plan" in payload and isinstance(payload["plan"], dict):
            lesson.plan = {**lesson.plan, **payload["plan"]}
        return self.store.upsert_lesson(lesson)

    def delete_lesson(self, lesson_id: str) -> None:
        self.store.delete_lesson(lesson_id)

    # ------------------------------------------------------------------
    # Scenes
    # ------------------------------------------------------------------

    def apply_stage_scene(self, project_id: str, lesson_id: str, stage_id: str) -> Dict[str, Any]:
        lesson = self.get_lesson(lesson_id)
        stage = lesson.find_stage(stage_id)
        if stage is None:
            raise KeyError(f"Unknown stage: {stage_id}")
        return self.apply_stage_scene_data(project_id, stage, lesson_id=lesson_id)

    def apply_stage_scene_data(
        self, project_id: str, stage: Dict[str, Any], lesson_id: str = ""
    ) -> Dict[str, Any]:
        """把一个环节的场景声明作用到项目；模拟测试的工作副本环节同样可用。"""
        stage_id = str(stage.get("stage_id") or "")
        project = self.store.get_project(project_id)
        if project is None:
            raise KeyError(f"Unknown project: {project_id}")

        scene = {**default_scene(), **(stage.get("scene") or {})}
        applied: Dict[str, Any] = {"templates": [], "visualization": None}
        if scene.get("strict_resources"):
            from .one_map_catalog import OneMapCatalogService
            catalog = OneMapCatalogService(self.config)
            for dataset_id in scene.get("catalog_layers") or []:
                item = catalog.get_item(dataset_id)
                if not catalog.resolve_item_path(item).is_file():
                    raise ValueError(f"教学数据 {dataset_id} 尚未准备，请先完成课前资料检查。")
        for item in scene.get("teaching_maps") or []:
            info = self.teaching_map_service.get_map(item["id"]) if self.teaching_map_service else None
            if not info or not info.get("available"):
                raise ValueError(f"教学图 {item['id']} 尚未准备，请先完成课前资料检查。")

        with self.store.batch():
            self._reset_stage_layers(project_id, scene)

            basemap_id = str(scene.get("basemap_id") or "")
            if basemap_id:
                base_map = self.config.basemap_by_id(basemap_id)
                self.store.set_basemap(project_id, base_map)

            for template_id in scene.get("templates") or []:
                template_id = str(template_id)
                project = self.store.get_project(project_id)
                template_layer_present = any(
                    str((layer.metadata or {}).get("template_id") or "") == template_id
                    for layer in (project.layers if project else [])
                )
                # A learner or an earlier workflow may delete a generated layer
                # while leaving the template marked as enabled. Rebuild it when
                # the lesson explicitly needs it; otherwise the stage opens on
                # the right extent but shows no thematic map.
                if template_id in project.enabled_templates and template_layer_present:
                    continue
                self.template_service.apply_template(project_id, template_id, {})
                applied["templates"].append(template_id)
                project = self.store.get_project(project_id)

            visual_query = scene.get("visual_query")
            if isinstance(visual_query, dict) and visual_query:
                applied["visualization"] = self._apply_visual_query(project_id, visual_query)

            catalog_ids = [str(item) for item in (scene.get("catalog_layers") or [])]
            catalog_layer_focus = str(scene.get("catalog_layer_focus") or "")
            if catalog_layer_focus not in catalog_ids:
                catalog_layer_focus = ""
            if catalog_ids and self.catalog_layer_loader is not None:
                project = self.store.get_project(project_id)
                existing_catalog = {
                    str((layer.metadata or {}).get("catalog_id") or "")
                    for layer in (project.layers if project else [])
                }
                for dataset_id in catalog_ids:
                    if dataset_id in existing_catalog:
                        continue
                    try:
                        self.catalog_layer_loader(project_id, dataset_id)
                    except (KeyError, ValueError, FileNotFoundError, OSError):
                        # Unknown / unreadable dataset: skip without breaking the scene.
                        continue

            project = self.store.get_project(project_id)
            existing_layer_ids = {layer.layer_id for layer in project.layers}
            catalog_id_set = set(catalog_ids)
            for layer_id, visible in (scene.get("layer_visibility") or {}).items():
                if layer_id not in existing_layer_ids:
                    continue
                self.store.patch_layer(project_id, str(layer_id), {"visible": bool(visible)})
            # Declared catalog layers are shown on top of whatever the reset left.
            # A lesson may preload several evidence layers but focus only one to
            # keep the initial classroom map legible.
            for layer in project.layers:
                catalog_id = str((layer.metadata or {}).get("catalog_id") or "")
                if not catalog_id or catalog_id not in catalog_id_set:
                    continue
                should_show = catalog_id == catalog_layer_focus if catalog_layer_focus else True
                if layer.visible != should_show:
                    self.store.patch_layer(project_id, layer.layer_id, {"visible": should_show})

            self._write_stage_annotations(project_id, scene.get("annotations") or [])
            for item in scene.get("teaching_maps") or []:
                result = self.teaching_map_service.toggle_overlay(project_id, item["id"], True)
                self.store.patch_layer(project_id, result["layer"]["layer_id"], {"opacity": float(item.get("opacity", .5))})

            view = dict(scene.get("view") or {})
            if view:
                self.store.set_view(project_id, view)

            self.store.add_recent_action(
                project_id,
                "应用课堂场景",
                f"已切换到环节“{stage.get('title', stage_id)}”",
                status="success",
                metadata={"lesson_id": lesson_id, "stage_id": stage_id},
            )

        project = self.store.get_project(project_id)
        return {
            "status": "success",
            "lesson_id": lesson_id,
            "stage_id": stage_id,
            "stage_title": stage.get("title", ""),
            "applied_templates": applied["templates"],
            "visualization": applied["visualization"],
            "catalog_layers": catalog_ids,
            "catalog_layer_focus": catalog_layer_focus,
            "view": project.view,
            "base_map": project.base_map,
            "globe": normalize_scene_globe(scene.get("globe")),
        }

    def _reset_stage_layers(self, project_id: str, scene: Dict[str, Any]) -> None:
        """Stage scenes are declarative: layers auto-loaded for a previous
        stage (metric-query highlights, template layers, catalog datasets)
        must not leak into the next one.  Explicit ``layer_visibility``
        entries are applied afterwards and win over this reset."""
        project = self.store.get_project(project_id)
        if project is None:
            return
        scene_templates = {str(item) for item in scene.get("templates") or []}
        scene_catalog_ids = {str(item) for item in scene.get("catalog_layers") or []}
        scene_map_ids = {item["id"] for item in scene.get("teaching_maps") or []}
        for layer in list(project.layers):
            layer_id = layer.layer_id
            if layer.metadata.get("teacher_topic") == "finland_population_2015":
                if layer.visible:
                    self.store.patch_layer(project_id, layer_id, {"visible": False})
                continue
            if layer.source == "teaching_map":
                desired = str(layer.metadata.get("teaching_map_id") or "") in scene_map_ids
                if layer.visible != desired:
                    self.store.patch_layer(project_id, layer_id, {"visible": desired})
                continue
            # Assistant annotations and POIs belong to the previous map discussion. Keep
            # their data, but hide them unless this scene explicitly requests them.
            if layer_id in {"assistant_annotations", "poi_search_results"} and layer.visible:
                self.store.patch_layer(project_id, layer_id, {"visible": False})
            if layer_id.startswith("visual_query_"):
                self.store.remove_layer(project_id, layer_id)
                continue
            template_id = str((layer.metadata or {}).get("template_id") or "")
            if template_id:
                desired = template_id in scene_templates
                if layer.visible != desired:
                    self.store.patch_layer(project_id, layer_id, {"visible": desired})
                continue
            if layer.source == "one_map_catalog" or layer_id.startswith("one_map_"):
                catalog_id = str((layer.metadata or {}).get("catalog_id") or "")
                if catalog_id and catalog_id in scene_catalog_ids:
                    continue
                if layer.visible:
                    self.store.patch_layer(project_id, layer_id, {"visible": False})

    @staticmethod
    def merge_scene_snapshot(scene: Dict[str, Any], snapshot: Dict[str, Any]) -> Dict[str, Any]:
        """把当前地图快照并入环节场景声明（模拟测试存图与课时存图共用）。"""
        scene = {**default_scene(), **(scene or {})}

        if snapshot.get("basemap_id"):
            scene["basemap_id"] = str(snapshot["basemap_id"])
        if isinstance(snapshot.get("view"), dict) and snapshot["view"]:
            scene["view"] = {
                key: snapshot["view"][key]
                for key in ("center", "zoom", "extent")
                if key in snapshot["view"]
            }
        if isinstance(snapshot.get("layer_visibility"), dict):
            scene["layer_visibility"] = {
                str(layer_id): bool(visible)
                for layer_id, visible in snapshot["layer_visibility"].items()
            }
        if isinstance(snapshot.get("templates"), list):
            scene["templates"] = [str(item) for item in snapshot["templates"]]
        if isinstance(snapshot.get("globe"), dict):
            scene["globe"] = normalize_scene_globe(snapshot["globe"])
        return scene

    def capture_stage_scene(self, lesson_id: str, stage_id: str, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        lesson = self.get_lesson(lesson_id)
        stage = lesson.find_stage(stage_id)
        if stage is None:
            raise KeyError(f"Unknown stage: {stage_id}")
        scene = self.merge_scene_snapshot(stage.get("scene") or {}, snapshot)

        stage["scene"] = scene
        self.store.upsert_lesson(lesson)
        return {"status": "success", "lesson_id": lesson_id, "stage_id": stage_id, "scene": scene}

    def _apply_visual_query(self, project_id: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        result = self.visual_query_service.run(project_id, params)
        layer_dict = result["layer"]
        layer = LayerRecord.create(
            layer_id=layer_dict["layer_id"],
            name=layer_dict["name"],
            kind=layer_dict["kind"],
            source=layer_dict["source"],
            geometry_type=layer_dict["geometry_type"],
            visible=layer_dict.get("visible", True),
            opacity=layer_dict.get("opacity", 1.0),
            z_index=layer_dict.get("z_index", 80),
            style=layer_dict.get("style") or {},
            data=layer_dict.get("data") or {},
            metadata=layer_dict.get("metadata") or {},
        )
        self.store.upsert_layer(project_id, layer)
        self.store.set_active_layer(project_id, layer.layer_id)
        return result.get("visualization")

    def _write_stage_annotations(self, project_id: str, annotations: List[Dict[str, Any]]) -> None:
        project = self.store.get_project(project_id)
        has_layer = any(layer.layer_id == LESSON_ANNOTATION_LAYER_ID for layer in project.layers)
        if not annotations and not has_layer:
            return
        features = []
        for item in annotations:
            position = item.get("position") or []
            if len(position) < 2:
                continue
            text = str(item.get("text") or "课堂标注")
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "name": text,
                        "label": text,
                        "__fillColor": "#fde047",
                        "__strokeColor": "#0f172a",
                        "__radius": 8,
                    },
                    "geometry": {"type": "Point", "coordinates": [float(position[0]), float(position[1])]},
                }
            )
        layer = LayerRecord.create(
            layer_id=LESSON_ANNOTATION_LAYER_ID,
            name="环节标注",
            kind="annotation",
            source="lesson",
            geometry_type="Point",
            visible=bool(features),
            data={"type": "FeatureCollection", "features": features},
            style={"labelField": "label", "fillColor": "#fde047", "radius": 8, "strokeColor": "#0f172a"},
            z_index=110,
        )
        self.store.upsert_layer(project_id, layer)

    # ------------------------------------------------------------------
    # Import from pasted lesson-plan text
    # ------------------------------------------------------------------

    def import_from_text(self, text: str, owner_user_id: str = "") -> Dict[str, Any]:
        cleaned = (text or "").strip()
        if not cleaned:
            raise ValueError("Lesson import requires non-empty text")
        parsed: Optional[Dict[str, Any]] = None
        parser = "heuristic"
        if self.minimax_client is not None:
            try:
                parsed = self._parse_with_llm(cleaned)
                parser = "minimax"
            except Exception:
                parsed = None
        if parsed is None:
            parsed = self._parse_heuristically(cleaned)
        lesson = self.create_lesson(
            parsed,
            source="imported",
            owner_user_id=owner_user_id,
        )
        return {"status": "success", "parser": parser, "lesson": lesson.to_dict()}

    def _parse_with_llm(self, text: str) -> Dict[str, Any]:
        if self.minimax_client is None:
            raise RuntimeError("LLM client unavailable")
        system = (
            "你是地理教研员，请把教师提供的教案文本解析为结构化课时 JSON。"
            "只输出 JSON，不要输出任何解释。JSON schema 示例："
            + json.dumps(LESSON_IMPORT_SCHEMA_HINT, ensure_ascii=False)
            + "。要求：stage_id 用 s1..sN；minutes 为整数；每个环节尽量提取教师提问到 questions"
            "（无选项的用 type=open，options=[]，answer_index=null），并把可能的学生误区写入 misconceptions；"
            "scene 中的 templates 只能从这些 id 里选（没有合适的就留空数组）："
            "population_distribution / population_density / population_migration / hu_line_comparison / "
            "population_classroom_pack；layer_visibility 的图层 id 只能用："
            "builtin_population_regions / builtin_population_density / builtin_population_migration / "
            "generated_hu_line；"
            "basemap_id 只能用 amap_light / amap_vector / amap_imagery。"
            "scene 中的 catalog_layers（可选）是一张图数据集 id 数组，常用："
            "china_climate_types / china_province_gdp_per_capita / china_city_gdp_per_capita / "
            "china_provinces / shanghai_population_density / shanghai_districts / hu_huanyong_line；"
            "不确定时留空数组。"
        )
        content = self.minimax_client.chat_completion(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": text[:12000]},
            ],
            temperature=0.1,
        )
        payload = _extract_json_payload(content)
        if not isinstance(payload, dict) or not payload.get("stages"):
            raise ValueError("LLM lesson parse returned no stages")
        return payload

    def _parse_heuristically(self, text: str) -> Dict[str, Any]:
        lines = [line.strip() for line in text.splitlines()]
        title = next((line.lstrip("# ").strip() for line in lines if line.lstrip("# ").strip()), "导入课时")

        stage_pattern = re.compile(
            r"^(?:#+\s*)?(?:###?\s*)?(?:(?:第?[一二三四五六七八九十\d]+[、.．)]\s*)|(?:\d+[-–~]\d+\s*分钟[:：]?\s*))?(.{2,40})$"
        )
        heading_pattern = re.compile(r"^#{2,}\s+(.+)$|^(?:[一二三四五六七八九十]+、)(.+)$|^(\d+[-–~]\d+\s*分钟[:：].+)$")
        minutes_pattern = re.compile(r"(\d+)\s*分钟")

        stages: List[Dict[str, Any]] = []
        current: Optional[Dict[str, Any]] = None
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            match = heading_pattern.match(line)
            if match:
                heading = next((group for group in match.groups() if group), "").strip()
                if heading:
                    minutes_match = minutes_pattern.search(heading)
                    current = {
                        "stage_id": f"s{len(stages) + 1}",
                        "title": heading[:40],
                        "minutes": int(minutes_match.group(1)) if minutes_match else 5,
                        "scene": default_scene(),
                        "script": [],
                        "questions": [],
                        "assistant_prompts": [],
                    }
                    stages.append(current)
                    continue
            if current is None:
                continue
            if line.endswith("？") or line.endswith("?"):
                question_text = line.lstrip("-•*0123456789.、 ").strip("“”\"")
                current["questions"].append(
                    {
                        "question_id": f"{current['stage_id']}q{len(current['questions']) + 1}",
                        "type": "open",
                        "text": question_text,
                        "options": [],
                        "answer_index": None,
                        "expected_points": [],
                        "misconceptions": [],
                    }
                )
            elif len(current["script"]) < 4:
                current["script"].append(line.lstrip("-•* ").strip())

        if not stages:
            stages = [
                {
                    "stage_id": "s1",
                    "title": "课堂主环节",
                    "minutes": 40,
                    "scene": default_scene(),
                    "script": [line for line in lines if line][:4],
                    "questions": [],
                    "assistant_prompts": [],
                }
            ]
        return {"title": title[:60], "objectives": [], "stages": stages}

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------

    def _normalize_stages(self, stages: Any) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        if not isinstance(stages, list):
            return normalized
        for index, raw in enumerate(stages, start=1):
            if not isinstance(raw, dict):
                continue
            stage_id = str(raw.get("stage_id") or f"s{index}")
            raw_kind = str(raw.get("kind") or "")
            kind = raw_kind if raw_kind in STAGE_KINDS else ""
            scene = {**default_scene(), **(raw.get("scene") or {})}
            raw_catalog = scene.get("catalog_layers")
            scene["catalog_layers"] = [str(item) for item in raw_catalog] if isinstance(raw_catalog, list) else []
            raw_catalog_focus = str(scene.get("catalog_layer_focus") or "")
            scene["catalog_layer_focus"] = raw_catalog_focus if raw_catalog_focus in scene["catalog_layers"] else ""
            scene["globe"] = normalize_scene_globe(scene.get("globe"))
            scene["teaching_maps"] = normalize_teaching_maps(scene.get("teaching_maps"))
            questions = []
            for q_index, question in enumerate(raw.get("questions") or [], start=1):
                if not isinstance(question, dict):
                    continue
                questions.append(self._normalize_stage_question(question, stage_id, q_index))
            objective_refs = [
                int(item)
                for item in raw.get("objective_refs") or []
                if isinstance(item, int) or (isinstance(item, str) and item.isdigit())
            ]
            normalized.append(
                {
                    "stage_id": stage_id,
                    "title": str(raw.get("title") or f"环节 {index}"),
                    "minutes": 0 if raw.get("timing_mode") == "teacher" else max(1, int(raw.get("minutes") or 5)),
                    "timing_mode": "teacher" if raw.get("timing_mode") == "teacher" else "planned",
                    "source_row": raw.get("source_row"),
                    "actions": normalize_lesson_actions(raw.get("actions")),
                    "kind": kind,
                    "scene": scene,
                    "script": [str(item) for item in raw.get("script") or []],
                    "questions": questions,
                    "assistant_prompts": [str(item) for item in raw.get("assistant_prompts") or []],
                    "knowledge_unit": str(raw.get("knowledge_unit") or ""),
                    "knowledge_point": str(raw.get("knowledge_point") or ""),
                    "content": str(raw.get("content") or raw.get("teaching_activity") or ""),
                    "activities": [str(item) for item in raw.get("activities") or []],
                    "material": str(raw.get("material") or ""),
                    "question_chain": [str(item) for item in raw.get("question_chain") or [] if str(item)],
                    "teacher_activities": [str(item) for item in raw.get("teacher_activities") or [] if str(item)],
                    "student_activities": [str(item) for item in raw.get("student_activities") or [] if str(item)],
                    "knowledge_conclusion": str(raw.get("knowledge_conclusion") or ""),
                    "design_intent": str(raw.get("design_intent") or ""),
                    "system_steps": [str(item) for item in raw.get("system_steps") or []],
                    "objective_refs": objective_refs,
                    "brainstorm": normalize_brainstorm(raw.get("brainstorm")),
                    "evidence_refs": normalize_evidence_refs(raw.get("evidence_refs")),
                    "teacher_guidance": normalize_teacher_guidance(raw.get("teacher_guidance")),
                    "presentation": normalize_presentation(raw.get("presentation")),
                    "profile_preset": normalize_profile_preset(raw.get("profile_preset")),
                }
            )
        return normalized

    @staticmethod
    def _normalize_stage_question(question: Dict[str, Any], stage_id: str, q_index: int) -> Dict[str, Any]:
        """环节题目规范化：保留旧 choice/open 题型，新增 composite 与题库/手动快照字段。

        题库快照（source=question_bank）与教师手动题（source=teacher_manual）
        的答案、解析、题图、小问等字段原样保留，保证快照不可变。
        """
        options = [str(option) for option in question.get("options") or []]
        sub_questions = [
            {
                "index": str(sub.get("index") or sub_index + 1),
                "text": str(sub.get("text") or ""),
                "options": [str(item) for item in sub.get("options") or []],
                "answer": str(sub.get("answer") or ""),
                "answer_index": sub.get("answer_index") if isinstance(sub.get("answer_index"), int) else None,
                "explanation": str(sub.get("explanation") or ""),
            }
            for sub_index, sub in enumerate(question.get("sub_questions") or [])
            if isinstance(sub, dict)
        ]
        q_type = str(question.get("type") or "open").strip()
        if sub_questions:
            q_type = "composite"
        elif options:
            q_type = "choice"
        elif q_type not in {"choice", "open", "composite"}:
            q_type = "open"
        answer_index = question.get("answer_index")
        if not isinstance(answer_index, int) or not (0 <= answer_index < len(options)):
            answer_index = None
        source = str(question.get("source") or "").strip()
        if source not in {"question_bank", "teacher_manual"}:
            source = "design"
        answer = str(question.get("answer") or "")
        answer_complete = question.get("answer_complete")
        if not isinstance(answer_complete, bool):
            if sub_questions:
                answer_complete = all(str(sub.get("answer") or "").strip() for sub in sub_questions)
            elif options:
                answer_complete = answer_index is not None or bool(answer.strip())
            else:
                answer_complete = bool(answer.strip())
        try:
            suggested_seconds = int(question.get("suggested_seconds") or 0)
        except (TypeError, ValueError):
            suggested_seconds = 0
        return {
            "question_id": str(question.get("question_id") or f"{stage_id}q{q_index}"),
            "type": q_type,
            "source": source,
            "text": str(question.get("text") or ""),
            "task_text": str(question.get("task_text") or ""),
            "material": str(question.get("material") or ""),
            "options": options,
            "answer": answer,
            "answer_letter": str(question.get("answer_letter") or ""),
            "answer_index": answer_index,
            "explanation": str(question.get("explanation") or ""),
            "sub_questions": sub_questions,
            "images": [
                {
                    "url": str(image.get("url") or ""),
                    "width": int(image.get("width") or 0),
                    "height": int(image.get("height") or 0),
                    "content_type": str(image.get("content_type") or ""),
                    "anchor": str(image.get("anchor") or "group"),
                    "order": int(image.get("order") or 0),
                }
                for image in question.get("images") or []
                if isinstance(image, dict)
            ],
            "answer_complete": answer_complete,
            "knowledge_points": [str(item) for item in question.get("knowledge_points") or []],
            "year": str(question.get("year") or ""),
            "region": str(question.get("region") or ""),
            "source_paper": str(question.get("source_paper") or ""),
            "bank_id": str(question.get("bank_id") or ""),
            "group_key": str(question.get("group_key") or ""),
            "number": str(question.get("number") or ""),
            "suggested_seconds": suggested_seconds,
            "expected_points": [str(item) for item in question.get("expected_points") or []],
            "misconceptions": [
                {
                    "tag": str(item.get("tag") or ""),
                    "description": str(item.get("description") or ""),
                }
                for item in question.get("misconceptions") or []
                if isinstance(item, dict)
            ],
            "evidence_refs": normalize_evidence_refs(question.get("evidence_refs")),
            "argument_chain": [str(item) for item in question.get("argument_chain") or [] if str(item)],
            "remediation_task": str(question.get("remediation_task") or ""),
            "explanation_source": str(question.get("explanation_source") or ("official" if source == "question_bank" else "")),
        }


def _extract_json_payload(content: str) -> Dict[str, Any]:
    cleaned = (content or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise
