"""Local knowledge base: teaching cards used to ground assistant answers.

Cards live in ``backend/app/data/builtin/knowledge/kb_manifest.json``.
Search is a lightweight keyword-overlap scorer — good enough to pick the
2-3 cards that ground an LLM answer, with zero external dependencies.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from ..config import AppConfig


class KnowledgeService:
    def __init__(self, config: AppConfig):
        self.config = config
        self.manifest_path = config.builtin_dir / "knowledge" / "kb_manifest.json"

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
        return [item for item in self.load_manifest().get("items", []) if isinstance(item, dict)]

    def search(self, query: str, limit: int = 3) -> List[Dict[str, Any]]:
        text = (query or "").strip()
        if not text:
            return []
        lowered = text.lower()
        scored: List[tuple[float, Dict[str, Any]]] = []
        for item in self.list_items():
            score = 0.0
            title = str(item.get("title") or "")
            if title and title in text:
                score += 6.0
            for keyword in item.get("keywords", []):
                keyword = str(keyword)
                if keyword and (keyword in text or keyword.lower() in lowered):
                    score += 3.0
            topic = str(item.get("topic") or "")
            if topic and topic.lower() in lowered:
                score += 1.5
            summary = str(item.get("summary") or "")
            score += sum(1.0 for token in _tokens(text) if token and token in summary)
            if score > 0:
                scored.append((score, item))
        scored.sort(key=lambda pair: -pair[0])
        return [item for _, item in scored[: max(1, limit)]]


def _tokens(text: str) -> List[str]:
    # 中文场景下用 2 字滑窗近似分词，足够做卡片匹配。
    cleaned = "".join(ch for ch in text if ch.isalnum())
    if len(cleaned) < 2:
        return [cleaned]
    return [cleaned[i : i + 2] for i in range(len(cleaned) - 1)]
