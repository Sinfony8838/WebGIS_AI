from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from uuid import uuid4

from ..config import AppConfig
from ..models import LayerRecord
from .knowledge_retrieval import RetrievalDoc, RetrievalEngine, RetrievalResult

# Bounded result cache: keyed by query+filters+owner+manifest fingerprint.
# Values are already permission-filtered, and a different owner or an
# older manifest fingerprint is a different key, so stale or cross-user
# rows can never be served from it.
_RESULT_CACHE_LIMIT = 256

INSUFFICIENT_MESSAGE = "知识库中没有找到与该问题匹配的资料，请尝试更换关键词或放宽筛选条件。"


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
        "owner_user_id": _as_text(raw.get("owner_user_id")),
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
        self._manifest_fingerprint: Tuple[int, int] | None = None
        self._cached_manifest: Dict[str, Any] | None = None
        self._engine_cache: Dict[Tuple[str, bool, str, str, str], RetrievalEngine] = {}
        self._result_cache: Dict[Tuple[Any, ...], Dict[str, Any]] = {}

    @staticmethod
    def _path_fingerprint(path: Path) -> Tuple[int, int]:
        try:
            stat = path.stat()
            return (stat.st_mtime_ns, stat.st_size)
        except OSError:
            return (0, 0)

    def _fingerprint(self) -> Tuple[int, int]:
        return self._path_fingerprint(self.manifest_path)

    def engine_units_fingerprint(self) -> Tuple[Tuple[int, int], Tuple[int, int]]:
        """Fingerprint every file that contributes public assistant evidence."""
        return (self._fingerprint(), self._path_fingerprint(self.geo_path))

    def _invalidate_caches(self) -> None:
        self._manifest_fingerprint = None
        self._cached_manifest = None
        self._engine_cache.clear()
        self._result_cache.clear()

    def _engine_for(
        self,
        owner_user_id: str,
        include_all: bool,
        topic_lower: str = "",
        region_lower: str = "",
        tag_lower: str = "",
    ) -> RetrievalEngine:
        """Return an index built only from accessible, explicitly filtered items."""
        key = (owner_user_id or "", bool(include_all), topic_lower, region_lower, tag_lower)
        self._manifest_items()  # refresh cache if the file changed on disk
        engine = self._engine_cache.get(key)
        if engine is None:
            docs = [
                self._doc_from_item(item)
                for item in self._accessible_items(owner_user_id, include_all)
                if self._passes_explicit_filters(item, topic_lower, region_lower, tag_lower)
            ]
            engine = RetrievalEngine(docs)
            self._engine_cache[key] = engine
        return engine

    def _accessible_items(self, owner_user_id: str, include_all: bool) -> List[Dict[str, Any]]:
        return [
            item
            for item in self._manifest_items()
            if self._can_access_item(item, owner_user_id, include_all)
        ]

    @staticmethod
    def _doc_from_item(item: Dict[str, Any]) -> RetrievalDoc:
        materials = [
            " ".join(
                part
                for part in (
                    str(material.get("title") or ""),
                    str(material.get("description") or ""),
                )
                if part
            )
            for material in item.get("materials", [])
            if isinstance(material, dict)
        ]
        return RetrievalDoc.from_mapping(item, material_texts=materials)

    def get_manifest(self, owner_user_id: str = "", include_all: bool = False) -> Dict[str, Any]:
        manifest = self._load_manifest(create_if_missing=True)
        items = [
            item
            for item in self._manifest_items()
            if self._can_access_item(item, owner_user_id, include_all)
        ]
        return {
            "status": "success",
            "path": str(self.manifest_path),
            **manifest,
            "items": items,
        }

    def search(
        self,
        query: str = "",
        topic: str = "",
        region: str = "",
        tag: str = "",
        limit: int = 20,
        owner_user_id: str = "",
        include_all: bool = False,
    ) -> Dict[str, Any]:
        cache_key = (
            str(query or ""),
            str(topic or ""),
            str(region or ""),
            str(tag or ""),
            int(limit or 20),
            str(owner_user_id or ""),
            bool(include_all),
            self._fingerprint(),
        )
        cached = self._result_cache.get(cache_key)
        if cached is not None:
            # Cache reuse re-applies nothing: the stored payload was already
            # permission-filtered under this exact owner/include_all key.
            return {**cached, "from_cache": True}

        query_tokens = [token for token in _normalize_keywords(query) if token]
        topic_lower = _as_text(topic).lower()
        region_lower = _as_text(region).lower()
        tag_lower = _as_text(tag).lower()

        # Permission filtering happens before scoring and before any result
        # is stored: the engine itself is built from accessible items only.
        items = [
            item
            for item in self._accessible_items(owner_user_id, include_all)
            if self._passes_explicit_filters(item, topic_lower, region_lower, tag_lower)
        ]

        rows: List[Tuple[float, str, Dict[str, Any]]] = []
        insufficient = False
        message = ""
        if query_tokens or _as_text(query).strip():
            # Rank inside the explicitly filtered corpus. Ranking the full
            # corpus first can fill Top-N with disallowed topics/regions and
            # make a valid filtered item disappear during the later ID join.
            engine = self._engine_for(
                owner_user_id,
                include_all,
                topic_lower,
                region_lower,
                tag_lower,
            )
            by_id = {str(item.get("id")): item for item in items}
            result: RetrievalResult = engine.search(query, limit=max(1, min(int(limit or 20), 100)))
            if result.insufficient:
                insufficient = True
                message = result.message or INSUFFICIENT_MESSAGE
            for hit in result.hits:
                item = by_id.get(hit.doc_id)
                if item is None:
                    continue
                payload = dict(item)
                payload["retrieval_score"] = round(hit.score, 4)
                rows.append((float(hit.score), _as_text(item.get("updated_at")), payload))
            rows.sort(key=lambda row: (row[0], row[1]), reverse=True)
        else:
            # No query text: keep the historical "list by filters" behavior.
            for item in items:
                score = 0.0
                if topic_lower and topic_lower in _as_text(item.get("topic")).lower():
                    score += 2
                if region_lower and region_lower in _as_text(item.get("region")).lower():
                    score += 2
                if tag_lower:
                    score += 2
                payload = dict(item)
                payload["retrieval_score"] = score
                rows.append((score, _as_text(item.get("updated_at")), payload))
            rows.sort(key=lambda row: (row[0], row[1]), reverse=True)

        max_limit = max(1, min(int(limit or 20), 100))
        paged = [payload for _, _, payload in rows[:max_limit]]
        response = {
            "status": "success",
            "query": query,
            "topic": topic,
            "region": region,
            "tag": tag,
            "total": len(rows),
            "items": paged,
            "insufficient": insufficient,
            "message": message,
        }
        self._result_cache[cache_key] = response
        while len(self._result_cache) > _RESULT_CACHE_LIMIT:
            self._result_cache.pop(next(iter(self._result_cache)))
        return dict(response)

    @staticmethod
    def _passes_explicit_filters(item: Dict[str, Any], topic_lower: str, region_lower: str, tag_lower: str) -> bool:
        if topic_lower and topic_lower not in _as_text(item.get("topic")).lower():
            return False
        if region_lower and region_lower not in _as_text(item.get("region")).lower():
            return False
        if tag_lower:
            keywords = _normalize_keywords(item.get("keywords"))
            tags = _normalize_keywords(item.get("tags")) or keywords
            if not any(tag_lower in candidate.lower() for candidate in tags + keywords):
                return False
        return True

    def topics(self, owner_user_id: str = "", include_all: bool = False) -> Dict[str, Any]:
        groups: Dict[str, Dict[str, Any]] = {}
        for item in self._manifest_items():
            if not self._can_access_item(item, owner_user_id, include_all):
                continue
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

    def upsert_item(
        self,
        raw_item: Dict[str, Any],
        *,
        owner_user_id: str = "",
        include_all: bool = False,
    ) -> Dict[str, Any]:
        manifest = self._load_manifest(create_if_missing=True)
        raw_item = {**raw_item, "owner_user_id": owner_user_id or raw_item.get("owner_user_id", "")}
        item = self._normalize_manifest_item(raw_item)
        if not item["title"]:
            raise ValueError("Knowledge item requires title")
        if not item["updated_at"]:
            item["updated_at"] = _utc_now()

        existing = _safe_list(manifest.get("items"))
        replaced = False
        for index, row in enumerate(existing):
            if _as_text(_safe_dict(row).get("id")) == item["id"]:
                current = self._normalize_manifest_item(_safe_dict(row))
                if not self._can_access_item(current, owner_user_id, include_all):
                    raise ValueError(f"Unknown knowledge item: {item['id']}")
                if not current.get("owner_user_id") and owner_user_id:
                    raise ValueError("Built-in knowledge items are read-only")
                if current.get("owner_user_id") and not item.get("owner_user_id"):
                    item["owner_user_id"] = current["owner_user_id"]
                existing[index] = item
                replaced = True
                break
        if not replaced:
            existing.append(item)

        manifest["items"] = existing
        manifest["updated_at"] = _utc_now()
        self._write_manifest(manifest)
        return item

    def add_material_to_item(
        self,
        kb_item_id: str,
        raw_material: Dict[str, Any],
        *,
        owner_user_id: str = "",
        include_all: bool = False,
    ) -> Dict[str, Any]:
        manifest = self._load_manifest(create_if_missing=True)
        target_id = _as_text(kb_item_id)
        if not target_id:
            raise ValueError("Knowledge material requires kb_item_id")
        material = _normalize_material(
            {**raw_material, "owner_user_id": owner_user_id or raw_material.get("owner_user_id", "")}
        )
        found = False
        items = _safe_list(manifest.get("items"))
        for index, row in enumerate(items):
            item = self._normalize_manifest_item(_safe_dict(row))
            if item["id"] != target_id:
                continue
            if not self._can_access_item(item, owner_user_id, include_all):
                break
            if not item.get("owner_user_id") and owner_user_id:
                raise ValueError("Built-in knowledge items are read-only")
            existing = [entry for entry in item.get("materials", []) if entry.get("id") != material["id"]]
            item["materials"] = _normalize_materials([*existing, material])
            item["updated_at"] = _utc_now()
            items[index] = item
            found = True
            break
        if not found:
            raise ValueError(f"Unknown knowledge item: {target_id}")
        manifest["items"] = items
        manifest["updated_at"] = _utc_now()
        self._write_manifest(manifest)
        return material

    def delete_item(
        self,
        item_id: str,
        *,
        owner_user_id: str = "",
        include_all: bool = False,
    ) -> Dict[str, Any]:
        """Remove one knowledge item and invalidate every derived cache.

        Built-in items (no owner) stay read-only, mirroring ``upsert_item``.
        The authenticated HTTP route delegates here through the runtime layer.
        """
        manifest = self._load_manifest(create_if_missing=True)
        target_id = _as_text(item_id)
        if not target_id:
            raise ValueError("Knowledge item deletion requires an item id")
        items = _safe_list(manifest.get("items"))
        found_index = -1
        found: Dict[str, Any] = {}
        for index, row in enumerate(items):
            current = _safe_dict(row)
            if _as_text(current.get("id")) == target_id:
                found_index = index
                found = current
                break
        if found_index < 0:
            raise ValueError(f"Unknown knowledge item: {target_id}")
        if not self._can_access_item(found, owner_user_id, include_all):
            raise ValueError(f"Unknown knowledge item: {target_id}")
        if not _as_text(found.get("owner_user_id")):
            raise ValueError("Built-in knowledge items are read-only")
        items.pop(found_index)
        manifest["items"] = items
        manifest["updated_at"] = _utc_now()
        self._write_manifest(manifest)
        return found

    def build_item_from_layer(
        self,
        project_id: str,
        layer: LayerRecord,
        overrides: Optional[Dict[str, Any]] = None,
        owner_user_id: str = "",
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
            "owner_user_id": owner_user_id,
        }
        return self._normalize_manifest_item(item)

    def build_engine_units(self) -> List[Dict[str, Any]]:
        geo_units = self._load_geo_units()
        manifest_units = []
        for item in self._manifest_items():
            if item.get("owner_user_id"):
                continue
            manifest_units.append(
                {
                    "id": _as_text(item.get("id")),
                    "title": _as_text(item.get("title")),
                    "domain": _as_text(item.get("topic")) or "geo_concept",
                    "topic": _as_text(item.get("topic")) or "geo_concept",
                    "region": _as_text(item.get("region")),
                    "time": _as_text(item.get("time")),
                    "keywords": _normalize_keywords(item.get("keywords")) or _normalize_keywords(item.get("tags")),
                    "tags": _normalize_keywords(item.get("keywords")) or _normalize_keywords(item.get("tags")),
                    "summary": _as_text(item.get("summary")),
                    "canonical_answer": _as_text(item.get("canonical_answer")) or _as_text(item.get("summary")),
                    "teaching_points": _safe_list(item.get("teaching_points")),
                    "citations": _normalize_citations(item.get("citations")),
                    "related_templates": _safe_list(item.get("related_templates")),
                    "updated_at": _as_text(item.get("updated_at")),
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
                "topic": _as_text(row.get("topic")) or _as_text(row.get("domain")) or "geo_concept",
                "region": _as_text(row.get("region")),
                "time": _as_text(row.get("time")),
                "keywords": _normalize_keywords(row.get("keywords")) or _normalize_keywords(row.get("tags")),
                "tags": _normalize_keywords(row.get("tags")),
                "summary": _as_text(row.get("summary")),
                "canonical_answer": canonical,
                "teaching_points": [str(item).strip() for item in _safe_list(row.get("teaching_points")) if str(item).strip()],
                "citations": _normalize_citations(row.get("citations")),
                "related_templates": _safe_list(row.get("related_templates")),
                "updated_at": _as_text(row.get("updated_at")),
                "materials": _normalize_materials(row.get("materials")),
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
            # Reading legacy/imported rows must not fabricate a fresh edit
            # time. Mutation paths add a real timestamp before writing.
            "updated_at": _as_text(item.get("updated_at")),
            "owner_user_id": _as_text(item.get("owner_user_id")),
        }

    @staticmethod
    def _can_access_item(item: Dict[str, Any], owner_user_id: str, include_all: bool) -> bool:
        item_owner = _as_text(item.get("owner_user_id"))
        return include_all or not item_owner or (bool(owner_user_id) and item_owner == owner_user_id)

    def _load_geo_units(self) -> List[Dict[str, Any]]:
        if not self.geo_path.exists():
            return []
        try:
            payload = json.loads(self.geo_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return payload if isinstance(payload, list) else []

    def _load_manifest(self, create_if_missing: bool = False) -> Dict[str, Any]:
        fingerprint = self._fingerprint()
        if fingerprint != self._manifest_fingerprint or self._cached_manifest is None:
            self._cached_manifest = self._read_manifest(create_if_missing=create_if_missing)
            self._manifest_fingerprint = fingerprint
            self._engine_cache.clear()
            self._result_cache.clear()
        return self._cached_manifest

    def _read_manifest(self, create_if_missing: bool) -> Dict[str, Any]:
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
        # Any write (add/update/material/delete) must not leave stale rows
        # in the fingerprint cache, per-owner indexes or result cache.
        self._cached_manifest = None
        self._manifest_fingerprint = None
        self._engine_cache.clear()
        self._result_cache.clear()

    def _default_manifest(self) -> Dict[str, Any]:
        return {
            "version": "1.0",
            "updated_at": _utc_now(),
            "items": [],
        }
