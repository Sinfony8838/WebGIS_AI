"""Structured metric query service that turns natural-language requests
into a highlightable map layer plus a bar chart payload.

The first version covers one dataset (``prefecture_population``) and a
single ranking query (``top``).  New datasets or operations can be added
by extending ``_DISPATCH`` without touching the rest of the pipeline.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..config import AppConfig
from ..models import LayerRecord


DEFAULT_DATASET = "prefecture_population"

# Parsed prefecture features cached by (path, mtime, size). Keeps in-class
# repeat queries instant instead of re-parsing the dataset each time.
_PREFECTURE_CACHE: Dict[Any, List[Dict[str, Any]]] = {}

DEFAULT_VIEW = {
    "center": [104.0, 35.0],
    "zoom": 4,
    "extent": [73.0, 18.0, 135.0, 54.0],
}

# Layer naming helpers
LAYER_ID_TEMPLATE = "visual_query_{dataset}_{year}_{operation}{suffix}"
LAYER_NAME_TEMPLATE = "{year}年{geo_level_label}{metric_label}{operation_label}{limit_label}"


@dataclass
class VisualQueryResult:
    title: str
    summary: str
    items: List[Dict[str, Any]]
    layer: LayerRecord
    visualization: Dict[str, Any]
    view: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "summary": self.summary,
            "items": list(self.items),
            "layer": self.layer.to_dict(),
            "visualization": dict(self.visualization),
            "view": dict(self.view),
        }


class VisualQueryError(ValueError):
    """Raised when the query parameters cannot be handled."""


class VisualQueryService:
    def __init__(self, config: AppConfig):
        self.config = config

    def run(self, project_id: str, query: Dict[str, Any]) -> Dict[str, Any]:
        dataset = str(query.get("dataset") or DEFAULT_DATASET)
        handler = self._resolve_handler(dataset)
        result = handler(project_id, query)
        if not isinstance(result, VisualQueryResult):
            raise VisualQueryError(
                f"Visual query handler for {dataset!r} returned an invalid result"
            )
        return result.to_dict()

    # ------------------------------------------------------------------
    # Dataset dispatch
    # ------------------------------------------------------------------

    def _resolve_handler(self, dataset: str):
        if dataset == "prefecture_population":
            return self._run_prefecture_population
        raise VisualQueryError(f"Unsupported dataset: {dataset!r}")

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _run_prefecture_population(
        self,
        project_id: str,
        query: Dict[str, Any],
    ) -> VisualQueryResult:
        year = _coerce_int(query.get("year"), default=2020, minimum=1900, maximum=2100)
        geo_level = str(query.get("geo_level") or "prefecture")
        if geo_level != "prefecture":
            raise VisualQueryError(
                f"Only the 'prefecture' geo_level is currently supported, got {geo_level!r}"
            )
        metric = str(query.get("metric") or "population")
        if metric != "population":
            raise VisualQueryError(f"Unsupported metric: {metric!r}")
        operation = str(query.get("operation") or "top")
        if operation != "top":
            raise VisualQueryError(f"Unsupported operation: {operation!r}")
        order = str(query.get("order") or "desc").lower()
        if order not in {"asc", "desc"}:
            raise VisualQueryError(f"Unsupported order: {order!r}")
        limit = _coerce_int(query.get("limit"), default=20, minimum=1, maximum=200)

        records = self._load_prefecture_population(year)
        if not records:
            raise VisualQueryError(
                f"Visual query dataset for year {year} returned no records"
            )
        records_sorted = sorted(
            records,
            key=lambda r: (
                -float(r["properties"].get("population_2020") or 0)
                if order == "desc"
                else float(r["properties"].get("population_2020") or 0),
                str(r["properties"].get("name") or ""),
            ),
        )
        top_records = records_sorted[:limit]
        if not top_records:
            raise VisualQueryError("Visual query produced no items to display")

        palette = _rank_palette(len(top_records))
        items: List[Dict[str, Any]] = []
        highlighted_features: List[Dict[str, Any]] = []
        maximum_value = max(
            float(r["properties"].get("population_2020") or 0) for r in top_records
        ) or 1.0
        for index, record in enumerate(top_records, start=1):
            properties = dict(record["properties"])
            value = float(properties.get("population_2020") or 0)
            color = palette[index - 1]
            geometry = record.get("geometry") or {
                "type": "MultiPolygon",
                "coordinates": [],
            }
            if geometry.get("type") == "Polygon":
                geometry = {
                    "type": "MultiPolygon",
                    "coordinates": [geometry.get("coordinates", [])],
                }
            feature = {
                "type": "Feature",
                "properties": {
                    "name": properties.get("name"),
                    "province": properties.get("province"),
                    "adm_code": properties.get("adm_code"),
                    "rank": index,
                    "value": int(value),
                    "unit": properties.get("unit") or "人",
                    "__fillColor": color,
                    "__fillOpacity": 0.62,
                    "__strokeColor": "#fef3c7",
                    "__strokeWidth": 1.6,
                },
                "geometry": geometry,
            }
            highlighted_features.append(feature)
            items.append(
                {
                    "rank": index,
                    "name": properties.get("name"),
                    "province": properties.get("province"),
                    "value": int(value),
                    "unit": properties.get("unit") or "人",
                    "share": round(value / maximum_value, 4) if maximum_value else 0,
                    "fill_color": color,
                    "adm_code": properties.get("adm_code"),
                }
            )

        layer_id = LAYER_ID_TEMPLATE.format(
            dataset="prefecture_population",
            year=year,
            operation="top",
            suffix=f"{(order or 'desc')[:1]}{limit}",
        )
        layer_name = LAYER_NAME_TEMPLATE.format(
            year=year,
            geo_level_label="地级市",
            metric_label="人口",
            operation_label="Top" if order == "desc" else "Top（升序）",
            limit_label=str(limit),
        )
        max_extent = _compute_extent(highlighted_features) or DEFAULT_VIEW["extent"]
        center = _compute_centroid(highlighted_features) or DEFAULT_VIEW["center"]
        visualization = {
            "type": "bar",
            "x": "name",
            "y": "value",
            "unit": "人",
            "title": f"{year} 年地级市常住人口 Top-{limit}",
            "items": copy.deepcopy(items),
            "palette": palette[: len(items)],
            "maximum": int(maximum_value),
        }
        layer = LayerRecord.create(
            layer_id=layer_id,
            name=layer_name,
            kind="vector",
            source="generated",
            geometry_type="MultiPolygon",
            data={"type": "FeatureCollection", "features": highlighted_features},
            metadata={
                "query": dict(query),
                "year": year,
                "metric": metric,
                "operation": operation,
                "limit": limit,
                "order": order,
                "geo_level": geo_level,
                "dataset": "prefecture_population",
                "feature_count": len(highlighted_features),
                "unit": "人",
                "visualization": visualization,
            },
            style={"labelField": "name", "strokeColor": "#fef3c7", "strokeWidth": 1.4},
            z_index=80,
        )
        summary = (
            f"已生成 {year} 年地级市常住人口 Top-{limit}。"
            f"第一名为{items[0]['name']}，约 {items[0]['value']:,} 人；"
            f"第{len(items)}名为{items[-1]['name']}，约 {items[-1]['value']:,} 人。"
        )
        return VisualQueryResult(
            title=f"{year} 年地级市常住人口 Top-{limit}",
            summary=summary,
            items=items,
            layer=layer,
            visualization=visualization,
            view={
                "center": center,
                "zoom": DEFAULT_VIEW["zoom"],
                "extent": max_extent,
            },
        )

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_prefecture_population(self, year: int) -> List[Dict[str, Any]]:
        # Today the project ships with the 2020 census snapshot.  If more
        # years are added later, the loader can fan out to per-year files.
        if year != 2020:
            raise VisualQueryError(
                f"Visual query dataset for year {year} is not available in this build"
            )
        path = self._prefecture_population_path()
        if not path.exists():
            raise VisualQueryError(
                f"Visual query dataset is missing on disk: {path}. "
                "Run scripts/build_prefecture_population_2020.py first."
            )
        # Cache by (path, mtime) so repeated in-class queries never re-parse
        # the file. Handlers deep-copy features before mutating them.
        stat = path.stat()
        cache_key = (str(path), stat.st_mtime_ns, stat.st_size)
        cached = _PREFECTURE_CACHE.get(cache_key)
        if cached is None:
            payload = json.loads(path.read_text(encoding="utf-8"))
            cached = list(payload.get("features") or [])
            _PREFECTURE_CACHE.clear()
            _PREFECTURE_CACHE[cache_key] = cached
        return cached

    def _prefecture_population_path(self) -> Path:
        return self.config.builtin_dir / "population" / "prefecture_population_2020.geojson"


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _coerce_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    if value is None or value == "":
        return default
    try:
        result = int(round(float(value)))
    except (TypeError, ValueError) as exc:
        raise VisualQueryError(f"Expected an integer, got {value!r}") from exc
    if result < minimum or result > maximum:
        raise VisualQueryError(
            f"Value {result} is out of range [{minimum}, {maximum}]"
        )
    return result


def _rank_palette(count: int) -> List[str]:
    """Return a red-to-blue-ish palette for ranking visualisations."""
    base = [
        "#7f1d1d",
        "#b91c1c",
        "#dc2626",
        "#ef4444",
        "#f97316",
        "#fb923c",
        "#f59e0b",
        "#eab308",
        "#facc15",
        "#fde68a",
        "#bef264",
        "#86efac",
        "#4ade80",
        "#22c55e",
        "#16a34a",
        "#14b8a6",
        "#06b6d4",
        "#0ea5e9",
        "#3b82f6",
        "#6366f1",
    ]
    if count <= len(base):
        return base[:count]
    palette = list(base)
    while len(palette) < count:
        palette.append(base[len(palette) % len(base)])
    return palette


def _compute_extent(features: List[Dict[str, Any]]) -> Optional[List[float]]:
    min_lon = min_lat = float("inf")
    max_lon = max_lat = float("-inf")
    found = False
    for feature in features:
        coords = _iter_polygon_coords(feature.get("geometry"))
        for ring in coords:
            for point in ring:
                if not isinstance(point, (list, tuple)) or len(point) < 2:
                    continue
                lon, lat = point[0], point[1]
                if not isinstance(lon, (int, float)) or not isinstance(lat, (int, float)):
                    continue
                found = True
                min_lon = min(min_lon, lon)
                max_lon = max(max_lon, lon)
                min_lat = min(min_lat, lat)
                max_lat = max(max_lat, lat)
    if not found:
        return None
    pad_lon = max(0.5, (max_lon - min_lon) * 0.08)
    pad_lat = max(0.5, (max_lat - min_lat) * 0.08)
    return [
        max(-180.0, min_lon - pad_lon),
        max(-90.0, min_lat - pad_lat),
        min(180.0, max_lon + pad_lon),
        min(90.0, max_lat + pad_lat),
    ]


def _compute_centroid(features: List[Dict[str, Any]]) -> Optional[List[float]]:
    total_lon = 0.0
    total_lat = 0.0
    count = 0
    for feature in features:
        coords = _iter_polygon_coords(feature.get("geometry"))
        for ring in coords:
            for point in ring:
                if not isinstance(point, (list, tuple)) or len(point) < 2:
                    continue
                lon, lat = point[0], point[1]
                if not isinstance(lon, (int, float)) or not isinstance(lat, (int, float)):
                    continue
                total_lon += lon
                total_lat += lat
                count += 1
    if count == 0:
        return None
    return [round(total_lon / count, 4), round(total_lat / count, 4)]


def _iter_polygon_coords(geometry: Optional[Dict[str, Any]]):
    if not isinstance(geometry, dict):
        return
    geometry_type = geometry.get("type")
    if geometry_type == "Polygon":
        for ring in geometry.get("coordinates") or []:
            yield ring
    elif geometry_type == "MultiPolygon":
        for polygon in geometry.get("coordinates") or []:
            for ring in polygon or []:
                yield ring
