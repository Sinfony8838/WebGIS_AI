from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import AppConfig
from ..store import RuntimeStore
from .knowledge_base import KnowledgeBaseService
from .one_map_catalog import OneMapCatalogService


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _safe_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


class PopulationSourceRegistryService:
    """Versioned, read-only evidence inventory for the population unit.

    Version manifests are source-controlled.  A project only persists the
    selected version id, so activating or rolling back a pack never rewrites
    the bundled datasets or knowledge manifest.
    """

    PROJECT_VERSION_KEY = "active_population_source_version"

    def __init__(
        self,
        config: AppConfig,
        store: RuntimeStore,
        catalog: OneMapCatalogService,
        knowledge_base: KnowledgeBaseService,
    ):
        self.config = config
        self.store = store
        self.catalog = catalog
        self.knowledge_base = knowledge_base
        self.root = self.config.builtin_dir / "population_sources"
        self.index_path = self.root / "index.json"

    def list_versions(self, project_id: str = "") -> Dict[str, Any]:
        index = self._load_index()
        active_version = self.resolve_version(project_id=project_id)
        return {
            "status": "success",
            "active_version": active_version,
            "versions": list(index["versions"]),
        }

    def resolve_version(self, project_id: str = "", version: str = "") -> str:
        index = self._load_index()
        available = {str(item.get("version") or "") for item in index["versions"]}
        requested = str(version or "").strip()
        if requested:
            if requested not in available:
                raise KeyError(f"Unknown population source version: {requested}")
            return requested
        if project_id:
            project = self.store.get_project(project_id)
            if project is None:
                raise KeyError(f"Unknown project: {project_id}")
            selected = str((project.metadata or {}).get(self.PROJECT_VERSION_KEY) or "")
            if selected in available:
                return selected
        default_version = str(index.get("active_version") or "")
        if default_version not in available:
            raise ValueError("Population source index has no valid active version")
        return default_version

    def activate_version(self, project_id: str, version: str) -> Dict[str, Any]:
        selected = self.resolve_version(version=version)
        project = self.store.get_project(project_id)
        if project is None:
            raise KeyError(f"Unknown project: {project_id}")
        project.metadata[self.PROJECT_VERSION_KEY] = selected
        self.store.save_project(project)
        payload = self.list_sources(project_id=project_id, version=selected)
        return {
            "status": "success",
            "project_id": project_id,
            "active_version": selected,
            "pack_fingerprint": payload["pack_fingerprint"],
        }

    def list_sources(self, project_id: str = "", version: str = "") -> Dict[str, Any]:
        selected = self.resolve_version(project_id=project_id, version=version)
        manifest = self._load_version_manifest(selected)
        cards = [self._normalize_card(item, selected) for item in _safe_list(manifest.get("items")) if isinstance(item, dict)]
        cards.sort(key=lambda item: (int(item.get("sort_order") or 0), str(item.get("title") or "")))
        pack_fingerprint = _sha256(_canonical_json([card["fingerprint"] for card in cards]))
        return {
            "status": "success",
            "version": selected,
            "title": str(manifest.get("title") or "人口地理来源包"),
            "released_at": str(manifest.get("released_at") or ""),
            "pack_fingerprint": pack_fingerprint,
            "items": cards,
        }

    def compare_versions(self, from_version: str, to_version: str) -> Dict[str, Any]:
        before = self.list_sources(version=from_version)
        after = self.list_sources(version=to_version)
        before_by_id = {item["id"]: item for item in before["items"]}
        after_by_id = {item["id"]: item for item in after["items"]}
        before_ids = set(before_by_id)
        after_ids = set(after_by_id)
        changed = sorted(
            source_id
            for source_id in before_ids.intersection(after_ids)
            if before_by_id[source_id]["fingerprint"] != after_by_id[source_id]["fingerprint"]
        )
        return {
            "status": "success",
            "from_version": before["version"],
            "to_version": after["version"],
            "added": sorted(after_ids - before_ids),
            "removed": sorted(before_ids - after_ids),
            "changed": changed,
            "unchanged": sorted(before_ids.intersection(after_ids) - set(changed)),
            "from_pack_fingerprint": before["pack_fingerprint"],
            "to_pack_fingerprint": after["pack_fingerprint"],
        }

    def get_source(
        self,
        source_id: str,
        project_id: str = "",
        version: str = "",
        expected_fingerprint: str = "",
    ) -> Dict[str, Any]:
        payload = self.list_sources(project_id=project_id, version=version)
        target = str(source_id or "").strip()
        for card in payload["items"]:
            if card["id"] != target:
                continue
            expected = str(expected_fingerprint or "").strip()
            return {
                "status": "success",
                "version": payload["version"],
                "pack_fingerprint": payload["pack_fingerprint"],
                "drifted": bool(expected and expected != card["fingerprint"]),
                "item": card,
            }
        raise KeyError(f"Unknown population source: {source_id}")

    def validate_references(
        self,
        references: Any,
        project_id: str = "",
        version: str = "",
    ) -> Dict[str, Any]:
        payload = self.list_sources(project_id=project_id, version=version)
        by_id = {item["id"]: item for item in payload["items"]}
        valid: List[Dict[str, Any]] = []
        missing: List[str] = []
        drifted: List[Dict[str, str]] = []
        for raw in _safe_list(references):
            if isinstance(raw, str):
                source_id = raw
                expected = ""
            elif isinstance(raw, dict):
                source_id = str(raw.get("source_id") or raw.get("id") or "")
                expected = str(raw.get("fingerprint") or "")
            else:
                continue
            card = by_id.get(source_id)
            if card is None:
                missing.append(source_id)
                continue
            if expected and expected != card["fingerprint"]:
                drifted.append(
                    {
                        "source_id": source_id,
                        "expected_fingerprint": expected,
                        "current_fingerprint": card["fingerprint"],
                    }
                )
            valid.append(self.reference_for(card))
        return {
            "status": "success" if not missing else "invalid",
            "version": payload["version"],
            "pack_fingerprint": payload["pack_fingerprint"],
            "valid": valid,
            "missing": missing,
            "drifted": drifted,
        }

    @staticmethod
    def reference_for(card: Dict[str, Any]) -> Dict[str, str]:
        return {
            "source_id": str(card.get("id") or ""),
            "title": str(card.get("title") or ""),
            "source_year": str(card.get("source_year") or ""),
            "fingerprint": str(card.get("fingerprint") or ""),
        }

    def _load_index(self) -> Dict[str, Any]:
        try:
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ValueError("Population source index is missing") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Population source index is invalid") from exc
        versions = [item for item in _safe_list(payload.get("versions")) if isinstance(item, dict)]
        if not versions:
            raise ValueError("Population source index declares no versions")
        return {
            "active_version": str(payload.get("active_version") or ""),
            "versions": versions,
        }

    def _load_version_manifest(self, version: str) -> Dict[str, Any]:
        index = self._load_index()
        record = next((item for item in index["versions"] if str(item.get("version") or "") == version), None)
        if record is None:
            raise KeyError(f"Unknown population source version: {version}")
        relative = str(record.get("manifest") or "")
        path = (self.root / relative).resolve()
        try:
            path.relative_to(self.root.resolve())
        except ValueError as exc:
            raise ValueError("Population source manifest escapes the builtin directory") from exc
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ValueError("Population source manifest is missing") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Population source manifest is invalid") from exc
        if str(payload.get("version") or "") != version:
            raise ValueError("Population source manifest version mismatch")
        return payload

    def _normalize_card(self, raw: Dict[str, Any], version: str) -> Dict[str, Any]:
        source_type = str(raw.get("source_type") or "").strip()
        dataset_id = str(raw.get("dataset_id") or "").strip()
        knowledge_id = str(raw.get("knowledge_id") or "").strip()
        lesson_id = str(raw.get("lesson_id") or "").strip()
        base: Dict[str, Any] = {}
        content_payload: Any = {}

        if source_type == "dataset":
            base = self.catalog.get_item(dataset_id)
            path = self.catalog.resolve_item_path(base)
            content_payload = path.read_bytes()
        elif source_type == "knowledge":
            manifest = self.knowledge_base.get_manifest()
            items = [item for item in _safe_list(manifest.get("items")) if isinstance(item, dict)]
            base = next((item for item in items if str(item.get("id") or "") == knowledge_id), {})
            if not base:
                raise ValueError(f"Population source references unknown knowledge item: {knowledge_id}")
            content_payload = base
        elif source_type == "lesson":
            lesson_path = self.config.builtin_dir / "lessons" / f"{lesson_id.removeprefix('lesson_builtin_')}_lesson.json"
            if not lesson_path.exists() and lesson_id == "lesson_builtin_population_distribution":
                lesson_path = self.config.builtin_dir / "lessons" / "population_distribution_lesson.json"
            try:
                base = json.loads(lesson_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"Population source references unreadable lesson: {lesson_id}") from exc
            content_payload = base
        else:
            raise ValueError(f"Unsupported population source type: {source_type}")

        source_id = str(raw.get("id") or "").strip()
        if not source_id:
            raise ValueError("Population source card requires id")
        source_name = str(raw.get("source_name") or base.get("source_name") or base.get("source") or "")
        source_year = str(raw.get("source_year") or base.get("source_year") or base.get("time") or "")
        source_url = str(raw.get("source_url") or base.get("source_url") or "")
        citations = [item for item in _safe_list(base.get("citations")) if isinstance(item, dict)]
        if not source_url and citations:
            source_url = str(citations[0].get("url") or "")
        license_name = str(raw.get("license") or base.get("license") or "unknown")
        status = str(raw.get("status") or base.get("status") or "ready")
        fields = [str(item) for item in _safe_list(base.get("fields"))]
        field_unit = str(raw.get("field_unit") or "")
        if not field_unit and any(field in {"density", "population_density"} for field in fields):
            field_unit = "人/平方千米"
        if not field_unit and any(field in {"population", "migrants"} for field in fields):
            field_unit = "人"

        resource_hash = _sha256(content_payload if isinstance(content_payload, bytes) else _canonical_json(content_payload))
        normalized = {
            "id": source_id,
            "title": str(raw.get("title") or base.get("name") or base.get("title") or source_id),
            "source_type": source_type,
            "source_name": source_name,
            "source_url": source_url,
            "source_year": source_year,
            "spatial_scale": str(raw.get("spatial_scale") or base.get("coverage") or base.get("region") or ""),
            "field_unit": field_unit,
            "license": license_name,
            "status": status,
            "dataset_id": dataset_id,
            "knowledge_id": knowledge_id,
            "lesson_id": lesson_id,
            "version": version,
            "teaching_usage": [str(item) for item in _safe_list(raw.get("teaching_usage"))],
            "limitations": [str(item) for item in _safe_list(raw.get("limitations"))],
            "summary": str(raw.get("summary") or base.get("summary") or base.get("description") or ""),
            "canonical_answer": str(base.get("canonical_answer") or ""),
            "teaching_points": [str(item) for item in _safe_list(base.get("teaching_points"))],
            "fields": fields,
            "resource_fingerprint": resource_hash,
            "sort_order": int(raw.get("sort_order") or 0),
        }
        fingerprint_payload = {key: value for key, value in normalized.items() if key != "version"}
        normalized["fingerprint"] = _sha256(_canonical_json(fingerprint_payload))
        return normalized
