from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from uuid import uuid4

from ..config import AppConfig
from ..models import LayerRecord


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(value: str) -> str:
    lowered = (value or "").strip().lower()
    cleaned = re.sub(r"[^a-z0-9_]+", "_", lowered)
    cleaned = cleaned.strip("_")
    return cleaned or "kb_item"


def _safe_list(payload: Any) -> List[Any]:
    return payload if isinstance(payload, list) else []


def _safe_dict(payload: Any) -> Dict[str, Any]:
    return payload if isinstance(payload, dict) else {}


def _as_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_keywords(value: Any) -> List[str]:
    raw = []
    if isinstance(value, str):
        raw = [part.strip() for part in re.split(r"[;,，\s]+", value) if part.strip()]
    elif isinstance(value, list):
        raw = [_as_text(item) for item in value if _as_text(item)]
    deduplicated: List[str] = []
    seen = set()
    for item in raw:
        lowered = item.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduplicated.append(item)
    return deduplicated


def _normalize_citations(value: Any) -> List[Dict[str, str]]:
    citations = []
    for item in _safe_list(value):
        if not isinstance(item, dict):
            continue
        title = _as_text(item.get("title"))
        url = _as_text(item.get("url"))
        if not title and not url:
            continue
        citations.append({"title": title or url, "url": url})
    return citations


def _normalize_region_binding(value: Any) -> Dict[str, str]:
    raw = _safe_dict(value)
    normalized: Dict[str, str] = {}
    for key in ("layer_id", "feature_id", "admin_code", "name", "name_field"):
        text = _as_text(raw.get(key))
        if text:
            normalized[key] = text
    return normalized


def _infer_material_type(filename_or_url: str, explicit_type: str = "") -> str:
    requested = _as_text(explicit_type).lower()
    if requested in {"image", "video", "animation", "document", "link"}:
        return requested
    suffix = Path(filename_or_url.split("?", 1)[0]).suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".svg"}:
        return "image"
    if suffix in {".gif", ".html", ".htm"}:
        return "animation"
    if suffix in {".mp4", ".webm", ".mov", ".m4v"}:
        return "video"
    if suffix in {".pdf", ".doc", ".docx", ".ppt", ".pptx"}:
        return "document"
    return "link"


def _normalize_material(value: Any) -> Dict[str, Any]:
    raw = _safe_dict(value)
    url = _as_text(raw.get("url"))
    title = _safe_text(raw.get("title"), Path(url).name or "教学资料")
    created_at = _as_text(raw.get("created_at")) or _utc_now()
    return {
        "id": _as_text(raw.get("id")) or f"material_{uuid4().hex}",
        "title": title,
        "type": _infer_material_type(url or title, _as_text(raw.get("type"))),
        "source": _safe_text(raw.get("source"), "teacher_upload"),
        "url": url,
        "thumbnail_url": _as_text(raw.get("thumbnail_url")),
        "description": _safe_text(raw.get("description")),
        "region_binding": _normalize_region_binding(raw.get("region_binding")),
        "sort_order": int(raw.get("sort_order") or 0),
        "created_at": created_at,
    }


def _normalize_materials(value: Any) -> List[Dict[str, Any]]:
    materials = []
    seen = set()
    for item in _safe_list(value):
        material = _normalize_material(item)
        if material["id"] in seen:
            continue
        seen.add(material["id"])
        materials.append(material)
    materials.sort(key=lambda row: (int(row.get("sort_order") or 0), str(row.get("created_at") or "")))
    return materials


def _looks_broken_text(value: Any) -> bool:
    text = _as_text(value)
    if not text:
        return False
    if "???" in text:
        return True
    return any(token in text for token in ("涓", "璇", "搴", "鍥", "鏉", "鐭", "瑙", "鍒"))


def _safe_text(value: Any, fallback: str = "") -> str:
    text = _as_text(value)
    return fallback if _looks_broken_text(text) else text


def _derive_status(item: Dict[str, Any]) -> str:
    explicit = _safe_text(item.get("status")).lower()
    if explicit in {"knowledge_only", "renderable_layer", "stored_only"}:
        return explicit
    refs = [entry for entry in _safe_list(item.get("dataset_refs")) if isinstance(entry, dict)]
    if not refs:
        return "knowledge_only"
    source_files = " ".join(_as_text(ref.get("source_file")).lower() for ref in refs)
    if any(ext in source_files for ext in (".jpg", ".jpeg", ".png", ".webp")):
        return "renderable_layer"
    return "stored_only"


TOPIC_LABELS = {
    "population_census": "人口普查",
    "population_distribution": "人口分布",
    "climate_zoning": "气候区划",
    "classroom_dataset": "课堂数据",
}


class KnowledgeBaseService:
    def __init__(self, config: AppConfig):
        self.config = config
        self.knowledge_dir = Path(self.config.knowledge_dir)
        self.geo_path = self.knowledge_dir / "geo_knowledge.json"
        self.manifest_path = self.knowledge_dir / "kb_manifest.json"

    def get_manifest(self) -> Dict[str, Any]:
        manifest = self._load_manifest(create_if_missing=True)
        return {
            "status": "success",
            "path": str(self.manifest_path),
            **manifest,
        }

    def search(
        self,
        query: str = "",
        topic: str = "",
        region: str = "",
        tag: str = "",
        limit: int = 20,
    ) -> Dict[str, Any]:
        query_tokens = [token for token in _normalize_keywords(query) if token]
        topic_lower = _as_text(topic).lower()
        region_lower = _as_text(region).lower()
        tag_lower = _as_text(tag).lower()
        rows = []

        for item in self._manifest_items():
            item_topic = _as_text(item.get("topic")).lower()
            item_region = _as_text(item.get("region")).lower()
            keywords = _normalize_keywords(item.get("keywords"))
            tags = _normalize_keywords(item.get("tags")) or keywords
            haystack_parts = [
                _as_text(item.get("title")),
                _as_text(item.get("topic")),
                _as_text(item.get("region")),
                _as_text(item.get("summary")),
                _as_text(item.get("canonical_answer")),
                " ".join(keywords),
                " ".join(tags),
            ]
            haystack = " ".join(part.lower() for part in haystack_parts if part)

            if topic_lower and topic_lower not in item_topic:
                continue
            if region_lower and region_lower not in item_region:
                continue
            if tag_lower and not any(tag_lower in candidate.lower() for candidate in tags + keywords):
                continue

            score = 0
            if query_tokens:
                token_hits = sum(1 for token in query_tokens if token.lower() in haystack)
                if token_hits == 0:
                    continue
                score += token_hits
            if topic_lower:
                score += 2
            if region_lower:
                score += 2
            if tag_lower:
                score += 2

            payload = dict(item)
            payload["_score"] = score
            rows.append(payload)

        rows.sort(key=lambda item: (int(item.get("_score", 0)), str(item.get("updated_at", ""))), reverse=True)
        max_limit = max(1, min(int(limit or 20), 100))
        paged = rows[:max_limit]
        for item in paged:
            item.pop("_score", None)

        return {
            "status": "success",
            "query": query,
            "topic": topic,
            "region": region,
            "tag": tag,
            "total": len(rows),
            "items": paged,
        }

    def topics(self) -> Dict[str, Any]:
        groups: Dict[str, Dict[str, Any]] = {}
        for item in self._manifest_items():
            topic = _as_text(item.get("topic")) or "uncategorized"
            status = _derive_status(item)
            group = groups.setdefault(
                topic,
                {
                    "topic": topic,
                    "title": TOPIC_LABELS.get(topic, topic),
                    "item_count": 0,
                    "renderable_count": 0,
                    "stored_only_count": 0,
                    "knowledge_only_count": 0,
                    "sample_titles": [],
                },
            )
            group["item_count"] += 1
            if status == "renderable_layer":
                group["renderable_count"] += 1
            elif status == "stored_only":
                group["stored_only_count"] += 1
            else:
                group["knowledge_only_count"] += 1
            if len(group["sample_titles"]) < 3:
                group["sample_titles"].append(_as_text(item.get("title")) or "待整理条目")

        return {
            "status": "success",
            "items": sorted(groups.values(), key=lambda row: (row["topic"] != "population_census", row["topic"])),
        }

    def upsert_item(self, raw_item: Dict[str, Any]) -> Dict[str, Any]:
        manifest = self._load_manifest(create_if_missing=True)
        item = self._normalize_manifest_item(raw_item)
        if not item["title"]:
            raise ValueError("Knowledge item requires title")

        existing = _safe_list(manifest.get("items"))
        replaced = False
        for index, row in enumerate(existing):
            if _as_text(_safe_dict(row).get("id")) == item["id"]:
                existing[index] = item
                replaced = True
                break
        if not replaced:
            existing.append(item)

        manifest["items"] = existing
        manifest["updated_at"] = _utc_now()
        self._write_manifest(manifest)
        return item

    def add_material_to_item(self, kb_item_id: str, raw_material: Dict[str, Any]) -> Dict[str, Any]:
        manifest = self._load_manifest(create_if_missing=True)
        target_id = _as_text(kb_item_id)
        if not target_id:
            raise ValueError("Knowledge material requires kb_item_id")
        material = _normalize_material(raw_material)
        found = False
        items = _safe_list(manifest.get("items"))
        for index, row in enumerate(items):
            item = self._normalize_manifest_item(_safe_dict(row))
            if item["id"] != target_id:
                continue
            existing = [entry for entry in item.get("materials", []) if entry.get("id") != material["id"]]
            item["materials"] = _normalize_materials([*existing, material])
            items[index] = item
            found = True
            break
        if not found:
            raise ValueError(f"Unknown knowledge item: {target_id}")
        manifest["items"] = items
        manifest["updated_at"] = _utc_now()
        self._write_manifest(manifest)
        return material

    def build_item_from_layer(
        self,
        project_id: str,
        layer: LayerRecord,
        overrides: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        overrides = overrides or {}
        source_file = _as_text(layer.metadata.get("source_file"))
        default_summary = (
            f"课堂数据图层“{layer.name}”已导入。可结合{layer.geometry_type}要素分布进行读图讲解，"
            "并围绕空间格局、形成机制和区域差异组织课堂提问。"
        )
        item = {
            "id": _as_text(overrides.get("id")) or f"{_slugify(project_id)}_{_slugify(layer.layer_id)}",
            "title": _as_text(overrides.get("title")) or layer.name,
            "topic": _as_text(overrides.get("topic")) or "classroom_dataset",
            "region": _as_text(overrides.get("region")),
            "time": _as_text(overrides.get("time")),
            "source": _as_text(overrides.get("source")) or source_file or "teacher_upload",
            "license": _as_text(overrides.get("license")) or "unknown",
            "grade_level": _as_text(overrides.get("grade_level")) or "general",
            "keywords": _normalize_keywords(overrides.get("keywords")) or [layer.name, layer.geometry_type, layer.kind],
            "crs": _as_text(overrides.get("crs")) or "EPSG:4326",
            "summary": _as_text(overrides.get("summary")) or default_summary,
            "canonical_answer": _as_text(overrides.get("canonical_answer")) or default_summary,
            "teaching_points": _safe_list(overrides.get("teaching_points"))
            or [
                "先描述图层对象与空间分布。",
                "再解释主要地理影响因素。",
                "最后回扣课堂主题并形成结论。",
            ],
            "citations": _normalize_citations(overrides.get("citations")),
            "dataset_refs": [
                {
                    "project_id": project_id,
                    "layer_id": layer.layer_id,
                    "layer_name": layer.name,
                    "source_file": source_file,
                }
            ],
            "materials": _safe_list(overrides.get("materials")),
        }
        return self._normalize_manifest_item(item)

    def build_engine_units(self) -> List[Dict[str, Any]]:
        geo_units = self._load_geo_units()
        manifest_units = []
        for item in self._manifest_items():
            manifest_units.append(
                {
                    "id": _as_text(item.get("id")),
                    "title": _as_text(item.get("title")),
                    "domain": _as_text(item.get("topic")) or "geo_concept",
                    "tags": _normalize_keywords(item.get("keywords")) or _normalize_keywords(item.get("tags")),
                    "canonical_answer": _as_text(item.get("canonical_answer")) or _as_text(item.get("summary")),
                    "teaching_points": _safe_list(item.get("teaching_points")),
                    "citations": _normalize_citations(item.get("citations")),
                    "related_templates": _safe_list(item.get("related_templates")),
                    "updated_at": _as_text(item.get("updated_at")) or _utc_now(),
                    "materials": _normalize_materials(item.get("materials")),
                }
            )
        return self._deduplicate_engine_units([*geo_units, *manifest_units])

    def _deduplicate_engine_units(self, units: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        index_by_id: Dict[str, int] = {}
        for raw in units:
            row = _safe_dict(raw)
            title = _as_text(row.get("title"))
            canonical = _as_text(row.get("canonical_answer"))
            if not title or not canonical:
                continue
            unit_id = _as_text(row.get("id")) or _slugify(title)
            normalized = {
                "id": unit_id,
                "title": title,
                "domain": _as_text(row.get("domain")) or "geo_concept",
                "tags": _normalize_keywords(row.get("tags")),
                "canonical_answer": canonical,
                "teaching_points": [str(item).strip() for item in _safe_list(row.get("teaching_points")) if str(item).strip()],
                "citations": _normalize_citations(row.get("citations")),
                "related_templates": _safe_list(row.get("related_templates")),
                "updated_at": _as_text(row.get("updated_at")) or _utc_now(),
            }
            if unit_id in index_by_id:
                rows[index_by_id[unit_id]] = normalized
            else:
                index_by_id[unit_id] = len(rows)
                rows.append(normalized)
        return rows

    def _manifest_items(self) -> List[Dict[str, Any]]:
        manifest = self._load_manifest(create_if_missing=True)
        items = []
        for row in _safe_list(manifest.get("items")):
            if isinstance(row, dict):
                items.append(self._normalize_manifest_item(row))
        return items

    def _normalize_manifest_item(self, raw_item: Dict[str, Any]) -> Dict[str, Any]:
        item = _safe_dict(raw_item)
        title = _as_text(item.get("title"))
        identifier = _as_text(item.get("id")) or _slugify(title or _as_text(item.get("source")) or "kb_item")
        summary = _as_text(item.get("summary"))
        canonical_answer = _as_text(item.get("canonical_answer")) or summary
        keywords = _normalize_keywords(item.get("keywords"))
        tags = _normalize_keywords(item.get("tags")) or keywords
        citations = _normalize_citations(item.get("citations"))
        teaching_points = [str(entry).strip() for entry in _safe_list(item.get("teaching_points")) if str(entry).strip()]

        return {
            "id": identifier,
            "title": _safe_text(title, "待整理条目"),
            "topic": _safe_text(item.get("topic")),
            "region": _safe_text(item.get("region")),
            "time": _safe_text(item.get("time")),
            "status": _derive_status(item),
            "source": _safe_text(item.get("source")),
            "license": _safe_text(item.get("license")),
            "grade_level": _safe_text(item.get("grade_level")),
            "keywords": [_safe_text(keyword, "待整理") for keyword in keywords if _safe_text(keyword, "待整理")],
            "tags": [_safe_text(tag, "待整理") for tag in tags if _safe_text(tag, "待整理")],
            "crs": _safe_text(item.get("crs")),
            "summary": _safe_text(summary, "该资料条目需要进一步整理摘要。"),
            "canonical_answer": _safe_text(canonical_answer, _safe_text(summary, "该资料条目需要进一步整理标准解释。")),
            "teaching_points": [_safe_text(entry, "待整理教学要点") for entry in teaching_points],
            "citations": citations,
            "dataset_refs": [entry for entry in _safe_list(item.get("dataset_refs")) if isinstance(entry, dict)],
            "materials": _normalize_materials(item.get("materials")),
            "related_templates": _safe_list(item.get("related_templates")),
            "updated_at": _as_text(item.get("updated_at")) or _utc_now(),
        }

    def _load_geo_units(self) -> List[Dict[str, Any]]:
        if not self.geo_path.exists():
            return []
        try:
            payload = json.loads(self.geo_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return payload if isinstance(payload, list) else []

    def _load_manifest(self, create_if_missing: bool = False) -> Dict[str, Any]:
        if not self.manifest_path.exists():
            manifest = self._default_manifest()
            if create_if_missing:
                self._write_manifest(manifest)
            return manifest
        try:
            payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = self._default_manifest()
            if create_if_missing:
                self._write_manifest(payload)
            return payload
        if not isinstance(payload, dict):
            payload = self._default_manifest()
            if create_if_missing:
                self._write_manifest(payload)
        payload.setdefault("version", "1.0")
        payload.setdefault("updated_at", _utc_now())
        payload["items"] = _safe_list(payload.get("items"))
        return payload

    def _write_manifest(self, manifest: Dict[str, Any]) -> None:
        self.knowledge_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    def _default_manifest(self) -> Dict[str, Any]:
        return {
            "version": "1.0",
            "updated_at": _utc_now(),
            "items": [],
        }
