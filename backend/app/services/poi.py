from __future__ import annotations

import json
from typing import Any, Callable, Dict, Iterable, List, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..config import AppConfig
from ..models import LayerRecord
from ..store import RuntimeStore


JsonFetcher = Callable[[str], Dict[str, Any]]


class PoiService:
    def __init__(self, config: AppConfig, store: RuntimeStore, fetch_json: Optional[JsonFetcher] = None):
        self.config = config
        self.store = store
        self.fetch_json = fetch_json or self._fetch_json

    def search(
        self,
        project_id: str,
        keyword: str,
        mode: str = "view",
        extent: Optional[Iterable[float]] = None,
        geometry: Optional[Dict[str, Any]] = None,
        page: int = 1,
        offset: int = 10,
    ) -> Dict[str, Any]:
        if not keyword.strip():
            raise ValueError("POI search keyword cannot be empty")
        if not self.config.online_services_enabled():
            raise ValueError("AMap POI search is not configured. Set WEBGIS_AI_AMAP_WEB_SERVICE_KEY first.")

        polygon = self._build_polygon_param(mode=mode, extent=extent, geometry=geometry)
        params = {
            "key": self.config.amap_web_service_key,
            "keywords": keyword.strip(),
            "polygon": polygon,
            "offset": max(1, min(int(offset), 25)),
            "page": max(1, min(int(page), 100)),
            "output": "JSON",
            "extensions": "base",
        }
        url = f"{self.config.amap_poi_polygon_url}?{urlencode(params)}"
        payload = self.fetch_json(url)
        if str(payload.get("status")) != "1":
            raise ValueError(str(payload.get("info") or "AMap POI search failed"))

        pois = payload.get("pois") or []
        items = [
            normalized
            for index, item in enumerate(pois, start=1)
            for normalized in [self._normalize_poi_item(item, index)]
            if normalized is not None
        ]
        collection = {
            "type": "FeatureCollection",
            "features": [self._poi_to_feature(item) for item in items],
        }
        layer = LayerRecord.create(
            layer_id="poi_search_results",
            name=f"POI：{keyword.strip()}",
            kind="vector",
            source="search",
            geometry_type="Point",
            data=collection,
            metadata={
                "provider": "amap",
                "keyword": keyword.strip(),
                "mode": mode,
                "result_count": len(items),
            },
            style={"labelField": "name", "radius": 8, "fillColor": "#f97316", "strokeColor": "#ffffff"},
            z_index=72,
        )
        self.store.upsert_layer(project_id, layer)
        self.store.set_active_layer(project_id, layer.layer_id)
        self.store.add_recent_action(
            project_id,
            "POI 检索",
            f"已搜索“{keyword.strip()}”并返回 {len(items)} 条结果",
            status="success",
            metadata={"layer_id": layer.layer_id, "mode": mode},
        )
        return {
            "status": "success",
            "keyword": keyword.strip(),
            "mode": mode,
            "items": items,
            "layer": layer.to_dict(),
            "summary": self._build_summary(keyword.strip(), items),
        }

    def _build_polygon_param(
        self,
        mode: str,
        extent: Optional[Iterable[float]],
        geometry: Optional[Dict[str, Any]],
    ) -> str:
        if mode == "polygon":
            coordinates = (((geometry or {}).get("coordinates") or [[]])[0]) if geometry else []
            if len(coordinates) < 4:
                raise ValueError("Polygon search requires a valid polygon geometry")
            points = [f"{float(point[0])},{float(point[1])}" for point in coordinates]
            if points[0] != points[-1]:
                points.append(points[0])
            return "|".join(points)

        values = [float(value) for value in (extent or [])]
        if len(values) != 4:
            raise ValueError("View search requires extent [west, south, east, north]")
        west, south, east, north = values
        return f"{west},{north}|{east},{south}"

    def _normalize_poi_item(self, item: Dict[str, Any], index: int) -> Optional[Dict[str, Any]]:
        location = str(item.get("location") or "").strip()
        if "," not in location:
            return None
        try:
            lng_text, lat_text = location.split(",", 1)
            longitude = float(lng_text)
            latitude = float(lat_text)
        except ValueError:
            return None
        if not (-180.0 <= longitude <= 180.0 and -90.0 <= latitude <= 90.0):
            return None
        return {
            "poi_id": str(item.get("id") or f"poi_{index}"),
            "name": str(item.get("name") or f"POI {index}"),
            "address": str(item.get("address") or ""),
            "type": str(item.get("type") or ""),
            "district": str(item.get("adname") or item.get("pname") or ""),
            "city": str(item.get("cityname") or ""),
            "location": [longitude, latitude],
        }

    def _poi_to_feature(self, item: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "type": "Feature",
            "properties": {
                "poi_id": item["poi_id"],
                "name": item["name"],
                "address": item["address"],
                "type": item["type"],
                "district": item["district"],
                "city": item["city"],
                "__fillColor": "#f97316",
                "__strokeColor": "#fff7ed",
                "__radius": 8,
            },
            "geometry": {"type": "Point", "coordinates": item["location"]},
        }

    def _build_summary(self, keyword: str, items: List[Dict[str, Any]]) -> str:
        if not items:
            return f"未在当前范围内检索到“{keyword}”相关结果。"
        top_names = "、".join(item["name"] for item in items[:3])
        return f"已检索到 {len(items)} 条“{keyword}”结果，靠前结果包括：{top_names}。"

    def _fetch_json(self, url: str) -> Dict[str, Any]:
        request = Request(url, headers={"User-Agent": "WebGIS-AI/1.1"})
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
