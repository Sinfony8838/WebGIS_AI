from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any, Dict, List

from ..config import AppConfig
from .knowledge_base import KnowledgeBaseService


AUTHORITY_SOURCES = (
    {
        "title": "NASA Earthdata",
        "url": "https://www.earthdata.nasa.gov/",
        "tags": ("remote sensing", "遥感", "气候", "地球观测", "satellite"),
    },
    {
        "title": "USGS Science Explorer",
        "url": "https://www.usgs.gov/",
        "tags": ("地质", "地形", "地震", "水文", "land", "geology"),
    },
    {
        "title": "NOAA Climate.gov",
        "url": "https://www.climate.gov/",
        "tags": ("气候", "海洋", "天气", "climate", "ocean"),
    },
    {
        "title": "World Bank Data",
        "url": "https://data.worldbank.org/",
        "tags": ("人口", "经济", "城市", "发展", "population", "economy"),
    },
    {
        "title": "UN Data",
        "url": "https://data.un.org/",
        "tags": ("人口", "区域", "国家", "社会", "un"),
    },
    {
        "title": "FAO Data",
        "url": "https://www.fao.org/faostat/",
        "tags": ("农业", "粮食", "土地利用", "fao"),
    },
)


def _as_text(value: Any) -> str:
    return str(value or "").strip()


class ResourceSearchService:
    def __init__(self, config: AppConfig, knowledge_base: KnowledgeBaseService):
        self.config = config
        self.knowledge_base = knowledge_base

    def search(self, query: str = "", scope: str = "all", limit: int = 12) -> Dict[str, Any]:
        normalized_scope = scope if scope in {"all", "kb", "web", "materials"} else "all"
        max_limit = max(1, min(int(limit or 12), 50))
        results: List[Dict[str, Any]] = []
        trace: List[Dict[str, str]] = []

        if normalized_scope in {"all", "kb"}:
            kb_results = self._search_kb(query, max_limit)
            results.extend(kb_results)
            trace.append({"source": "kb", "status": "success", "count": str(len(kb_results))})

        if normalized_scope in {"all", "materials"}:
            material_results = self._search_materials(query, max_limit)
            results.extend(material_results)
            trace.append({"source": "materials", "status": "success", "count": str(len(material_results))})

        if normalized_scope in {"all", "web"}:
            try:
                web_results = self._search_web(query, max_limit)
                results.extend(web_results)
                trace.append({"source": "web", "status": "success", "count": str(len(web_results))})
            except Exception as exc:  # pragma: no cover - network/config defensive branch
                trace.append({"source": "web", "status": "error", "detail": str(exc)})

        deduped = self._dedupe(results)
        return {
            "status": "success",
            "query": query,
            "scope": normalized_scope,
            "total": len(deduped),
            "items": deduped[:max_limit],
            "trace": trace,
        }

    def _search_kb(self, query: str, limit: int) -> List[Dict[str, Any]]:
        payload = self.knowledge_base.search(query=query, limit=limit)
        rows = []
        for item in payload.get("items", []):
            title = _as_text(item.get("title"))
            rows.append(
                {
                    "id": f"kb:{item.get('id')}",
                    "title": title,
                    "source": "knowledge_base",
                    "type": "knowledge",
                    "summary": _as_text(item.get("summary") or item.get("canonical_answer")),
                    "url": "",
                    "thumbnail_url": "",
                    "citations": item.get("citations", []),
                    "confidence": 0.86,
                    "kb_item": item,
                }
            )
        return rows

    def _search_materials(self, query: str, limit: int) -> List[Dict[str, Any]]:
        terms = [part.lower() for part in query.split() if part.strip()]
        rows = []
        manifest = self.knowledge_base.get_manifest()
        for item in manifest.get("items", []):
            for material in item.get("materials", []):
                haystack = " ".join(
                    [
                        _as_text(material.get("title")),
                        _as_text(material.get("description")),
                        _as_text(item.get("title")),
                        _as_text(item.get("region")),
                        json.dumps(material.get("region_binding", {}), ensure_ascii=False),
                    ]
                ).lower()
                if terms and not all(term in haystack for term in terms):
                    continue
                rows.append(
                    {
                        "id": f"material:{material.get('id')}",
                        "title": _as_text(material.get("title")),
                        "source": _as_text(material.get("source")) or "material",
                        "type": _as_text(material.get("type")) or "material",
                        "summary": _as_text(material.get("description") or item.get("summary")),
                        "url": _as_text(material.get("url")),
                        "thumbnail_url": _as_text(material.get("thumbnail_url")),
                        "citations": item.get("citations", []),
                        "confidence": 0.9,
                        "material": material,
                        "kb_item": item,
                    }
                )
                if len(rows) >= limit:
                    return rows
        return rows

    def _search_web(self, query: str, limit: int) -> List[Dict[str, Any]]:
        if self.config.resource_search_endpoint.strip():
            return self._search_web_endpoint(query, limit)
        return self._authority_suggestions(query, limit)

    def _search_web_endpoint(self, query: str, limit: int) -> List[Dict[str, Any]]:
        params = urllib.parse.urlencode({"q": query, "limit": str(limit)})
        url = f"{self.config.resource_search_endpoint.rstrip('?&')}?{params}"
        request = urllib.request.Request(url, headers={"User-Agent": "WebGIS-AI/1.1"})
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
        raw_items = payload.get("items") if isinstance(payload, dict) else payload
        rows = []
        for index, item in enumerate(raw_items if isinstance(raw_items, list) else []):
            if not isinstance(item, dict):
                continue
            item_url = _as_text(item.get("url"))
            if not self._is_allowed_url(item_url):
                continue
            rows.append(
                {
                    "id": _as_text(item.get("id")) or f"web:{index}:{item_url}",
                    "title": _as_text(item.get("title")) or item_url,
                    "source": "web",
                    "type": "web",
                    "summary": _as_text(item.get("summary") or item.get("snippet")),
                    "url": item_url,
                    "thumbnail_url": _as_text(item.get("thumbnail_url")),
                    "citations": [{"title": _as_text(item.get("title")) or item_url, "url": item_url}],
                    "confidence": float(item.get("confidence") or 0.62),
                }
            )
        return rows

    def _authority_suggestions(self, query: str, limit: int) -> List[Dict[str, Any]]:
        lowered = query.lower()
        rows = []
        for source in AUTHORITY_SOURCES:
            tags = source["tags"]
            score = 0.64 if not lowered else 0.58
            if lowered and any(str(tag).lower() in lowered or lowered in str(tag).lower() for tag in tags):
                score = 0.72
            rows.append(
                {
                    "id": f"web:{source['title']}",
                    "title": f"{source['title']}：{query or '地理资料'}",
                    "source": "authoritative_web",
                    "type": "web",
                    "summary": "权威在线资料入口。课堂中建议打开后核对最新数据、图表或说明，再写入知识库。",
                    "url": source["url"],
                    "thumbnail_url": "",
                    "citations": [{"title": source["title"], "url": source["url"]}],
                    "confidence": score,
                }
            )
        rows.sort(key=lambda item: float(item["confidence"]), reverse=True)
        return rows[:limit]

    def _is_allowed_url(self, url: str) -> bool:
        lowered = url.lower()
        return any(
            domain in lowered
            for domain in (
                ".gov",
                ".edu",
                "nasa.gov",
                "noaa.gov",
                "usgs.gov",
                "wmo.int",
                "fao.org",
                "worldbank.org",
                "un.org",
                "data.un.org",
            )
        )

    def _dedupe(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        deduped = []
        seen = set()
        for row in rows:
            key = row.get("url") or row.get("id") or row.get("title")
            if key in seen:
                continue
            seen.add(key)
            deduped.append(row)
        deduped.sort(key=lambda item: float(item.get("confidence") or 0), reverse=True)
        return deduped
