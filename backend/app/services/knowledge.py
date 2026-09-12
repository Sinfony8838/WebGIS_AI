"""Local knowledge base: teaching cards used to ground assistant answers.

Cards live in ``backend/app/data/builtin/knowledge/kb_manifest.json``.
Search runs through the shared :mod:`knowledge_retrieval` engine so the
assistant's evidence path follows the same normalization, Chinese
matching, region/year/metric constraints and insufficient-evidence
threshold as ``KnowledgeBaseService``. The manifest is cached per file
fingerprint and invalidated automatically when the file changes.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from ..config import AppConfig
from .knowledge_retrieval import RetrievalDoc, RetrievalEngine

INSUFFICIENT_MESSAGE = "内置知识卡片中没有找到与该问题匹配的资料。"


class KnowledgeService:
    def __init__(self, config: AppConfig):
        self.config = config
        self.manifest_path = config.builtin_dir / "knowledge" / "kb_manifest.json"
        self._cache_fingerprint: tuple[int, int] | None = None
        self._cached_items: List[Dict[str, Any]] = []
        self._engine: RetrievalEngine | None = None

    def load_manifest(self) -> Dict[str, Any]:
        try:
            payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": "1.0", "items": []}
        if not isinstance(payload, dict):
            return {"version": "1.0", "items": []}
        payload.setdefault("items", [])
        return payload

    def list_items(self) -> List[Dict[str, Any]]:
        fingerprint = self._fingerprint()
        if fingerprint != self._cache_fingerprint:
            self._cached_items = [
                item for item in self.load_manifest().get("items", []) if isinstance(item, dict)
            ]
            self._cache_fingerprint = fingerprint
            self._engine = None
        return list(self._cached_items)

    def search(self, query: str, limit: int = 3) -> List[Dict[str, Any]]:
        """Return matching builtin cards, or ``[]`` when evidence is weak.

        Natural Chinese questions are normalized and tokenized; region,
        year and metric constraints from the question are matched against
        each card's fields. A weak best match returns nothing so callers
        keep their own fallback instead of showing an off-topic card.
        """
        text = (query or "").strip()
        if not text:
            return []
        engine = self._get_engine()
        result = engine.search(text, limit=max(1, limit))
        if result.insufficient:
            return []
        by_id = {str(item.get("id")): item for item in self.list_items()}
        cards: List[Dict[str, Any]] = []
        for hit in result.hits:
            item = by_id.get(hit.doc_id)
            if item is None:
                continue
            card = dict(item)
            card["retrieval_score"] = round(hit.score, 4)
            card["retrieval_insufficient"] = False
            cards.append(card)
        return cards

    def _get_engine(self) -> RetrievalEngine:
        self.list_items()  # refresh cache if the manifest changed on disk
        if self._engine is None:
            docs = [RetrievalDoc.from_mapping(item) for item in self._cached_items]
            self._engine = RetrievalEngine(docs)
        return self._engine

    def _fingerprint(self) -> tuple[int, int]:
        try:
            stat = self.manifest_path.stat()
            return (stat.st_mtime_ns, stat.st_size)
        except OSError:
            return (0, 0)
