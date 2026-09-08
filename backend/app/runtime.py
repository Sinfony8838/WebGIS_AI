from __future__ import annotations

import base64
import csv
import json
import math
import re
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from .config import AppConfig
from .models import LayerRecord, ProjectRecord, WorkflowRecord, build_assistant_v2_stages, build_workflow_stages, utc_now
from .services.assistant import ASSISTANT_TOOL_SCHEMA, AssistantService
from .services.classroom_workflow import ClassroomWorkflowRuntime
from .services.datasets import DatasetService
from .services.knowledge import KnowledgeService
from .services.knowledge_base import KnowledgeBaseService
from .services.llm_planner import LLMPlanner
from .services.minimax_client import build_llm_client
from .services.minimax_image_client import MiniMaxImageClient
from .services.one_map_catalog import OneMapCatalogService
from .services.population_sources import PopulationSourceRegistryService
from .services.timeline_service import TimelineService
from .services.poi import PoiService
from .services.resource_search import ResourceSearchService
from .services.voice_asr import VoiceAsrEngine
from .services.session_engine import AssistantSessionEngine
from .services.teaching_maps import TeachingMapService
from .services.workflow_executor import WorkflowExecutor
from .services.workflow_templates import INTERACTION_ALLOWED_TEMPLATES, detect_template, expand_template, list_templates
from .services.templates import DISABLED_TEMPLATE_IDS, TemplateService
from .services.vision import MapVisionService
from .store import RuntimeStore


TRANSPARENT_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAEElEQVR42mP8z8BQDwAFgwJ/lU9nWQAAAABJRU5ErkJggg=="
)

MAX_IMAGE_LIBRARY_BYTES = 20 * 1024 * 1024
SUPPORTED_IMAGE_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def _detect_image_mime(raw_bytes: bytes) -> str:
    if raw_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if raw_bytes.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(raw_bytes) >= 12 and raw_bytes[:4] == b"RIFF" and raw_bytes[8:12] == b"WEBP":
        return "image/webp"
    return ""


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _safe_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or "").strip())
    return cleaned.strip("_") or "dataset"


def _first_geometry_type(payload: Dict[str, Any]) -> str:
    for feature in payload.get("features", []) if isinstance(payload.get("features"), list) else []:
        geometry = feature.get("geometry") if isinstance(feature, dict) else None
        if isinstance(geometry, dict) and geometry.get("type"):
            return str(geometry["type"])
    return "Unknown"


def _iter_coords(value: Any):
    if isinstance(value, (list, tuple)):
        if len(value) >= 2 and all(isinstance(part, (int, float)) for part in value[:2]):
            yield float(value[0]), float(value[1])
            return
        for item in value:
            yield from _iter_coords(item)


def _geojson_bounds(payload: Dict[str, Any]) -> List[float]:
    coords = list(_iter_coords(payload.get("coordinates") if payload.get("type") != "FeatureCollection" else [
        feature.get("geometry", {}).get("coordinates")
        for feature in payload.get("features", [])
        if isinstance(feature, dict)
    ]))
    if not coords:
        return [73, 18, 135, 54]
    xs = [point[0] for point in coords]
    ys = [point[1] for point in coords]
    return [min(xs), min(ys), max(xs), max(ys)]


def _bounds_center(bounds: List[float]) -> List[float]:
    return [(bounds[0] + bounds[2]) / 2.0, (bounds[1] + bounds[3]) / 2.0]


def _feature_point(feature: Dict[str, Any]) -> Optional[List[float]]:
    geometry = feature.get("geometry") if isinstance(feature, dict) else None
    if not isinstance(geometry, dict):
        return None
    if geometry.get("type") == "Point":
        coords = geometry.get("coordinates")
        if isinstance(coords, list) and len(coords) >= 2:
            return [float(coords[0]), float(coords[1])]
    bounds = _geojson_bounds(geometry)
    return _bounds_center(bounds)


def _point_in_ring(point: List[float], ring: Any) -> bool:
    if not isinstance(ring, list) or len(ring) < 3:
        return False
    x, y = point
    inside = False
    j = len(ring) - 1
    for i, current in enumerate(ring):
        previous = ring[j]
        j = i
        if not (isinstance(current, list) and isinstance(previous, list) and len(current) >= 2 and len(previous) >= 2):
            continue
        xi, yi = float(current[0]), float(current[1])
        xj, yj = float(previous[0]), float(previous[1])
        intersects = (yi > y) != (yj > y) and x < ((xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi)
        if intersects:
            inside = not inside
    return inside


def _point_in_polygon(point: List[float], polygon: Any) -> bool:
    if not isinstance(polygon, list) or not polygon:
        return False
    if not _point_in_ring(point, polygon[0]):
        return False
    return not any(_point_in_ring(point, hole) for hole in polygon[1:] if isinstance(hole, list))


def _point_in_selection(point: List[float], geometry: Optional[Dict[str, Any]]) -> bool:
    if not geometry:
        return True
    geom_type = geometry.get("type")
    coords = geometry.get("coordinates")
    if geom_type == "Polygon":
        return _point_in_polygon(point, coords)
    if geom_type == "MultiPolygon" and isinstance(coords, list):
        return any(_point_in_polygon(point, polygon) for polygon in coords)
    return True


def _as_number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _coerce_catalog_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if stripped == "":
        return ""
    number = _as_number(stripped)
    if number is None:
        return stripped
    return int(number) if number.is_integer() else number


def _normalize_join_value(value: Any) -> str:
    return str(value or "").strip().upper()


CSV_JOIN_DEFAULTS: Dict[str, Dict[str, str]] = {
    "world_population_by_country": {
        "geometry_source": "world_countries",
        "join_key": "region_code",
    }
}


def _shape_area_stats(
    feature_geometry: Optional[Dict[str, Any]],
    selection_geometry: Optional[Dict[str, Any]],
) -> Optional[Dict[str, float]]:
    if not isinstance(feature_geometry, dict) or feature_geometry.get("type") not in {"Polygon", "MultiPolygon"}:
        return None
    try:
        from pyproj import Transformer  # type: ignore
        from shapely.geometry import shape  # type: ignore
        from shapely.ops import transform  # type: ignore
        from shapely.validation import make_valid  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Area-weighted statistics require shapely and pyproj. Run pip install -r requirements.txt.") from exc

    transformer = Transformer.from_crs("EPSG:4326", "EPSG:6933", always_xy=True)
    feature_shape = make_valid(shape(feature_geometry))
    if feature_shape.is_empty:
        return None
    projected_feature = make_valid(transform(transformer.transform, feature_shape))
    feature_area_m2 = float(projected_feature.area)
    if feature_area_m2 <= 0:
        return None
    if not selection_geometry:
        return {"ratio": 1.0, "area_km2": feature_area_m2 / 1_000_000.0}

    selection_shape = make_valid(shape(selection_geometry))
    if selection_shape.is_empty:
        return {"ratio": 0.0, "area_km2": 0.0}
    projected_selection = make_valid(transform(transformer.transform, selection_shape))
    intersection_area_m2 = float(projected_feature.intersection(projected_selection).area)
    ratio = max(0.0, min(1.0, intersection_area_m2 / feature_area_m2))
    return {"ratio": ratio, "area_km2": intersection_area_m2 / 1_000_000.0}


def _classify_colors(features: List[Dict[str, Any]], field: str) -> None:
    values = [
        value
        for value in (_as_number((feature.get("properties") or {}).get(field)) for feature in features)
        if value is not None
    ]
    values = sorted(values)
    colors = ["#fef3c7", "#fde68a", "#f59e0b", "#dc2626", "#7f1d1d"]
    if not values:
        for feature in features:
            (feature.setdefault("properties", {}))["__fillColor"] = "#38bdf8"
            (feature.setdefault("properties", {}))["__fillOpacity"] = 0.24
        return
    breaks = [values[min(len(values) - 1, int((len(values) - 1) * q / 5))] for q in range(1, 6)]
    for feature in features:
        props = feature.setdefault("properties", {})
        value = _as_number(props.get(field))
        if value is None:
            props["__fillColor"] = "#94a3b8"
            props["__fillOpacity"] = 0.28
            props["__strokeColor"] = "#334155"
            props["__strokeWidth"] = 0.8
            continue
        index = 0
        while index < len(breaks) - 1 and value > breaks[index]:
            index += 1
        props["__fillColor"] = colors[index]
        props["__fillOpacity"] = 0.42
        props["__strokeColor"] = "#334155"
        props["__strokeWidth"] = 0.8


def _decorate_default_style(features: List[Dict[str, Any]], geometry_type: str = "") -> None:
    is_line = "Line" in geometry_type
    is_point = "Point" in geometry_type
    for feature in features:
        props = feature.setdefault("properties", {})
        props.setdefault("__fillColor", "#38bdf8")
        props.setdefault("__fillOpacity", 0.28 if not is_line else 0.0)
        props.setdefault("__strokeColor", "#2563eb" if is_line else "#0f172a")
        props.setdefault("__strokeWidth", 2.4 if is_line else 0.9)
        if is_point:
            props.setdefault("__radius", 5.5)


def _fallback_summary(record: "WorkflowRecord", stats_payload: Dict[str, Any]) -> str:
    """Plain-text summary used when MiniMax is unavailable."""
    lines: List[str] = []
    if record.intent:
        lines.append(f"### {record.intent}")
    summary = (stats_payload or {}).get("summary") or {}
    if summary:
        snippet_keys = list(summary.keys())[:6]
        details = "，".join(f"{k}: {summary[k]}" for k in snippet_keys)
        if details:
            lines.append(f"统计要点：{details}。")
    rows = (stats_payload or {}).get("rows") or []
    if rows:
        first = rows[0]
        if isinstance(first, dict):
            sample = "、".join(f"{k}={v}" for k, v in list(first.items())[:3])
            lines.append(f"示例：{sample}。")
    if not lines:
        lines.append("分析任务已完成，可在右侧查看图层、图例和统计表。")
    return "\n\n".join(lines)


class WebGISRuntime:
    def __init__(self, config: Optional[AppConfig] = None, store: Optional[RuntimeStore] = None):
        self.config = config or AppConfig()
        self.config.ensure_dirs()
        self.store = store or RuntimeStore(self.config.state_file)
        self.dataset_service = DatasetService(self.config, self.store)
        self.template_service = TemplateService(self.config, self.store)
        self.assistant_service = AssistantService(self.config)
        self.knowledge_service = KnowledgeService(self.config)
        self.knowledge_base_service = KnowledgeBaseService(self.config)
        self.one_map_catalog_service = OneMapCatalogService(self.config)
        self.population_source_registry_service = PopulationSourceRegistryService(
            self.config,
            self.store,
            self.one_map_catalog_service,
            self.knowledge_base_service,
        )
        self.resource_search_service = ResourceSearchService(self.config, self.knowledge_base_service)
        self.poi_service = PoiService(self.config, self.store)
        self.vision_service = MapVisionService(self.config)
        self.minimax_client = build_llm_client(self.config)
        self.image_generation_service = MiniMaxImageClient(self.config)
        self.teaching_map_service = TeachingMapService(self.config, self.store)
        self.assistant_service.teaching_map_service = self.teaching_map_service
        self.assistant_service.minimax_client = self.minimax_client
        self.llm_planner = LLMPlanner(self.minimax_client, self.assistant_service)
        self.session_engine = AssistantSessionEngine(
            self.config,
            self.store,
            self.llm_planner,
            self.assistant_service,
            self._execute_assistant_action,
            vision_service=self.vision_service,
        )
        self.session_engine.set_resource_search(self.resource_search_service)
        self.workflow_executor = WorkflowExecutor(
            self.config,
            self.store,
            summary_callback=self._generate_workflow_summary,
        )
        self.timeline_service = TimelineService(self.minimax_client)
        self.voice_asr = VoiceAsrEngine(self.config)
        self.classroom = ClassroomWorkflowRuntime(self)
        self.session_engine.set_session_stats_provider(self._session_statistics_for_assistant)
        self._normalize_loaded_projects()

    # Compatibility entry points retained for callers built against the
    # pre-merge classroom runtime API.
    def apply_lesson_scene(self, project_id: str, lesson_id: str, stage_id: str) -> Dict[str, Any]:
        return self.classroom.apply_lesson_scene(project_id, lesson_id, stage_id)

    def capture_lesson_scene(self, lesson_id: str, stage_id: str, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        return self.classroom.capture_lesson_scene(lesson_id, stage_id, snapshot)

    def _compose_knowledge_answer(self, project: ProjectRecord, focus: str, map_context: Dict[str, Any]) -> str:
        fallback = self.assistant_service.compose_explanation(project, map_context=map_context, focus=focus)
        query = focus or "、".join(layer.name for layer in project.layers if layer.visible)
        cards = self.knowledge_service.search(query, limit=3)
        if not cards:
            return fallback
        card = cards[0]
        canonical = str(card.get("canonical_answer") or "").strip()
        if not canonical:
            return fallback
        return f"{fallback}\n\n知识参考（{card.get('title', '')}）：{canonical}"

    def health(self) -> Dict[str, Any]:
        return {
            "status": "success",
            "runtime": {
                "api": self.config.public_api_base_url(),
                "workspace": str(self.config.root_dir),
                "uploads": str(self.config.uploads_dir),
                "outputs": str(self.config.outputs_dir),
            },
            "ui": {
                "mode": "single_teacher_live_demo",
                "assistant_tools": ASSISTANT_TOOL_SCHEMA,
                "assistant_v2_enabled": self.config.assistant_v2_enabled,
            },
            "online_services": {
                "amap_poi_enabled": self.config.online_services_enabled(),
                "weather_basemap_enabled": self.config.weather_basemap_enabled(),
            },
            "llm": self.minimax_client.status(),
            "voice_asr": self.voice_asr.status(),
            "vision": self.vision_service.status(),
            "image_generation": self.image_generation_service.status(),
            "gis_workflow": {
                "enabled": True,
                "engine": "pyqgis_worker",
                "qgis_root": self.config.qgis_root or "",
                "init_warning": self.workflow_executor.init_warning() if hasattr(self, "workflow_executor") else None,
            },
            "basemaps": self.config.basemap_catalog(),
            "templates": self.template_service.list_templates()["items"],
            "knowledge_base": {
                "manifest_path": str(self.knowledge_base_service.manifest_path),
                "item_count": len(self.knowledge_base_service.get_manifest().get("items", [])),
            },
        }

    def list_teaching_maps(self) -> Dict[str, Any]:
        return self.teaching_map_service.list_maps()

    def toggle_teaching_map(self, project_id: str, map_id: str, visible: bool = True) -> Dict[str, Any]:
        self._require_project(project_id)
        return self.teaching_map_service.toggle_overlay(project_id, map_id, visible)

    def get_active_teaching_maps(self, project_id: str) -> Dict[str, Any]:
        self._require_project(project_id)
        return {"status": "success", "active": self.teaching_map_service.get_active_overlays(project_id)}

    def kb_manifest(self, owner_user_id: str = "", include_all: bool = False) -> Dict[str, Any]:
        return self.knowledge_base_service.get_manifest(
            owner_user_id=owner_user_id,
            include_all=include_all,
        )

    def kb_search(
        self,
        query: str = "",
        topic: str = "",
        region: str = "",
        tag: str = "",
        limit: int = 20,
        owner_user_id: str = "",
        include_all: bool = False,
    ) -> Dict[str, Any]:
        return self.knowledge_base_service.search(
            query=query,
            topic=topic,
            region=region,
            tag=tag,
            limit=limit,
            owner_user_id=owner_user_id,
            include_all=include_all,
        )

    def kb_topics(self, owner_user_id: str = "", include_all: bool = False) -> Dict[str, Any]:
        return self.knowledge_base_service.topics(
            owner_user_id=owner_user_id,
            include_all=include_all,
        )

    def kb_upsert_item(
        self,
        item: Dict[str, Any],
        owner_user_id: str = "",
        include_all: bool = False,
    ) -> Dict[str, Any]:
        normalized = self.knowledge_base_service.upsert_item(
            item,
            owner_user_id=owner_user_id,
            include_all=include_all,
        )
        return {"status": "success", "item": normalized}

    def kb_register_layer(
        self,
        project_id: str,
        layer_id: str,
        metadata: Optional[Dict[str, Any]] = None,
        owner_user_id: str = "",
        include_all: bool = False,
    ) -> Dict[str, Any]:
        project = self._require_project(project_id)
        target_layer = next((layer for layer in project.layers if layer.layer_id == layer_id), None)
        if target_layer is None:
            raise KeyError(f"Unknown layer in project: {layer_id}")
        item = self.knowledge_base_service.build_item_from_layer(
            project_id,
            target_layer,
            metadata or {},
            owner_user_id=owner_user_id,
        )
        normalized = self.knowledge_base_service.upsert_item(
            item,
            owner_user_id=owner_user_id,
            include_all=include_all,
        )
        self.store.add_recent_action(
            project_id,
            "知识库登记",
            f"图层“{target_layer.name}”已登记到知识库",
            status="success",
            metadata={"layer_id": layer_id, "kb_item_id": normalized.get("id", "")},
        )
        return {"status": "success", "item": normalized}

    def kb_upload_material(
        self,
        kb_item_id: str,
        filename: str,
        raw_bytes: bytes,
        title: str = "",
        description: str = "",
        material_type: str = "",
        region_binding: Optional[Dict[str, Any]] = None,
        owner_user_id: str = "",
        include_all: bool = False,
    ) -> Dict[str, Any]:
        suffix = Path(filename or "").suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".mp4", ".webm", ".mov", ".m4v", ".html", ".htm", ".pdf", ".doc", ".docx", ".ppt", ".pptx"}:
            raise ValueError(f"Unsupported material type: {suffix or 'unknown'}")
        safe_name = self._safe_upload_filename(filename or f"material{suffix}")
        output_dir = self.config.uploads_dir / "kb_materials"
        output_path = self.config.unique_path(output_dir, safe_name)
        output_path.write_bytes(raw_bytes)
        material = self.knowledge_base_service.add_material_to_item(
            kb_item_id,
            {
                "title": title or Path(filename).stem or "教学资料",
                "type": material_type,
                "source": "teacher_upload",
                "url": self.config.public_url_for_path(output_path),
                "thumbnail_url": self.config.public_url_for_path(output_path) if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"} else "",
                "description": description,
                "region_binding": region_binding or {},
            },
            owner_user_id=owner_user_id,
            include_all=include_all,
        )
        return {"status": "success", "material": material}

    def kb_link_material(
        self,
        kb_item_id: str,
        url: str,
        title: str = "",
        description: str = "",
        material_type: str = "link",
        thumbnail_url: str = "",
        region_binding: Optional[Dict[str, Any]] = None,
        owner_user_id: str = "",
        include_all: bool = False,
    ) -> Dict[str, Any]:
        if not str(url or "").strip().lower().startswith(("http://", "https://", "/files/")):
            raise ValueError("Material link must be an http(s) URL or a public /files URL")
        material = self.knowledge_base_service.add_material_to_item(
            kb_item_id,
            {
                "title": title or url,
                "type": material_type or "link",
                "source": "teacher_link",
                "url": url,
                "thumbnail_url": thumbnail_url,
                "description": description,
                "region_binding": region_binding or {},
            },
            owner_user_id=owner_user_id,
            include_all=include_all,
        )
        return {"status": "success", "material": material}

    def resource_search(
        self,
        query: str = "",
        scope: str = "all",
        limit: int = 12,
        owner_user_id: str = "",
        include_all: bool = False,
    ) -> Dict[str, Any]:
        return self.resource_search_service.search(
            query=query,
            scope=scope,
            limit=limit,
            owner_user_id=owner_user_id,
            include_all=include_all,
        )

    def list_population_source_versions(self, project_id: str = "") -> Dict[str, Any]:
        return self.population_source_registry_service.list_versions(project_id=project_id)

    def list_population_sources(
        self,
        project_id: str = "",
        version: str = "",
    ) -> Dict[str, Any]:
        return self.population_source_registry_service.list_sources(project_id=project_id, version=version)

    def get_population_source(
        self,
        source_id: str,
        project_id: str = "",
        version: str = "",
        expected_fingerprint: str = "",
    ) -> Dict[str, Any]:
        return self.population_source_registry_service.get_source(
            source_id,
            project_id=project_id,
            version=version,
            expected_fingerprint=expected_fingerprint,
        )

    def compare_population_source_versions(self, from_version: str, to_version: str) -> Dict[str, Any]:
        return self.population_source_registry_service.compare_versions(from_version, to_version)

    def activate_population_source_version(self, project_id: str, version: str) -> Dict[str, Any]:
        return self.population_source_registry_service.activate_version(project_id, version)

    def list_lesson_resources(self, project_id: str) -> Dict[str, Any]:
        project = self._require_project(project_id)
        sets = self._lesson_resource_sets(project.project_id, project.metadata)
        active_id = str(project.metadata.get("active_lesson_resource_set_id") or "")
        return {"status": "success", "items": sets, "active_lesson_resource_set_id": active_id}

    def save_lesson_resource_set(self, project_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        project = self._require_project(project_id)
        sets = self._lesson_resource_sets(project.project_id, project.metadata)
        now = self.store_timestamp()
        resource_set = self._normalize_lesson_resource_set(project_id, payload, now)
        replaced = False
        for index, existing in enumerate(sets):
            if existing["id"] == resource_set["id"]:
                resource_set["created_at"] = existing.get("created_at") or now
                sets[index] = resource_set
                replaced = True
                break
        if not replaced:
            sets.append(resource_set)
        project.metadata["lesson_resource_sets"] = sets
        if resource_set.get("active"):
            project.metadata["active_lesson_resource_set_id"] = resource_set["id"]
            for item in sets:
                item["active"] = item["id"] == resource_set["id"]
        self.store.save_project(project)
        return {"status": "success", "item": resource_set, "items": sets}

    def activate_lesson_resource_set(self, project_id: str, set_id: str, patch: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        project = self._require_project(project_id)
        sets = self._lesson_resource_sets(project.project_id, project.metadata)
        if not any(item.get("id") == set_id for item in sets):
            raise KeyError(f"Unknown lesson resource set: {set_id}")
        patch = patch or {}
        for item in sets:
            if item.get("id") != set_id:
                item["active"] = False
                continue
            if patch:
                item.update({key: value for key, value in patch.items() if key in {"title", "item_ids", "material_ids", "region_bindings"}})
            item["active"] = bool(patch.get("active", True))
            item["updated_at"] = self.store_timestamp()
            if item["active"]:
                project.metadata["active_lesson_resource_set_id"] = set_id
        if patch.get("active") is False:
            project.metadata["active_lesson_resource_set_id"] = ""
        project.metadata["lesson_resource_sets"] = sets
        self.store.save_project(project)
        return {"status": "success", "items": sets, "active_lesson_resource_set_id": project.metadata.get("active_lesson_resource_set_id", "")}

    # ------------------------------------------------------------------
    # Timeline
    # ------------------------------------------------------------------

    def generate_timeline(self, project_id: str, filename: str, raw_bytes: bytes) -> Dict[str, Any]:
        project = self._require_project(project_id)
        result = self.timeline_service.generate_timeline(filename, raw_bytes, project_id)
        timeline = result["timeline"]
        project.metadata["timeline"] = timeline
        self.store.save_project(project)
        return result

    def get_timeline(self, project_id: str) -> Dict[str, Any]:
        project = self._require_project(project_id)
        timeline = project.metadata.get("timeline")
        if not timeline:
            return {"status": "empty", "timeline": None}
        return {"status": "success", "timeline": timeline}

    def update_timeline(self, project_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
        project = self._require_project(project_id)
        timeline = project.metadata.get("timeline")
        if not timeline:
            raise KeyError("No timeline exists for this project")

        if "active_node_id" in patch:
            for node in timeline["nodes"]:
                node["active"] = node["id"] == patch["active_node_id"]

        if "nodes" in patch:
            timeline["nodes"] = patch["nodes"]

        if "title" in patch:
            timeline["title"] = patch["title"]

        timeline["updated_at"] = datetime.now(timezone.utc).isoformat()
        project.metadata["timeline"] = timeline
        self.store.save_project(project)
        return {"status": "success", "timeline": timeline}

    def llm_status(self) -> Dict[str, Any]:
        return {"status": "success", **self.minimax_client.status()}

    def list_basemaps(self) -> Dict[str, Any]:
        return {"status": "success", **self.config.basemap_catalog()}

    def fetch_weather_tile(self, layer: str, z: int, x: int, y: int) -> tuple[bytes, str]:
        if not self.config.weather_basemap_enabled():
            return TRANSPARENT_PNG, "image/png"
        request = urllib.request.Request(
            self.config.weather_tile_upstream_url(layer, z, x, y),
            headers={"User-Agent": "WebGIS-AI/1.1"},
        )
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                content_type = response.headers.get_content_type() or "image/png"
                return response.read(), content_type
        except urllib.error.HTTPError as exc:
            raise ConnectionError(f"Weather tile upstream returned HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise ConnectionError(f"Weather tile upstream is unavailable: {exc.reason}") from exc

    def create_project(
        self,
        name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        owner_user_id: str = "",
    ) -> Dict[str, Any]:
        project = self.store.create_project(
            name=name,
            owner_user_id=owner_user_id,
            metadata=metadata,
            base_map=self.config.default_basemap(),
        )
        return {"status": "success", **project.to_dict()}

    @staticmethod
    def _project_payload(project: ProjectRecord) -> Dict[str, Any]:
        payload = project.to_dict()
        # Layer GeoJSON is served by /layers; omitting it here keeps the
        # project payload small (layers can hold multi-MB collections).
        for layer in payload.get("layers", []):
            layer["data"] = {}
        return payload

    def list_projects(self, owner_user_id: str = "", include_all: bool = False) -> Dict[str, Any]:
        projects = sorted(self.store.projects.values(), key=lambda project: project.updated_at, reverse=True)
        if owner_user_id and not include_all:
            projects = [project for project in projects if project.owner_user_id == owner_user_id]
        return {
            "status": "success",
            "items": [self._project_payload(project) for project in projects],
        }

    def get_project(self, project_id: str) -> Dict[str, Any]:
        project = self._require_project(project_id)
        return {"status": "success", **self._project_payload(project)}

    def list_layers(self, project_id: str) -> Dict[str, Any]:
        project = self._require_project(project_id)
        layers = sorted(project.layers, key=lambda layer: layer.z_index)
        return {
            "status": "success",
            "items": [layer.to_dict() for layer in layers],
            "active_layer_id": project.active_layer_id,
            "view": project.view,
            "enabled_templates": project.enabled_templates,
            "recent_actions": project.recent_actions,
            "base_map": project.base_map,
        }

    def patch_layer(self, project_id: str, layer_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
        layer = self.store.patch_layer(project_id, layer_id, patch)
        if patch.get("active"):
            self.store.set_active_layer(project_id, layer_id)
        self.store.add_recent_action(
            project_id,
            "更新图层样式",
            f"已更新图层“{layer.name}”",
            status="success",
            metadata={"layer_id": layer.layer_id},
        )
        return {"status": "success", "item": layer.to_dict()}

    def delete_layer(self, project_id: str, layer_id: str) -> Dict[str, Any]:
        layer = self.store.delete_layer(project_id, layer_id)
        self.store.add_recent_action(
            project_id,
            "删除图层",
            f"已删除图层“{layer.name}”",
            status="success",
            metadata={"layer_id": layer.layer_id},
        )
        return {"status": "success", "item": layer.to_dict()}

    def set_basemap(self, project_id: str, basemap_id: str) -> Dict[str, Any]:
        self._require_project(project_id)
        base_map = self.config.basemap_by_id(basemap_id)
        updated = self.store.set_basemap(project_id, base_map)
        self.store.add_recent_action(
            project_id,
            "切换底图",
            f"已切换到“{updated.get('title', basemap_id)}”",
            status="success",
            metadata={"basemap_id": basemap_id},
        )
        return {"status": "success", "base_map": updated}

    def search_poi(
        self,
        project_id: str,
        keyword: str,
        mode: str = "view",
        extent: Optional[List[float]] = None,
        geometry: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        self._require_project(project_id)
        return self.poi_service.search(project_id=project_id, keyword=keyword, mode=mode, extent=extent, geometry=geometry)

    def upload_dataset(
        self,
        project_id: str,
        filename: str,
        raw_bytes: bytes,
        dataset_name: str = "",
        lat_field: str = "",
        lon_field: str = "",
        image_bounds: Optional[List[float]] = None,
    ) -> Dict[str, Any]:
        job = self.store.create_job(
            project_id=project_id,
            job_type="dataset_upload",
            title=f"导入 {filename}",
            workflow_type="dataset_upload",
            request={"filename": filename},
            stages=build_workflow_stages(),
        )
        try:
            self.store.set_job_status(job.job_id, "running")
            self.store.update_job_stage(job.job_id, "analysis", "running", "正在识别数据类型。")
            result = self.dataset_service.import_upload(
                project_id=project_id,
                filename=filename,
                raw_bytes=raw_bytes,
                dataset_name=dataset_name,
                lat_field=lat_field,
                lon_field=lon_field,
                image_bounds=image_bounds,
            )
            self.store.update_job_stage(job.job_id, "analysis", "success", "数据类型识别完成。")
            self.store.update_job_stage(job.job_id, "map", "success", "图层已写入项目。")
            artifact = result["artifact"]
            registered_artifact = self.store.register_artifact(
                project_id=project_id,
                job_id=job.job_id,
                artifact_type=artifact["artifact_type"],
                title=artifact["title"],
                path=artifact["path"],
                metadata=artifact["metadata"],
            )
            self.store.update_job_stage(job.job_id, "artifacts", "success", "数据导入记录已保存。")
            self.store.set_job_status(
                job.job_id,
                "completed",
                result={
                    "status": "success",
                    "workflow_type": "dataset_upload",
                    "summary": f"已导入 {result['layer']['name']}",
                    "assistant_message": f"数据集 {result['layer']['name']} 已进入当前课堂项目。",
                    "artifacts": {registered_artifact.artifact_id: registered_artifact.to_dict()},
                    "layer": result["layer"],
                    "stages": self.store.get_job(job.job_id).stages,
                },
            )
            return {"status": "success", "job_id": job.job_id, **result}
        except Exception as exc:
            self._fail_job(job.job_id, "dataset_upload", str(exc))
            raise

    def submit_template(self, project_id: str, template_id: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        job = self.store.create_job(
            project_id=project_id,
            job_type="template",
            title=f"应用模板 {template_id}",
            workflow_type="template_run",
            request={"template_id": template_id, "payload": payload or {}},
        )
        threading.Thread(
            target=self._run_template_job,
            args=(job.job_id, project_id, template_id, payload or {}),
            daemon=True,
        ).start()
        return {"status": "accepted", "job_id": job.job_id, "project_id": project_id}

    def submit_assistant_message(
        self,
        project_id: str,
        message: str,
        map_context: Optional[Dict[str, Any]] = None,
        assistant_mode: str = "teaching",
        conversation_id: str = "",
        history: Optional[List[Dict[str, Any]]] = None,
        target: str = "webgis",
        input_mode: str = "text",
        screen_snapshot: Optional[Dict[str, Any]] = None,
        teaching_context: Optional[Dict[str, Any]] = None,
        image_attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        # Heavy GIS work moved to /workflow/*; assistant actions are WebGIS-only.
        normalized_target = "webgis"
        normalized_input_mode = input_mode if input_mode in {"text", "voice"} else "text"
        normalized_mode = assistant_mode if assistant_mode in {"teaching", "knowledge", "tool", "interaction"} else "teaching"
        resolved_attachments = self.resolve_image_attachments(project_id, image_attachments or [])
        use_v2 = (
            self.config.assistant_v2_enabled
            or normalized_mode == "teaching"
            or normalized_mode == "interaction"
            or assistant_mode == "knowledge"
            or bool(conversation_id)
            or bool(history)
            or bool(resolved_attachments)
        )
        job = self.store.create_job(
            project_id=project_id,
            job_type="assistant",
            title="课堂助教请求",
            workflow_type="assistant_message",
            request={
                "message": message,
                "map_context": map_context or {},
                "assistant_mode": normalized_mode,
                "conversation_id": conversation_id,
                "history": history or [],
                "target": normalized_target,
                "input_mode": normalized_input_mode,
                "screen_snapshot": screen_snapshot or {},
                "teaching_context": teaching_context or {},
                "image_attachments": image_attachments or [],
            },
            stages=build_assistant_v2_stages() if use_v2 else build_workflow_stages(),
        )
        if use_v2:
            threading.Thread(
                target=self._run_assistant_v2_job,
                args=(
                    job.job_id,
                    project_id,
                    message,
                    map_context or {},
                    normalized_mode,
                    conversation_id,
                    history or [],
                    normalized_target,
                    normalized_input_mode,
                    screen_snapshot or {},
                    teaching_context or {},
                    resolved_attachments,
                ),
                daemon=True,
            ).start()
        else:
            threading.Thread(
                target=self._run_assistant_job,
                args=(job.job_id, project_id, message, map_context or {}, normalized_target, normalized_input_mode, screen_snapshot or {}),
                daemon=True,
            ).start()
        return {
            "status": "accepted",
            "job_id": job.job_id,
            "project_id": project_id,
            "conversation_id": conversation_id,
            "assistant_mode": normalized_mode,
        }

    def confirm_assistant_action(self, confirmation_id: str, decision: str = "approve") -> Dict[str, Any]:
        confirmation = self.store.get_confirmation(confirmation_id)
        if confirmation is None:
            raise KeyError(f"Unknown confirmation: {confirmation_id}")
        normalized_decision = "reject" if str(decision).strip().lower() == "reject" else "approve"
        job = self.store.create_job(
            project_id=confirmation.project_id,
            job_type="assistant_confirmation",
            title=confirmation.title or ("Reject assistant action" if normalized_decision == "reject" else "Confirm assistant action"),
            workflow_type="assistant_confirmation",
            request={"confirmation_id": confirmation_id, "conversation_id": confirmation.conversation_id, "decision": normalized_decision},
            stages=build_assistant_v2_stages(),
        )
        threading.Thread(target=self._run_confirmation_job, args=(job.job_id, confirmation_id, normalized_decision), daemon=True).start()
        return {
            "status": "accepted",
            "job_id": job.job_id,
            "project_id": confirmation.project_id,
            "conversation_id": confirmation.conversation_id,
            "confirmation_id": confirmation_id,
            "decision": normalized_decision,
        }

    def get_conversation(self, conversation_id: str) -> Dict[str, Any]:
        conversation = self.store.get_conversation(conversation_id)
        if conversation is None:
            raise KeyError(f"Unknown conversation: {conversation_id}")
        messages = [item.to_dict() for item in self.store.list_conversation_messages(conversation_id)]
        return {"status": "success", **conversation.to_dict(), "messages": messages}

    def upload_image_asset(
        self,
        project_id: str,
        filename: str,
        raw_bytes: bytes,
        title: str = "",
    ) -> Dict[str, Any]:
        self._require_project(project_id)
        if not raw_bytes:
            raise ValueError("图片文件为空。")
        if len(raw_bytes) > MAX_IMAGE_LIBRARY_BYTES:
            raise ValueError("图片不能超过 20MB。")
        detected_mime = _detect_image_mime(raw_bytes)
        if not detected_mime:
            raise ValueError("仅支持 JPEG、PNG、WebP 或 GIF 图片。")

        original_suffix = Path(filename or "").suffix.lower()
        expected_mime = SUPPORTED_IMAGE_MIME_BY_SUFFIX.get(original_suffix)
        if expected_mime and expected_mime != detected_mime:
            raise ValueError("图片扩展名与实际文件格式不一致。")
        suffix = original_suffix if expected_mime else next(
            key for key, value in SUPPORTED_IMAGE_MIME_BY_SUFFIX.items() if value == detected_mime
        )
        safe_stem = _safe_id(Path(filename or "uploaded_image").stem)[:80]
        output_dir = self.config.project_upload_dir(project_id) / "image_library"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.config.unique_path(output_dir, f"{safe_stem}{suffix}")

        job = self.store.create_job(
            project_id=project_id,
            job_type="image_upload",
            title=title.strip() or Path(filename or "图片").stem or "图片",
            workflow_type="image_library_upload",
            request={"filename": filename, "size": len(raw_bytes)},
        )
        try:
            self.store.set_job_status(job.job_id, "running")
            self.store.update_job_stage(job.job_id, "artifacts", "running", "正在保存图片。")
            output_path.write_bytes(raw_bytes)
            public_url = self.config.public_url_for_path(output_path)
            artifact = self.store.register_artifact(
                project_id=project_id,
                job_id=job.job_id,
                artifact_type="uploaded_image",
                title=title.strip() or Path(filename or "图片").stem or "图片",
                path=str(output_path),
                metadata={
                    "public_url": public_url,
                    "mime_type": detected_mime,
                    "source": "upload",
                    "original_filename": filename,
                    "size": len(raw_bytes),
                },
            )
            self.store.update_job_stage(job.job_id, "artifacts", "success", "图片已保存到图片库。")
            self.store.set_job_status(
                job.job_id,
                "completed",
                result={"status": "success", "artifact": artifact.to_dict()},
            )
            return {"status": "success", "job_id": job.job_id, "artifact": artifact.to_dict()}
        except Exception as exc:
            self._fail_job(job.job_id, "image_library_upload", str(exc))
            raise

    def generate_image_asset(
        self,
        project_id: str,
        prompt: str,
        title: str = "",
        model: str = "",
        aspect_ratio: str = "16:9",
        prompt_optimizer: bool = True,
    ) -> Dict[str, Any]:
        self._require_project(project_id)
        normalized_prompt = str(prompt or "").strip()
        job = self.store.create_job(
            project_id=project_id,
            job_type="image_generation",
            title=title.strip() or "AI生成示意图",
            workflow_type="image_generation",
            request={
                "prompt": normalized_prompt,
                "model": model or self.config.minimax_image_model,
                "aspect_ratio": aspect_ratio,
                "prompt_optimizer": bool(prompt_optimizer),
            },
        )
        output_path: Optional[Path] = None
        artifact_registered = False
        try:
            self.store.set_job_status(job.job_id, "running")
            self.store.update_job_stage(job.job_id, "artifacts", "running", "正在调用 MiniMax 生成图片。")
            generated = self.image_generation_service.generate(
                normalized_prompt,
                model=model,
                aspect_ratio=aspect_ratio,
                prompt_optimizer=prompt_optimizer,
            )
            raw_bytes = generated["raw_bytes"]
            if not raw_bytes or len(raw_bytes) > MAX_IMAGE_LIBRARY_BYTES:
                raise ValueError("生成图片为空或超过 20MB，未保存到项目图片库。")

            output_dir = self.config.project_output_dir(project_id) / "generated_images"
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"ai_image_{job.job_id}{generated['suffix']}"
            output_path.write_bytes(raw_bytes)
            artifact = self.store.register_artifact(
                project_id=project_id,
                job_id=job.job_id,
                artifact_type="generated_image",
                title=title.strip() or "AI生成示意图",
                path=str(output_path),
                metadata={
                    "public_url": self.config.public_url_for_path(output_path),
                    "mime_type": generated["mime_type"],
                    "source": "minimax_image_generation",
                    "size": len(raw_bytes),
                    "prompt": normalized_prompt,
                    "model": generated["model"],
                    "aspect_ratio": generated["aspect_ratio"],
                    "request_id": generated["request_id"],
                    "ai_generated": True,
                    "aigc_watermark": True,
                },
            )
            artifact_registered = True
            self.store.add_recent_action(project_id, "AI生成图片", artifact.title, status="success")
            self.store.update_job_stage(job.job_id, "artifacts", "success", "图片已保存到项目图片库。")
            self.store.set_job_status(
                job.job_id,
                "completed",
                result={"status": "success", "artifact": artifact.to_dict()},
            )
            return {"status": "success", "job_id": job.job_id, "artifact": artifact.to_dict()}
        except Exception as exc:
            if output_path is not None and not artifact_registered and output_path.exists():
                try:
                    output_path.unlink()
                except OSError:
                    pass
            self._fail_job(job.job_id, "image_generation", str(exc))
            raise

    def resolve_image_attachments(
        self,
        project_id: str,
        attachments: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if len(attachments) > 1:
            raise ValueError("每条消息暂时只能附加一张图片。")
        resolved: List[Dict[str, Any]] = []
        for item in attachments:
            artifact_id = str(item.get("artifact_id") or "").strip()
            if not artifact_id:
                raise ValueError("图片附件缺少 artifact_id。")
            artifact = self.store.get_artifact(artifact_id)
            if artifact is None:
                raise KeyError(f"Unknown artifact: {artifact_id}")
            if artifact.project_id != project_id:
                raise ValueError("不能使用其他项目的图片。")
            if artifact.artifact_type not in {"map_snapshot", "uploaded_image", "generated_image"}:
                raise ValueError("该产物不是可识别的图片。")
            path = Path(artifact.path).resolve()
            allowed_roots = (self.config.uploads_dir.resolve(), self.config.outputs_dir.resolve())
            if not any(_is_relative_to(path, root) for root in allowed_roots):
                raise ValueError("图片路径不在允许的项目目录中。")
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_IMAGE_MIME_BY_SUFFIX:
                raise ValueError("图片文件不存在或格式不受支持。")
            detected_mime = _detect_image_mime(path.read_bytes()[:32])
            expected_mime = SUPPORTED_IMAGE_MIME_BY_SUFFIX[path.suffix.lower()]
            if not detected_mime or detected_mime != expected_mime:
                raise ValueError("图片文件内容与格式不一致。")
            resolved.append(
                {
                    "artifact_id": artifact.artifact_id,
                    "title": artifact.title,
                    "path": str(path),
                    "public_url": str(artifact.metadata.get("public_url") or self.config.public_url_for_path(path)),
                    "mime_type": str(
                        artifact.metadata.get("mime_type")
                        or SUPPORTED_IMAGE_MIME_BY_SUFFIX.get(path.suffix.lower(), "")
                    ),
                }
            )
        return resolved

    def export_snapshot(
        self,
        project_id: str,
        title: str,
        image_data_url: str,
        note: str = "",
    ) -> Dict[str, Any]:
        job = self.store.create_job(
            project_id=project_id,
            job_type="export",
            title=title or "课堂导图",
            workflow_type="export_snapshot",
            request={"title": title, "note": note},
        )
        try:
            self.store.set_job_status(job.job_id, "running")
            self.store.update_job_stage(job.job_id, "artifacts", "running", "正在保存课堂截图。")
            if "," not in image_data_url:
                raise ValueError("Snapshot export requires a valid data URL")
            prefix, encoded = image_data_url.split(",", 1)
            if ";base64" not in prefix:
                raise ValueError("Snapshot export requires a base64 data URL")
            raw = base64.b64decode(encoded.encode("utf-8"))
            if len(raw) > MAX_IMAGE_LIBRARY_BYTES:
                raise ValueError("截图不能超过 20MB。")
            if _detect_image_mime(raw) != "image/png" or not prefix.lower().startswith("data:image/png"):
                raise ValueError("截图必须是有效的 PNG 图片。")
            output_path = self.config.project_output_dir(project_id) / f"snapshot_{job.job_id}.png"
            output_path.write_bytes(raw)
            artifact = self.store.register_artifact(
                project_id=project_id,
                job_id=job.job_id,
                artifact_type="map_snapshot",
                title=title or "课堂导图",
                path=str(output_path),
                metadata={
                    "public_url": self.config.public_url_for_path(output_path),
                    "note": note,
                    "mime_type": "image/png",
                    "source": "screenshot",
                    "size": len(raw),
                },
            )
            self.store.add_recent_action(project_id, "导出课堂截图", title or "课堂导图", status="success")
            self.store.update_job_stage(job.job_id, "artifacts", "success", "课堂截图已保存。")
            self.store.set_job_status(
                job.job_id,
                "completed",
                result={
                    "status": "success",
                    "workflow_type": "export_snapshot",
                    "summary": f"已导出 {title or '课堂导图'}",
                    "assistant_message": "当前课堂画面已保存为本地截图。",
                    "artifacts": {artifact.artifact_id: artifact.to_dict()},
                    "stages": self.store.get_job(job.job_id).stages,
                },
            )
            return {"status": "success", "job_id": job.job_id, "artifact": artifact.to_dict()}
        except Exception as exc:
            self._fail_job(job.job_id, "export_snapshot", str(exc))
            raise

    def get_job(self, job_id: str) -> Dict[str, Any]:
        job = self.store.get_job(job_id)
        if not job:
            raise KeyError(f"Unknown job: {job_id}")
        return job.to_dict()

    def get_artifact(self, artifact_id: str) -> Dict[str, Any]:
        artifact = self.store.get_artifact(artifact_id)
        if not artifact:
            raise KeyError(f"Unknown artifact: {artifact_id}")
        return {"status": "success", **artifact.to_dict()}

    def list_outputs(self, project_id: Optional[str] = None) -> Dict[str, Any]:
        teacher_facing = {"map_snapshot", "uploaded_image", "generated_image", "annotation_export", "dataset_import", "assistant_note", "query_summary"}
        items = [item for item in self.store.list_outputs(project_id=project_id) if item.get("artifact_type") in teacher_facing]
        return {"status": "success", "items": items}

    def list_dataset_catalog(self) -> Dict[str, Any]:
        return self.one_map_catalog_service.list_catalog()

    def get_catalog_dataset_data(self, dataset_id: str) -> Dict[str, Any]:
        """Return a catalog dataset as a FeatureCollection without persisting
        anything to the runtime store — used by client-side visualizations
        (e.g. the 3D globe thematic layers) that only need read access."""
        item = self.one_map_catalog_service.get_item(dataset_id)
        item_format = item.get("format", "").lower()
        if item_format == "geojson":
            payload = self._read_geojson_catalog_payload(item)
        elif item_format == "csv":
            payload = self._materialize_csv_catalog_payload(item)
        else:
            raise ValueError(f"Catalog dataset format cannot be served as GeoJSON: {item_format or 'unknown'}")
        return {"status": "success", "dataset": item, "data": payload}

    def _read_geojson_catalog_payload(self, item: Dict[str, Any]) -> Dict[str, Any]:
        path = self.one_map_catalog_service.resolve_item_path(item)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Catalog dataset is not valid GeoJSON: {item.get('id')}") from exc
        if payload.get("type") != "FeatureCollection" or not isinstance(payload.get("features"), list):
            raise ValueError(f"Catalog dataset must be a GeoJSON FeatureCollection: {item.get('id')}")
        return json.loads(json.dumps(payload, ensure_ascii=False))

    def _materialize_csv_catalog_payload(self, item: Dict[str, Any]) -> Dict[str, Any]:
        join_defaults = CSV_JOIN_DEFAULTS.get(str(item.get("id") or ""))
        join_key = str(item.get("join_key") or (join_defaults or {}).get("join_key") or "").strip()
        geometry_source = str(item.get("geometry_source") or (join_defaults or {}).get("geometry_source") or "").strip()
        if not join_key or not geometry_source:
            raise ValueError(
                f"Catalog CSV dataset cannot be loaded as a layer without geometry_source and join_key: {item.get('id')}"
            )

        csv_path = self.one_map_catalog_service.resolve_item_path(item)
        rows_by_key: Dict[str, Dict[str, Any]] = {}
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or join_key not in reader.fieldnames:
                raise ValueError(f"Catalog CSV dataset is missing join key '{join_key}': {item.get('id')}")
            for raw_row in reader:
                key = _normalize_join_value(raw_row.get(join_key))
                if not key:
                    continue
                rows_by_key[key] = {field: _coerce_catalog_value(value) for field, value in raw_row.items()}
        if not rows_by_key:
            raise ValueError(f"Catalog CSV dataset has no joinable rows: {item.get('id')}")

        geometry_item = self.one_map_catalog_service.get_item(geometry_source)
        if geometry_item.get("format", "").lower() != "geojson":
            raise ValueError(f"Catalog geometry_source must point to a GeoJSON dataset: {geometry_source}")
        payload = self._read_geojson_catalog_payload(geometry_item)
        joined_features: List[Dict[str, Any]] = []
        for feature in payload.get("features", []):
            if not isinstance(feature, dict):
                continue
            props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
            row = rows_by_key.get(_normalize_join_value(props.get(join_key)))
            if not row:
                continue
            next_feature = json.loads(json.dumps(feature, ensure_ascii=False))
            next_props = next_feature.setdefault("properties", {})
            next_props.update(row)
            next_props.setdefault("geometry_source_id", geometry_item["id"])
            joined_features.append(next_feature)

        if not joined_features:
            raise ValueError(
                f"Catalog CSV dataset did not match any geometry features using '{join_key}': {item.get('id')}"
            )
        payload["features"] = joined_features
        return payload

    def materialize_catalog_layer(self, project_id: str, dataset_id: str) -> LayerRecord:
        """Materialize a one-map catalog dataset as a project vector layer.

        Shared by the manual ``add_catalog_dataset_layer`` endpoint and by
        lesson stage scenes that declaratively open catalog layers via
        ``scene.catalog_layers``.  Only writes the layer itself - no view,
        active-layer or recent-action side effects - so a scene apply can
        compose several catalog layers and then set its own view/visibility.
        """
        project = self._require_project(project_id)
        item = self.one_map_catalog_service.get_item(dataset_id)
        item_format = item.get("format", "").lower()
        materialized_from_csv = False
        if item_format == "geojson":
            payload = self._read_geojson_catalog_payload(item)
        elif item_format == "csv":
            payload = self._materialize_csv_catalog_payload(item)
            materialized_from_csv = True
        else:
            raise ValueError(f"Catalog dataset format cannot be loaded as a map layer: {item_format or 'unknown'}")

        features = [feature for feature in payload.get("features", []) if isinstance(feature, dict)]
        geometry_type = item.get("geometry_type") or _first_geometry_type(payload)
        if not geometry_type and features:
            geometry_type = _first_geometry_type(payload)
        numeric_candidates = [
            "density",
            "population",
            "gdp_per_capita_2020",
            "population_2020",
            "area",
            "area_km2",
        ]
        catalog_fields = set(item.get("fields") or [])
        style_field = str(item.get("style_field") or "") or next((field for field in numeric_candidates if field in catalog_fields), "")
        if style_field:
            _classify_colors(features, style_field)
        else:
            _decorate_default_style(features, geometry_type)

        project = self._require_project(project_id)
        layer_id = f"one_map_{_safe_id(item['id'])}"
        z_index = max([layer.z_index for layer in project.layers], default=30) + 10
        layer = LayerRecord.create(
            layer_id=layer_id,
            name=item.get("name") or item["id"],
            kind="vector",
            source="one_map_catalog",
            geometry_type=geometry_type,
            opacity=0.86,
            z_index=z_index,
            style={"labelField": "name"},
            data=payload,
            metadata={
                "catalog_id": item["id"],
                "catalog_source": item["source"],
                "category": item.get("category", ""),
                "coverage": item.get("coverage", ""),
                "source_name": item.get("source_name", ""),
                "source_year": item.get("source_year", ""),
                "source_url": item.get("source_url", ""),
                "license": item.get("license", ""),
                "status": item.get("status", ""),
                "fields": item.get("fields", []),
                "includes_taiwan": item.get("includes_taiwan", False),
                "style_field": style_field,
                "materialized_from_csv": materialized_from_csv,
                "join_key": item.get("join_key", ""),
                "geometry_source": item.get("geometry_source", ""),
                "description": item.get("description", ""),
            },
        )
        self.store.upsert_layer(project_id, layer)
        return layer

    def add_catalog_dataset_layer(self, project_id: str, dataset_id: str) -> Dict[str, Any]:
        layer = self.materialize_catalog_layer(project_id, dataset_id)
        self.store.set_active_layer(project_id, layer.layer_id)

        bounds = _geojson_bounds(layer.data or {})
        width = max(0.0, bounds[2] - bounds[0])
        height = max(0.0, bounds[3] - bounds[1])
        zoom = 2 if width > 120 or height > 70 else 4 if width > 35 or height > 25 else 7 if width > 5 else 10
        view = self.store.set_view(project_id, {"center": _bounds_center(bounds), "zoom": zoom, "extent": bounds})
        self.store.add_recent_action(
            project_id,
            "加载一张图数据",
            f"已加载“{layer.name}”到底图。",
            status="success",
            metadata={"layer_id": layer.layer_id, "catalog_id": (layer.metadata or {}).get("catalog_id", "")},
        )
        return {"status": "success", "layer": layer.to_dict(), "view": view}

    def summarize_catalog_layers(
        self,
        project_id: str,
        geometry: Optional[Dict[str, Any]] = None,
        layer_id: str = "",
    ) -> Dict[str, Any]:
        project = self._require_project(project_id)
        geometry = geometry or None
        candidates = [
            layer
            for layer in project.layers
            if layer.kind == "vector"
            and layer.source == "one_map_catalog"
            and (not layer_id or layer.layer_id == layer_id)
            and (layer.visible or layer_id)
        ]
        if layer_id and not candidates:
            raise KeyError(f"Unknown or unavailable one-map layer: {layer_id}")

        layer_summaries: List[Dict[str, Any]] = []
        total_population = 0.0
        total_area = 0.0
        total_matched = 0

        for layer in candidates:
            data = layer.data if isinstance(layer.data, dict) else {}
            features = data.get("features", [])
            if not isinstance(features, list):
                continue

            rows: List[Dict[str, Any]] = []
            layer_population = 0.0
            layer_area = 0.0
            matched_count = 0
            has_population_value = False
            has_area_value = False

            for index, feature in enumerate(features):
                if not isinstance(feature, dict):
                    continue
                props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
                source_population = _as_number(props.get("population") or props.get("population_2020") or props.get("pop_max"))
                source_area = _as_number(props.get("area") or props.get("area_km2"))
                source_density = _as_number(props.get("density"))
                coverage_ratio = 1.0
                geometry_stats = _shape_area_stats(feature.get("geometry"), geometry)
                if geometry_stats is not None:
                    coverage_ratio = geometry_stats["ratio"]
                    if coverage_ratio <= 0:
                        continue
                    computed_area = geometry_stats["area_km2"]
                    area = source_area * coverage_ratio if source_area is not None else computed_area
                else:
                    point = _feature_point(feature)
                    if point is None or not _point_in_selection(point, geometry):
                        continue
                    area = source_area

                population = source_population * coverage_ratio if source_population is not None else None
                density = population / area if population is not None and area and area > 0 else source_density
                matched_count += 1
                if population is not None:
                    layer_population += population
                    has_population_value = True
                if area is not None:
                    layer_area += area
                    has_area_value = True
                rows.append(
                    {
                        "name": str(props.get("name") or props.get("city") or props.get("name_en") or f"feature_{index + 1}"),
                        "region_code": str(props.get("adcode") or props.get("region_code") or props.get("iso3") or ""),
                        "population": round(population, 2) if population is not None else None,
                        "area": round(area, 2) if area is not None else None,
                        "density": round(density, 4) if density is not None else None,
                        "coverage_ratio": round(coverage_ratio, 6),
                        "source_population": source_population,
                        "source_area": source_area,
                        "estimated": coverage_ratio < 0.999999,
                    }
                )

            computed_density = layer_population / layer_area if layer_area > 0 and has_population_value else None
            if has_population_value:
                total_population += layer_population
            if has_area_value:
                total_area += layer_area
            total_matched += matched_count
            layer_summaries.append(
                {
                    "layer_id": layer.layer_id,
                    "name": layer.name,
                    "catalog_id": str(layer.metadata.get("catalog_id", "")),
                    "feature_count": len(features),
                    "matched_count": matched_count,
                    "total_population": round(layer_population, 2) if has_population_value else None,
                    "total_area": round(layer_area, 2) if has_area_value else None,
                    "density": round(computed_density, 4) if computed_density is not None else None,
                    "rows": rows[:80],
                    "method": "area_weighted_intersection",
                }
            )

        overall_density = total_population / total_area if total_area > 0 and total_population > 0 else None
        summary = (
            f"已统计 {len(layer_summaries)} 个一张图图层，命中 {total_matched} 个要素。"
            if layer_summaries
            else "当前没有可统计的一张图图层，请先从数据库加载 GeoJSON 数据。"
        )
        return {
            "status": "success",
            "summary": summary,
            "geometry_used": bool(geometry),
            "layers": layer_summaries,
            "totals": {
                "matched_count": total_matched,
                "total_population": round(total_population, 2) if total_population else None,
                "total_area": round(total_area, 2) if total_area else None,
                "density": round(overall_density, 4) if overall_density is not None else None,
            },
        }

    # ------------------------------------------------------------------
    # GIS workflow API helpers. PyQGIS is the backend worker implementation.
    # ------------------------------------------------------------------

    def list_workflow_templates(self) -> Dict[str, Any]:
        return {"status": "success", "items": list_templates()}

    def submit_workflow(
        self,
        project_id: str,
        message: str,
        mode: str = "template",
        template_id: str = "",
        parameters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build a workflow JSON from a template (or accept caller-built JSON)
        and hand it off to :class:`WorkflowExecutor`."""
        params = dict(parameters or {})
        params.setdefault("project_id", project_id)
        chosen_template = template_id or detect_template(message) or "population_choropleth"
        try:
            match = expand_template(chosen_template, message, params)
        except KeyError as exc:
            raise KeyError(f"Unknown workflow template: {chosen_template}") from exc

        workflow_record = WorkflowRecord.create(
            project_id=project_id,
            user_message=message,
            intent=match.intent,
            template_id=match.template_id,
            mode=mode,
            workflow_json=match.workflow,
        )
        workflow_record, _validation = self.workflow_executor.submit(workflow_record)
        return {
            "status": "success" if workflow_record.status != "error" else "error",
            "workflow_id": workflow_record.workflow_id,
            "workflow_status": workflow_record.status,
            "intent": workflow_record.intent,
            "template_id": match.template_id,
            "parameters": match.parameters,
            "error": workflow_record.error,
        }

    def get_workflow(self, workflow_id: str) -> Dict[str, Any]:
        record = self.store.get_workflow(workflow_id)
        if record is None:
            raise KeyError(f"Unknown workflow: {workflow_id}")
        return {"status": "success", **record.to_dict()}

    def list_workflow_artifacts(self, workflow_id: str) -> Dict[str, Any]:
        record = self.store.get_workflow(workflow_id)
        if record is None:
            raise KeyError(f"Unknown workflow: {workflow_id}")
        return {
            "status": "success",
            "workflow_id": workflow_id,
            "artifacts": list(record.artifacts),
        }

    def list_workflows(self, project_id: Optional[str] = None) -> Dict[str, Any]:
        return {"status": "success", "items": self.store.list_workflows(project_id=project_id)}

    def stream_workflow_events(self, workflow_id: str):
        return self.workflow_executor.stream(workflow_id)

    def workflow_init_warning(self) -> Optional[Dict[str, Any]]:
        return self.workflow_executor.init_warning()

    def resolve_workflow_file(self, workflow_id: str, relative: str) -> Path:
        """Resolve a workflow-relative file for the /workflow-files endpoint."""
        return self.config.resolve_workflow_path(workflow_id, relative)

    def _generate_workflow_summary(
        self,
        record: WorkflowRecord,
        outputs_by_step: Dict[str, Any],
    ) -> str:
        """Optional summary generator. Reads stats.json if present and asks
        MiniMax for a brief Chinese explanation suitable for classroom use.

        On any failure returns an empty string so the workflow result still
        ships even without the LLM."""
        stats_path: Optional[Path] = None
        for state_id, outputs in outputs_by_step.items():
            stats_value = outputs.get("stats") if isinstance(outputs, dict) else None
            if isinstance(stats_value, str) and stats_value:
                stats_path = Path(stats_value)
                break
        stats_payload: Dict[str, Any] = {}
        if stats_path and stats_path.exists():
            try:
                stats_payload = json.loads(stats_path.read_text(encoding="utf-8"))
            except Exception:
                stats_payload = {}
        if not stats_payload and not record.intent:
            return ""

        if not self.config.minimax_enabled():
            return _fallback_summary(record, stats_payload)

        try:
            user_payload = json.dumps(stats_payload, ensure_ascii=False)[:4000]
            messages = [
                {
                    "role": "system",
                    "content": (
                        "你是一名高中地理教师，擅长用 100-180 字概括 GIS 分析结果。"
                        "请输出 Markdown 格式的解释，不要使用代码块，不要输出 JSON。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"任务意图：{record.intent}\n"
                        f"原始需求：{record.user_message}\n"
                        f"统计 JSON：\n{user_payload}"
                    ),
                },
            ]
            content = self.minimax_client.chat_completion(messages, temperature=0.4)
            return content.strip()
        except Exception:
            return _fallback_summary(record, stats_payload)

    def _run_template_job(self, job_id: str, project_id: str, template_id: str, payload: Dict[str, Any]) -> None:
        try:
            self.store.set_job_status(job_id, "running")
            self.store.append_job_step(job_id, "开始处理模板", f"正在应用模板 {template_id}", "running")
            self.store.update_job_stage(job_id, "analysis", "success", "模板请求已接收。")
            self.store.update_job_stage(job_id, "actions", "running", "正在准备图层和课堂视图。")
            result = self.template_service.apply_template(project_id, template_id, payload)
            self.store.update_job_stage(job_id, "actions", "success", "模板规则计算完成。")
            self.store.update_job_stage(job_id, "map", "success", "地图图层已写入课堂项目。")
            artifacts = self._register_artifacts(project_id, job_id, result.get("artifacts", []))
            self.store.update_job_stage(job_id, "artifacts", "success", "模板产物已登记。")
            self.store.set_job_status(
                job_id,
                "completed",
                result={
                    "status": "success",
                    "workflow_type": "template_run",
                    "summary": result["summary"],
                    "assistant_message": result["assistant_message"],
                    "template_id": template_id,
                    "artifacts": artifacts,
                    "stages": self.store.get_job(job_id).stages,
                    "layers": result.get("layers", []),
                    "view": result.get("view", {}),
                },
            )
        except Exception as exc:  # pragma: no cover - defensive runtime branch
            self._fail_job(job_id, "template_run", str(exc))

    def _session_statistics_for_assistant(self, session_id: str) -> Dict[str, Any]:
        """Read-only session statistics used to ground assistant answers."""
        session = self.store.get_class_session(session_id)
        if session is None:
            raise KeyError(f"Unknown class session: {session_id}")
        try:
            lesson = self.classroom._lesson_for_session(session)
        except Exception:
            lesson = None
        return self.classroom.report_service.build_statistics(session, lesson)

    def _log_assistant_exchange(
        self,
        job_id: str,
        map_context: Dict[str, Any],
        message: str,
        result: Dict[str, Any],
    ) -> None:
        """Append the assistant round-trip to the running class session's event
        stream so post-class reports can count and quote real usage."""
        try:
            teaching_context = map_context.get("teaching_context") if isinstance(map_context.get("teaching_context"), dict) else {}
            session_id = str((teaching_context or {}).get("session_id") or "").strip()
            if not session_id:
                return
            session = self.store.get_class_session(session_id)
            if session is None or session.status != "running":
                return
            tools = []
            for item in result.get("actions_executed") or []:
                action = item.get("action") or {}
                name = str(action.get("tool_name") or "").strip()
                if name:
                    tools.append(name)
            self.store.append_session_event(
                session_id,
                "assistant_exchange",
                stage_id=str(teaching_context.get("stage_id") or ""),
                payload={
                    "job_id": job_id,
                    "conversation_id": str(result.get("conversation_id") or ""),
                    "intent": str(result.get("intent") or ""),
                    "planner": str(result.get("planner") or ""),
                    "phase": str(teaching_context.get("phase") or ""),
                    "user_message": str(message or "")[:120],
                    "assistant_excerpt": str(result.get("assistant_message") or "")[:160],
                    "tools": tools,
                    "requires_confirmation": bool(result.get("requires_confirmation")),
                },
            )
        except Exception:  # pragma: no cover - event logging must never break the reply
            pass

    def _run_assistant_v2_job(
        self,
        job_id: str,
        project_id: str,
        message: str,
        map_context: Dict[str, Any],
        assistant_mode: str,
        conversation_id: str,
        history: List[Dict[str, Any]],
        target: str = "webgis",
        input_mode: str = "text",
        screen_snapshot: Optional[Dict[str, Any]] = None,
        teaching_context: Optional[Dict[str, Any]] = None,
        image_attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        try:
            project = self._require_project(project_id)
            if screen_snapshot:
                map_context = {**map_context, "screen_snapshot": screen_snapshot}
            if teaching_context:
                map_context = {**map_context, "teaching_context": teaching_context}
            if image_attachments:
                map_context = {**map_context, "image_attachments": image_attachments}
            self.store.set_job_status(job_id, "running")
            self.store.append_job_step(job_id, "route", "assistant session engine started", "running")

            def update_stage(stage_name: str, status: str, summary: str = "", detail: str = "") -> None:
                self.store.update_job_stage(job_id, stage_name, status, summary, detail)

            result = self.session_engine.handle(
                job_id=job_id,
                project=project,
                message=message,
                assistant_mode=assistant_mode,
                conversation_id=conversation_id,
                history=history,
                map_context=map_context,
                target=target,
                input_mode=input_mode,
                stage_callback=update_stage,
            )
            if not result.get("requires_confirmation"):
                self._log_assistant_exchange(job_id, map_context, message, result)
            registered_artifacts: Dict[str, Any] = {}
            for item in result.get("actions_executed", []):
                action_result = item.get("result", {})
                registered_artifacts.update(
                    self._register_artifacts(project_id, job_id, action_result.get("artifacts", []))
                )
            artifact_status = "success" if registered_artifacts else "skipped"
            artifact_summary = "Artifacts registered" if registered_artifacts else "No standalone artifacts"
            self.store.update_job_stage(job_id, "artifacts", artifact_status, artifact_summary)
            self.store.set_job_status(
                job_id,
                "completed",
                result={
                    "status": "success",
                    "workflow_type": "assistant_message",
                    "summary": result.get("assistant_message") or message,
                    "assistant_message": result.get("assistant_message") or "",
                    "teaching_contract": result.get("teaching_contract"),
                    "intent": result.get("intent"),
                    "knowledge": result.get("knowledge"),
                    "citations": result.get("citations", []),
                    "actions_planned": result.get("actions_planned", []),
                    "actions_executed": result.get("actions_executed", []),
                    "requires_confirmation": result.get("requires_confirmation", False),
                    "confirmation_id": result.get("confirmation_id", ""),
                    "confirmation_expires_at": result.get("confirmation_expires_at", ""),
                    "plan_fingerprint": result.get("plan_fingerprint", ""),
                    "planner": result.get("planner", ""),
                    "retrieval_trace": result.get("retrieval_trace", []),
                    "conversation_id": result.get("conversation_id", ""),
                    "prompt_parts": result.get("prompt_parts", {}),
                    "permission_context": result.get("permission_context", {}),
                    "artifacts": registered_artifacts,
                    "stages": self.store.get_job(job_id).stages,
                },
            )
        except Exception as exc:  # pragma: no cover - defensive runtime branch
            self._fail_job(job_id, "assistant_message_v2", str(exc))

    def _run_assistant_job(
        self,
        job_id: str,
        project_id: str,
        message: str,
        map_context: Dict[str, Any],
        target: str = "webgis",
        input_mode: str = "text",
        screen_snapshot: Optional[Dict[str, Any]] = None,
    ) -> None:
        try:
            project = self._require_project(project_id)
            if screen_snapshot:
                map_context = {**map_context, "screen_snapshot": screen_snapshot}
            self.store.set_job_status(job_id, "running")
            self.store.append_job_step(job_id, "解析指令", "正在理解课堂助教请求。", "running")
            self.store.update_job_stage(job_id, "analysis", "running", "正在分析课堂意图。")
            plan = self.llm_planner.plan_actions(
                message,
                project,
                map_context=map_context,
                target=target,
                input_mode=input_mode,
            )
            plan_target = str(plan.get("target") or "webgis")
            self.store.update_job_stage(job_id, "analysis", "success", "课堂意图识别完成。")
            self.store.update_job_stage(job_id, "actions", "running", "正在执行地图副驾驶动作。")
            executed_actions = []
            artifacts: List[Dict[str, Any]] = []
            messages = [plan.get("assistant_message", "").strip()]
            for action in plan.get("actions", []):
                self.store.append_job_step(job_id, action["tool_name"], json.dumps(action["tool_params"], ensure_ascii=False), "info")
                if action["tool_name"] in {"launch_question", "record_observation", "generate_image"}:
                    # The legacy path has no risk assessment or confirmation
                    # gate, so classroom tools are teaching-mode only.
                    refusal = (
                        "图片生成会消耗 MiniMax API 余额，请在图片库中使用“MiniMax AI 生成”并明确点击生成。"
                        if action["tool_name"] == "generate_image"
                        else "课堂工具（发布提问/记录学情）只在专业教学智能体模式下可用，且发布提问需要教师确认。"
                    )
                    executed_actions.append({"action": action, "result": {"assistant_message": refusal, "artifacts": []}})
                    messages.append(refusal)
                    continue
                action_result = self._execute_assistant_action(project_id, action, map_context)
                executed_actions.append({"action": action, "result": action_result})
                if action_result.get("assistant_message"):
                    messages.append(str(action_result["assistant_message"]))
                artifacts.extend(action_result.get("artifacts", []))
            self.store.update_job_stage(job_id, "actions", "success", "课堂动作执行完成。")
            self.store.update_job_stage(job_id, "map", "success", "项目状态已同步到课堂地图。")
            registered_artifacts = self._register_artifacts(project_id, job_id, artifacts)
            artifact_status = "success" if registered_artifacts else "skipped"
            artifact_summary = "已记录助教产物。" if registered_artifacts else "本次助教动作没有生成独立产物。"
            self.store.update_job_stage(job_id, "artifacts", artifact_status, artifact_summary)
            self.store.set_job_status(
                job_id,
                "completed",
                result={
                    "status": "success",
                    "workflow_type": "assistant_message",
                    "summary": messages[-1] if messages else "课堂助教已完成当前操作。",
                    "assistant_message": "\n\n".join([part for part in messages if part]),
                    "target": plan_target,
                    "planner": plan.get("planner", "rule_fallback"),
                    "llm_fallback_reason": plan.get("llm_fallback_reason", ""),
                    "actions": plan.get("actions", []),
                    "actions_executed": executed_actions,
                    "artifacts": registered_artifacts,
                    "stages": self.store.get_job(job_id).stages,
                },
            )
        except Exception as exc:  # pragma: no cover - defensive runtime branch
            self._fail_job(job_id, "assistant_message", str(exc))

    def _run_confirmation_job(self, job_id: str, confirmation_id: str, decision: str = "approve") -> None:
        try:
            self.store.set_job_status(job_id, "running")
            self.store.append_job_step(
                job_id,
                "confirm",
                "rejecting assistant action" if decision == "reject" else "executing confirmed assistant action",
                "running",
            )

            def update_stage(stage_name: str, status: str, summary: str = "", detail: str = "") -> None:
                self.store.update_job_stage(job_id, stage_name, status, summary, detail)

            confirmation = self.store.get_confirmation(confirmation_id)
            confirmation_payload = dict(confirmation.payload or {}) if confirmation is not None else {}
            if decision == "reject":
                result = self.session_engine.reject_confirmation(confirmation_id)
            else:
                result = self.session_engine.execute_confirmation(confirmation_id, stage_callback=update_stage)
                self._log_assistant_exchange(
                    job_id,
                    dict(confirmation_payload.get("map_context") or {}),
                    str(confirmation_payload.get("message") or ""),
                    result,
                )
            registered_artifacts: Dict[str, Any] = {}
            for item in result.get("actions_executed", []):
                action_result = item.get("result", {})
                registered_artifacts.update(
                    self._register_artifacts(result.get("project_id", self.store.get_job(job_id).project_id), job_id, action_result.get("artifacts", []))
                )
            self.store.update_job_stage(job_id, "artifacts", "success" if registered_artifacts else "skipped", "Confirmation flow finished")
            self.store.set_job_status(
                job_id,
                "completed",
                result={
                    "status": "success",
                    "workflow_type": "assistant_confirmation",
                    "summary": result.get("assistant_message", ""),
                    "assistant_message": result.get("assistant_message", ""),
                    "teaching_contract": result.get("teaching_contract"),
                    "intent": result.get("intent"),
                    "knowledge": result.get("knowledge"),
                    "citations": result.get("citations", []),
                    "actions_planned": result.get("actions_planned", []),
                    "actions_executed": result.get("actions_executed", []),
                    "requires_confirmation": False,
                    "confirmation_id": result.get("confirmation_id", ""),
                    "confirmation_status": "rejected" if decision == "reject" else "approved",
                    "planner": result.get("planner", "confirmation"),
                    "retrieval_trace": result.get("retrieval_trace", []),
                    "conversation_id": result.get("conversation_id", ""),
                    "permission_context": result.get("permission_context", {}),
                    "artifacts": registered_artifacts,
                    "stages": self.store.get_job(job_id).stages,
                },
            )
        except Exception as exc:  # pragma: no cover - defensive runtime branch
            self._fail_job(job_id, "assistant_confirmation", str(exc))

    def _execute_assistant_action(self, project_id: str, action: Dict[str, Any], map_context: Dict[str, Any]) -> Dict[str, Any]:
        tool_name = action["tool_name"]
        params = action.get("tool_params", {})
        if tool_name == "set_view":
            view = self.store.set_view(project_id, params)
            self.store.add_recent_action(project_id, "调整视角", "已更新课堂视图。", status="success")
            return {"assistant_message": "课堂视角已更新。", "view": view, "artifacts": []}
        if tool_name == "toggle_layer":
            layer = self.store.patch_layer(project_id, params["layer_id"], {"visible": params["visible"]})
            state_text = "显示" if params["visible"] else "隐藏"
            self.store.add_recent_action(project_id, f"{state_text}图层", f"{state_text}“{layer.name}”", status="success")
            return {"assistant_message": f"图层“{layer.name}”已{state_text}。", "artifacts": []}
        if tool_name == "reorder_layer":
            layer = self.store.patch_layer(project_id, params["layer_id"], {"z_index": params["z_index"]})
            self.store.add_recent_action(project_id, "调整图层顺序", f"“{layer.name}”已移动到新的层级。", status="success")
            return {"assistant_message": f"图层“{layer.name}”的顺序已调整。", "artifacts": []}
        if tool_name == "style_layer":
            layer = self.store.patch_layer(project_id, params["layer_id"], {"style": params["style"]})
            self.store.add_recent_action(project_id, "更新图层样式", f"“{layer.name}”样式已更新。", status="success")
            return {"assistant_message": f"图层“{layer.name}”的样式已更新。", "artifacts": []}
        if tool_name == "query_features":
            project = self._require_project(project_id)
            content = self.assistant_service.compose_feature_summary(project, params.get("layer_id", ""), limit=int(params.get("limit", 5)))
            note = self._write_text_output(project_id, f"query_{self._safe_output_stub(params.get('layer_id', 'layers'))}", content)
            return {
                "assistant_message": content,
                "artifacts": [{"artifact_type": "assistant_note", "title": "图层查询摘要", "path": str(note), "metadata": {"public_url": self.config.public_url_for_path(note)}}],
            }
        if tool_name == "draw_annotation":
            project = self._require_project(project_id)
            annotation_layer = next((layer for layer in project.layers if layer.layer_id == "assistant_annotations"), None)
            if annotation_layer is None:
                annotation_layer = LayerRecord.create(
                    layer_id="assistant_annotations",
                    name="课堂标注",
                    kind="annotation",
                    source="generated",
                    geometry_type="Point",
                    data={"type": "FeatureCollection", "features": []},
                    style={"labelField": "label", "fillColor": "#fde047", "radius": 8, "strokeColor": "#0f172a"},
                    z_index=100,
                )
            position = params.get("position") or project.view.get("center") or [104.0, 35.0]
            annotation_layer.data.setdefault("features", []).append(
                {
                    "type": "Feature",
                    "properties": {"name": params.get("text", "课堂标注"), "label": params.get("text", "课堂标注"), "__fillColor": "#fde047", "__strokeColor": "#0f172a", "__radius": 8},
                    "geometry": {"type": "Point", "coordinates": [float(position[0]), float(position[1])]},
                }
            )
            self.store.upsert_layer(project_id, annotation_layer)
            self.store.add_recent_action(project_id, "添加课堂标注", params.get("text", "课堂标注"), status="success")
            return {"assistant_message": "课堂标注已添加到当前视图。", "artifacts": []}
        if tool_name == "measure":
            content = self.assistant_service.compose_measurement(params.get("extent") or map_context.get("extent"))
            note = self._write_text_output(project_id, "measure_note", content)
            return {
                "assistant_message": content,
                "artifacts": [{"artifact_type": "assistant_note", "title": "尺度说明", "path": str(note), "metadata": {"public_url": self.config.public_url_for_path(note)}}],
            }
        if tool_name == "apply_template":
            result = self.template_service.apply_template(project_id, params["template_id"], {})
            return {"assistant_message": result["assistant_message"], "artifacts": result.get("artifacts", [])}
        if tool_name == "run_visual_query":
            result = self.classroom.visual_query_service.run(project_id, params)
            layer = LayerRecord(**result["layer"])
            self.store.upsert_layer(project_id, layer)
            self.store.set_active_layer(project_id, layer.layer_id)
            view = result.get("view") or {}
            if view:
                self.store.set_view(project_id, view)
            summary = str(result.get("summary") or f"已生成指标查询图层“{layer.name}”。")
            self.store.add_recent_action(
                project_id,
                "指标查询",
                summary,
                status="success",
                metadata={"layer_id": layer.layer_id, "query": params},
            )
            return {
                "assistant_message": summary,
                "layer": layer.to_dict(),
                "items": result.get("items", []),
                "visualization": result.get("visualization", {}),
                "view": view,
                "artifacts": [],
            }
        if tool_name == "export_snapshot":
            return {"assistant_message": self.assistant_service.build_export_hint(), "artifacts": []}
        if tool_name == "explain_current_view":
            project = self._require_project(project_id)
            content = self.assistant_service.compose_explanation(project, map_context=map_context, focus=params.get("focus", ""))
            screen_snapshot = map_context.get("screen_snapshot") if isinstance(map_context.get("screen_snapshot"), dict) else {}
            if screen_snapshot:
                vision_result = self.vision_service.understand_map(
                    project_id=project_id,
                    project=project,
                    map_context=map_context,
                    focus=params.get("focus", ""),
                    screen_snapshot=screen_snapshot,
                )
                if vision_result.get("used_vision") and vision_result.get("summary"):
                    content = "\n\n".join(
                        [
                            str(vision_result.get("summary") or "").strip(),
                            "---",
                            "结构化地图上下文补充：",
                            content,
                        ]
                    )
                if not vision_result.get("used_vision") and vision_result.get("reason"):
                    content = f"{content}\n\n注意事项：{vision_result['reason']}"
            note = self._write_text_output(project_id, "assistant_explanation", content)
            return {
                "assistant_message": content,
                "artifacts": [{"artifact_type": "assistant_note", "title": "课堂讲解稿", "path": str(note), "metadata": {"public_url": self.config.public_url_for_path(note)}}],
            }
        if tool_name == "switch_basemap":
            if params.get("basemap_id") not in {item["id"] for item in self.config.basemap_catalog()["items"]}:
                return {"assistant_message": "未找到指定底图，当前底图保持不变。", "artifacts": []}
            basemap = self.set_basemap(project_id, params["basemap_id"])["base_map"]
            return {"assistant_message": f"底图已切换到“{basemap.get('title', params['basemap_id'])}”。", "artifacts": []}
        if tool_name == "search_poi":
            result = self.search_poi(
                project_id=project_id,
                keyword=str(params.get("keyword") or ""),
                mode=str(params.get("mode") or "view"),
                extent=params.get("extent"),
                geometry=params.get("geometry"),
            )
            content = "\n".join(
                [
                    result["summary"],
                    *[
                        f"- {item['name']}（{item['district'] or item['city'] or '未知区域'} {item['address'] or ''}）".strip()
                        for item in result["items"][:5]
                    ],
                ]
            )
            note = self._write_text_output(project_id, "poi_search_note", content)
            return {
                "assistant_message": self.assistant_service.build_poi_hint(result["keyword"], len(result["items"])),
                "artifacts": [{"artifact_type": "assistant_note", "title": "POI 检索结果", "path": str(note), "metadata": {"public_url": self.config.public_url_for_path(note)}}],
            }
        if tool_name == "toggle_teaching_map":
            result = self.toggle_teaching_map(project_id, params["map_id"], params.get("visible", True))
            layer = result.get("layer")
            name = layer["name"] if layer else params["map_id"]
            visible = params.get("visible", True)
            state_text = "叠加" if visible else "隐藏"
            # Also set view to the recommended area when showing a teaching map
            view = result.get("view", {})
            if visible and view.get("center") and view.get("zoom"):
                self.store.set_view(project_id, view)
            return {
                "assistant_message": f'教学地图"{name}"已{state_text}。',
                "view": view,
                "artifacts": [],
            }
        if tool_name == "open_material":
            material = params.get("material") if isinstance(params.get("material"), dict) else {}
            if not material:
                material = self._find_kb_material(str(params.get("material_id") or ""))
            if not material:
                raise KeyError(f"Unknown teaching material: {params.get('material_id') or ''}")
            title = str(material.get("title") or "课堂资料")
            return {
                "assistant_message": f"已打开课堂资料“{title}”。",
                "ui_actions": [{"type": "open_material", "title": title, "materials": [material]}],
                "artifacts": [],
            }
        if tool_name == "generate_image":
            generated = self.generate_image_asset(
                project_id=project_id,
                prompt=str(params.get("prompt") or ""),
                title=str(params.get("title") or ""),
                model=str(params.get("model") or ""),
                aspect_ratio=str(params.get("aspect_ratio") or "16:9"),
                prompt_optimizer=bool(params.get("prompt_optimizer", True)),
            )
            artifact = generated["artifact"]
            return {
                "assistant_message": "图片已生成并保存到项目图片库，已标记为 AI 生成示意图。你可以把它加入助教继续提问。",
                "generated_artifact": artifact,
                "artifacts": [],
            }
        if tool_name == "record_observation":
            teaching_context = map_context.get("teaching_context") if isinstance(map_context.get("teaching_context"), dict) else {}
            session_id = str((teaching_context or {}).get("session_id") or "").strip()
            if not session_id:
                raise ValueError("record_observation requires an active class session")
            raw_verdict = str(params.get("verdict") or "").strip().lower()
            verdict_map = {
                "correct": "correct",
                "对": "correct",
                "答对": "correct",
                "正确": "correct",
                "partial": "partial",
                "部分": "partial",
                "部分正确": "partial",
                "misconception": "misconception",
                "误区": "misconception",
                "错误": "misconception",
            }
            verdict = verdict_map.get(raw_verdict, "")
            if not verdict:
                raise ValueError(
                    "record_observation 需要明确的学生表现判定 verdict（correct/partial/misconception，即 答对/部分正确/存在误区）"
                    + (f"，收到：{raw_verdict}" if raw_verdict else "")
                )
            observation = {
                "verdict": verdict,
                "tag": str(params.get("tag") or ""),
                "note": str(params.get("note") or ""),
                "question_id": str(params.get("question_id") or ""),
                "stage_id": str(params.get("stage_id") or ""),
            }
            self.classroom.add_session_observation(session_id, observation)
            verdict_text = {"correct": "答对", "partial": "部分正确", "misconception": "存在误区"}[verdict]
            detail = str(observation["note"] or observation["tag"] or "").strip()
            summary = f"已记录课堂学情（{verdict_text}）" + (f"：{detail}" if detail else "。")
            self.store.add_recent_action(project_id, "记录学情", summary, status="success")
            return {"assistant_message": summary, "artifacts": []}
        if tool_name == "launch_question":
            teaching_context = map_context.get("teaching_context") if isinstance(map_context.get("teaching_context"), dict) else {}
            session_id = str((teaching_context or {}).get("session_id") or "").strip()
            if not session_id:
                raise ValueError("launch_question requires an active class session")
            question_id = str(params.get("question_id") or "").strip()
            # Deliberately no teaching_context.stage_id fallback: the class may
            # advance between planning and execution, and an empty stage_id
            # makes the classroom service attribute the question to the CURRENT
            # stage at execution time.
            stage_id = str(params.get("stage_id") or "")
            if question_id:
                result = self.classroom.launch_session_question(
                    session_id,
                    stage_id=stage_id,
                    question_id=question_id,
                    delivery="teacher_oral",
                )
            else:
                raw_options = params.get("options")
                if isinstance(raw_options, str):
                    options = [part.strip() for part in re.split(r"[/;；、\n]", raw_options) if part.strip()]
                elif isinstance(raw_options, list):
                    options = [str(option) for option in raw_options]
                else:
                    options = []
                raw_index = params.get("answer_index")
                answer_index: Optional[int] = None
                if isinstance(raw_index, bool):
                    answer_index = None
                elif isinstance(raw_index, int):
                    answer_index = raw_index
                elif isinstance(raw_index, float) and float(raw_index).is_integer():
                    answer_index = int(raw_index)
                elif isinstance(raw_index, str) and raw_index.strip().isdigit():
                    answer_index = int(raw_index.strip())
                adhoc = {
                    "text": str(params.get("text") or "").strip(),
                    "options": options,
                    "answer_index": answer_index,
                }
                result = self.classroom.launch_session_question(
                    session_id,
                    stage_id=stage_id,
                    adhoc=adhoc,
                    delivery="teacher_oral",
                )
            presented = result.get("presented_question") or {}
            summary = f"已在教师工作台呈现口头提问：{presented.get('text', '')}"
            self.store.add_recent_action(project_id, "呈现口头提问", summary, status="success")
            return {"assistant_message": summary, "presented_question": presented, "artifacts": []}
        # --- 智能交互（interaction）工具 ---
        if tool_name == "switch_view_mode":
            mode = str(params.get("mode") or "").strip().lower()
            # 2D/3D 投影是客户端状态：后端只广播 ui_action，
            # 由前端 transitionToGlobe/transitionToPlane 执行平滑切换。
            summary = "已切换到三维地球。" if mode == "globe" else "已切换到二维平面地图。"
            self.store.add_recent_action(project_id, "切换视图模式", summary, status="success")
            return {
                "assistant_message": summary,
                "ui_actions": [{"type": "switch_view", "mode": "globe" if mode == "globe" else "plane"}],
                "artifacts": [],
            }
        if tool_name == "open_panel":
            panel = str(params.get("panel") or "").strip().lower()
            open_state = bool(params.get("open", True))
            panel_names = {"layers": "图层管理器", "database": "数据库面板", "workflow": "工作流坞"}
            name = panel_names.get(panel, panel)
            return {
                "assistant_message": f"已{'打开' if open_state else '关闭'}{name}。",
                "ui_actions": [{"type": "open_panel", "panel": panel, "open": open_state}],
                "artifacts": [],
            }
        if tool_name == "focus_layer":
            project = self._require_project(project_id)
            layer = self._resolve_interaction_layer(project, params, map_context)
            if layer is None:
                return {"assistant_message": "没有找到要定位的图层，请说出图层的完整名称后重试。", "artifacts": []}
            extent = self._layer_extent(layer)
            if not extent:
                return {"assistant_message": f"已选中图层“{layer.name}”，但该图层缺少范围信息，无法定位。", "artifacts": []}
            view = {
                "center": [(extent[0] + extent[2]) / 2.0, (extent[1] + extent[3]) / 2.0],
                "zoom": 6,
                "extent": extent,
            }
            self.store.set_view(project_id, view)
            self.store.add_recent_action(project_id, "定位图层", f"已定位到“{layer.name}”", status="success")
            return {"assistant_message": f"已定位到图层“{layer.name}”。", "view": view, "artifacts": []}
        if tool_name == "set_layer_opacity":
            project = self._require_project(project_id)
            layer = self._resolve_interaction_layer(project, params, map_context)
            if layer is None:
                return {"assistant_message": "没有找到要调整透明度的图层，请说出图层的完整名称后重试。", "artifacts": []}
            opacity = max(0.0, min(1.0, float(params.get("opacity", 1.0))))
            self.store.patch_layer(project_id, layer.layer_id, {"opacity": opacity})
            self.store.add_recent_action(project_id, "调整透明度", f"“{layer.name}”透明度已调整为 {opacity:g}", status="success")
            return {"assistant_message": f"图层“{layer.name}”的透明度已调整为 {opacity:g}。", "artifacts": []}
        if tool_name == "enter_lesson_stage":
            teaching_context = map_context.get("teaching_context") if isinstance(map_context.get("teaching_context"), dict) else {}
            session_id = str((teaching_context or {}).get("session_id") or "").strip()
            if not session_id:
                raise ValueError("enter_lesson_stage requires an active class session")
            session = self.store.get_class_session(session_id)
            if session is None:
                raise KeyError(f"Unknown class session: {session_id}")
            lesson = self.classroom._lesson_for_session(session)
            if lesson is None:
                raise KeyError(f"Unknown lesson: {session.lesson_id}")
            target_stage_id = self._resolve_interaction_stage_id(session, lesson, params)
            if not target_stage_id:
                return {"assistant_message": "没有匹配到对应的教学环节，可以说“下一环节”或说出环节名称。", "artifacts": []}
            result = self.classroom.enter_session_stage(session_id, target_stage_id)
            stage = result.get("stage") or {}
            stage_title = str(stage.get("title") or target_stage_id)
            summary = f"已进入环节“{stage_title}”，教学场景已同步切换。"
            self.store.add_recent_action(project_id, "进入教学环节", summary, status="success", metadata={"stage_id": target_stage_id})
            return {"assistant_message": summary, "stage": stage, "artifacts": []}
        if tool_name == "run_workflow":
            template_id = str(params.get("template_id") or "").strip()
            description = str(params.get("description") or "").strip()
            if not template_id:
                template_id = str(detect_template(description) or "")
            if template_id not in INTERACTION_ALLOWED_TEMPLATES:
                allowed_titles = "、".join(
                    item["title"] for item in list_templates() if item["id"] in INTERACTION_ALLOWED_TEMPLATES
                )
                return {"assistant_message": f"该分析暂不支持语音发起，目前可说：{allowed_titles}。", "artifacts": []}
            result = self.submit_workflow(
                project_id,
                message=description or template_id,
                mode="template",
                template_id=template_id,
                parameters=params.get("parameters") if isinstance(params.get("parameters"), dict) else None,
            )
            if result.get("error"):
                return {"assistant_message": f"分析提交失败：{result['error']}", "artifacts": []}
            template_title = next((item["title"] for item in list_templates() if item["id"] == template_id), template_id)
            summary = f"已提交「{template_title}」分析，完成后结果图层会自动加载。"
            self.store.add_recent_action(project_id, "语音发起分析", summary, status="success", metadata={"workflow_id": result.get("workflow_id", "")})
            return {
                "assistant_message": summary,
                "workflow": {"workflow_id": result.get("workflow_id", ""), "template_id": template_id, "status": result.get("workflow_status", "")},
                "ui_actions": [{"type": "open_panel", "panel": "workflow", "open": True}],
                "artifacts": [],
            }
        if tool_name == "start_class_session":
            teaching_context = map_context.get("teaching_context") if isinstance(map_context.get("teaching_context"), dict) else {}
            lesson_id = str(params.get("lesson_id") or (teaching_context or {}).get("lesson_id") or "").strip()
            lesson_title = str(params.get("lesson_title") or "").strip()
            if not lesson_id and lesson_title:
                matched = self.store.list_lessons() if hasattr(self.store, "list_lessons") else []
                # store.list_lessons 不存在时经由 lesson_service 匹配
                lessons = matched.get("items", []) if isinstance(matched, dict) else matched
                lesson_id = next(
                    (str(item.get("lesson_id") or "") for item in lessons if lesson_title in str(item.get("title") or "")),
                    "",
                )
            if not lesson_id:
                return {"assistant_message": "开始上课需要先绑定教案（在课前面板选择教案后再试）。", "artifacts": []}
            result = self.classroom.create_class_session(lesson_id, project_id)
            session = result.get("session") or {}
            summary = f"已开始上课（班课码 {session.get('join_code', '')}）。"
            self.store.add_recent_action(project_id, "开始上课", summary, status="success", metadata={"session_id": session.get("session_id", "")})
            return {"assistant_message": summary, "class_session": session, "artifacts": []}
        if tool_name == "end_class_session":
            teaching_context = map_context.get("teaching_context") if isinstance(map_context.get("teaching_context"), dict) else {}
            session_id = str((teaching_context or {}).get("session_id") or "").strip()
            if not session_id:
                raise ValueError("end_class_session requires an active class session")
            result = self.classroom.end_class_session(session_id)
            summary = "本节课已结束，课后报告已生成。"
            self.store.add_recent_action(project_id, "结束上课", summary, status="success", metadata={"session_id": session_id})
            return {"assistant_message": summary, "class_session": result.get("session") or {}, "artifacts": []}
        raise ValueError(f"Unsupported assistant tool: {tool_name}")

    def _resolve_interaction_layer(
        self,
        project: ProjectRecord,
        params: Dict[str, Any],
        map_context: Dict[str, Any],
    ) -> Optional[LayerRecord]:
        """layer_id 精确 → layer_name 子串 → 当前激活图层。"""
        layer_id = str(params.get("layer_id") or "").strip()
        if layer_id:
            return next((layer for layer in project.layers if layer.layer_id == layer_id), None)
        layer_name = str(params.get("layer_name") or "").strip().lower()
        if layer_name:
            for layer in project.layers:
                if layer_name in layer.name.lower():
                    return layer
            for layer in project.layers:
                if layer.name.lower() in layer_name:
                    return layer
            return None
        active_id = str(map_context.get("active_layer_id") or project.active_layer_id or "").strip()
        if active_id:
            return next((layer for layer in project.layers if layer.layer_id == active_id), None)
        return None

    @staticmethod
    def _iter_geojson_coordinates(node: Any):
        if isinstance(node, dict):
            for value in node.values():
                yield from WebGISRuntime._iter_geojson_coordinates(value)
        elif isinstance(node, (list, tuple)):
            if len(node) >= 2 and all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in node[:2]):
                yield node[0], node[1]
            else:
                for child in node:
                    yield from WebGISRuntime._iter_geojson_coordinates(child)

    def _layer_extent(self, layer: LayerRecord) -> Optional[List[float]]:
        data = layer.data if isinstance(layer.data, dict) else {}
        coordinates = list(self._iter_geojson_coordinates(data.get("features") or []))
        if not coordinates:
            return None
        lons = [point[0] for point in coordinates]
        lats = [point[1] for point in coordinates]
        return [min(lons), min(lats), max(lons), max(lats)]

    @staticmethod
    def _resolve_interaction_stage_id(session: Any, lesson: Any, params: Dict[str, Any]) -> str:
        stages = [stage for stage in (lesson.stages or []) if isinstance(stage, dict)]
        stage_ids = [str(stage.get("stage_id") or "") for stage in stages]
        stage_id = str(params.get("stage_id") or "").strip()
        if stage_id and stage_id in stage_ids:
            return stage_id
        stage_title = str(params.get("stage_title") or "").strip()
        if stage_title:
            lowered = stage_title.lower()
            for stage in stages:
                title = str(stage.get("title") or "")
                if lowered and (lowered in title.lower() or title.lower() in lowered):
                    return str(stage.get("stage_id") or "")
        offset = str(params.get("offset") or "").strip().lower()
        if offset in {"next", "previous"}:
            current = str(session.current_stage_id or "")
            if current in stage_ids:
                index = stage_ids.index(current)
                shifted = index + 1 if offset == "next" else index - 1
            else:
                shifted = 0 if offset == "next" else len(stage_ids) - 1
            shifted = max(0, min(len(stage_ids) - 1, shifted))
            return stage_ids[shifted]
        return ""

    def _register_artifacts(self, project_id: str, job_id: str, artifacts: List[Dict[str, Any]]) -> Dict[str, Any]:
        registered = {}
        for descriptor in artifacts:
            artifact = self.store.register_artifact(
                project_id=project_id,
                job_id=job_id,
                artifact_type=descriptor["artifact_type"],
                title=descriptor["title"],
                path=descriptor["path"],
                metadata=descriptor.get("metadata", {}),
            )
            registered[artifact.artifact_id] = artifact.to_dict()
        return registered

    def _write_text_output(self, project_id: str, stem: str, content: str) -> Path:
        output_path = self.config.unique_path(self.config.project_output_dir(project_id), f"{stem}.md")
        output_path.write_text(content, encoding="utf-8")
        return output_path

    def _safe_output_stub(self, value: str) -> str:
        return "".join(ch if ch.isalnum() else "_" for ch in str(value or "note"))

    def _find_kb_material(self, material_id: str) -> Dict[str, Any]:
        if not material_id:
            return {}
        manifest = self.knowledge_base_service.get_manifest()
        for item in manifest.get("items", []):
            for material in item.get("materials", []):
                if str(material.get("id") or "") == material_id:
                    return material
        return {}

    def _safe_upload_filename(self, filename: str) -> str:
        name = Path(filename or "material.dat").name
        stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(name).stem).strip("._") or "material"
        suffix = Path(name).suffix.lower()
        return f"{stem}_{uuid4().hex[:8]}{suffix}"

    def store_timestamp(self) -> str:
        return utc_now()

    def _lesson_resource_sets(self, project_id: str, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        rows = []
        for item in metadata.get("lesson_resource_sets", []):
            if isinstance(item, dict):
                rows.append(self._normalize_lesson_resource_set(project_id, item, str(item.get("updated_at") or utc_now())))
        return rows

    def _normalize_lesson_resource_set(self, project_id: str, payload: Dict[str, Any], now: str) -> Dict[str, Any]:
        raw = payload or {}
        set_id = str(raw.get("id") or f"lesson_{uuid4().hex}")
        def string_list(value: Any) -> List[str]:
            if not isinstance(value, list):
                return []
            return [str(item).strip() for item in value if str(item).strip()]

        bindings = []
        for entry in raw.get("region_bindings", []):
            if not isinstance(entry, dict):
                continue
            bindings.append({key: str(value).strip() for key, value in entry.items() if key in {"layer_id", "feature_id", "admin_code", "name", "name_field"} and str(value).strip()})
        return {
            "id": set_id,
            "title": str(raw.get("title") or "课堂资料包").strip(),
            "project_id": project_id or str(raw.get("project_id") or ""),
            "item_ids": string_list(raw.get("item_ids")),
            "material_ids": string_list(raw.get("material_ids")),
            "region_bindings": bindings,
            "active": bool(raw.get("active")),
            "created_at": str(raw.get("created_at") or now),
            "updated_at": now,
        }

    def _normalize_loaded_projects(self) -> None:
        for project in list(self.store.projects.values()):
            normalized_templates = [item for item in project.enabled_templates if item not in DISABLED_TEMPLATE_IDS]
            if normalized_templates != project.enabled_templates:
                project.enabled_templates = normalized_templates
                self.store.save_project(project)
            normalized = self.config.normalize_basemap(project.base_map)
            if normalized != project.base_map:
                self.store.set_basemap(project.project_id, normalized)

    def _fail_job(self, job_id: str, workflow_type: str, message: str) -> None:
        self.store.update_job_stage(job_id, "artifacts", "error", message)
        self.store.set_job_status(
            job_id,
            "failed",
            result={"status": "error", "workflow_type": workflow_type, "summary": message, "assistant_message": message, "stages": self.store.get_job(job_id).stages},
            error=message,
        )

    def _require_project(self, project_id: str) -> ProjectRecord:
        project = self.store.get_project(project_id)
        if not project:
            raise KeyError(f"Unknown project: {project_id}")
        return project
