"""Read-only, source-grounded profiles along a measured WGS84 line."""

from __future__ import annotations

import io
import math
import os
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple
from uuid import uuid4

from PIL import Image
from pyproj import Geod
from shapely.geometry import Point, shape


GEOD = Geod(ellps="WGS84")
GPW_COLLECTION = "sedac-popdensity-yeargrid5yr-v4.11"
GPW_ITEM = "sedac-popdensity-yeargrid5yr-v4.11-gpw_v4_population_density_rev11_2020_30_sec_2020"
GPW_POINT_URL = f"https://earth.gov/ghgcenter/api/raster/collections/{GPW_COLLECTION}/items/{GPW_ITEM}/point/"
TERRAIN_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium"
TERRAIN_ZOOM = 10
MAX_LENGTH_M = 2_000_000
TERRAIN_CACHE_WRITE_LOCK = threading.Lock()


class ProfileError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


def _line(coordinates: Sequence[Sequence[float]]) -> Tuple[List[Tuple[float, float]], List[float]]:
    if not 2 <= len(coordinates) <= 64:
        raise ProfileError("INVALID_LINE", "测线需要 2 至 64 个顶点。")
    vertices: List[Tuple[float, float]] = []
    for raw in coordinates:
        if len(raw) != 2 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in raw):
            raise ProfileError("INVALID_LINE", "测线坐标必须是有限的经纬度数值。")
        lon, lat = float(raw[0]), float(raw[1])
        if not -180 <= lon <= 180 or not -85 <= lat <= 85:
            raise ProfileError("INVALID_LINE", "测线须位于有效的 WGS84 经纬度范围。")
        vertices.append((lon, lat))
    distances = [0.0]
    for start, end in zip(vertices, vertices[1:]):
        if start == end:
            raise ProfileError("INVALID_LINE", "测线不能包含重复的相邻顶点。")
        if abs(end[0] - start[0]) > 180:
            raise ProfileError("INVALID_LINE", "跨越日期变更线的测线暂不支持剖面。")
        _, _, meters = GEOD.inv(*start, *end)
        distances.append(distances[-1] + meters)
    if distances[-1] < 1 or distances[-1] > MAX_LENGTH_M:
        raise ProfileError("INVALID_LINE", "测线长度须在 1 米至 2000 千米之间。")
    return vertices, distances


def _at(vertices: List[Tuple[float, float]], distances: List[float], meters: float) -> Tuple[float, float]:
    for index in range(len(distances) - 1):
        if meters <= distances[index + 1] or index == len(distances) - 2:
            start, end = vertices[index:index + 2]
            azimuth, _, _ = GEOD.inv(*start, *end)
            lon, lat, _ = GEOD.fwd(*start, azimuth, min(max(meters - distances[index], 0), distances[index + 1] - distances[index]))
            return round(lon, 7), round(lat, 7)
    return vertices[-1]


def _sample_points(vertices: List[Tuple[float, float]], distances: List[float], max_count: int) -> List[Dict[str, Any]]:
    total = distances[-1]
    count = min(max_count, max(2, math.ceil(total / 1_000) + 1))
    positions = sorted(set([total * i / (count - 1) for i in range(count)] + distances))
    return [{"distance_km": round(m / 1_000, 4), "lon": lon, "lat": lat, "value": None}
            for m in positions for lon, lat in [_at(vertices, distances, m)]]


def _fetch(url: str, max_bytes: int = 600_000) -> bytes:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "WebGIS-AI/1.0"}), timeout=12) as response:
            data = response.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise ProfileError("SOURCE_ERROR", "公开数据响应过大，已停止读取。", 503)
            return data
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ProfileError("SOURCE_UNAVAILABLE", "公开数据服务暂时不可用，请稍后重试。", 503) from exc


def _gpw_value(point: Dict[str, Any]) -> float | None:
    import json

    try:
        payload = json.loads(_fetch(f"{GPW_POINT_URL}{point['lon']},{point['lat']}?assets=population-density"))
    except (json.JSONDecodeError, TypeError) as exc:
        raise ProfileError("SOURCE_ERROR", "人口密度数据响应无效。", 503) from exc
    values = payload.get("values") or []
    value = values[0] if values else None
    return round(float(value), 3) if isinstance(value, (int, float)) and math.isfinite(value) and value >= 0 else None


def _terrain_value(point: Dict[str, Any], cache_root: Path) -> float | None:
    lon, lat = point["lon"], point["lat"]
    n = 2 ** TERRAIN_ZOOM
    tx = (lon + 180) / 360 * n
    lat_radians = math.radians(lat)
    ty = (1 - math.asinh(math.tan(lat_radians)) / math.pi) / 2 * n
    x, y = min(n - 1, max(0, int(tx))), min(n - 1, max(0, int(ty)))
    path = cache_root / "terrain" / str(TERRAIN_ZOOM) / str(x) / f"{y}.png"
    if not path.exists():
        with TERRAIN_CACHE_WRITE_LOCK:
            if not path.exists():
                data = _fetch(f"{TERRAIN_URL}/{TERRAIN_ZOOM}/{x}/{y}.png")
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_name(f"{path.stem}-{uuid4().hex}.tmp")
                try:
                    temporary.write_bytes(data)
                    os.replace(temporary, path)
                finally:
                    temporary.unlink(missing_ok=True)
    data = path.read_bytes()
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.size != (256, 256):
                raise ValueError("unexpected terrain tile size")
            red, green, blue = image.convert("RGB").getpixel((min(255, int((tx - x) * 256)), min(255, int((ty - y) * 256))))
    except (OSError, ValueError) as exc:
        raise ProfileError("SOURCE_ERROR", "高程瓦片无法解码。", 503) from exc
    return round(red * 256 + green + blue / 256 - 32768, 2)


def _polygon_profile(project: Any, source_id: str, vertices: List[Tuple[float, float]], distances: List[float]) -> Dict[str, Any]:
    layer = next((item for item in project.layers if item.layer_id == source_id and item.visible), None)
    if layer is None or layer.kind != "vector" or "Polygon" not in layer.geometry_type:
        raise ProfileError("INVALID_SOURCE", "请选择当前可见的人口密度面图层。")
    features = []
    for feature in layer.data.get("features", []):
        properties = feature.get("properties") or {}
        value = properties.get("density")
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            continue
        geometry = shape(feature.get("geometry"))
        if geometry.geom_type not in {"Polygon", "MultiPolygon"}:
            continue
        features.append((geometry, float(value), str(properties.get("name") or "")))
    if not features:
        raise ProfileError("INVALID_SOURCE", "所选图层没有可用于剖面的有效人口密度属性。")

    # Densify the geodesic before intersection. A long WGS84 segment is not a
    # straight line in lon/lat, especially away from the equator.
    from shapely.geometry import LineString as ShapeLine
    stops = set(distances)
    for step in range(1, math.ceil(distances[-1] / 5_000)):
        stops.add(min(distances[-1], step * 5_000.0))
    track_distances = sorted(stops)
    track_vertices = [_at(vertices, distances, position) for position in track_distances]
    boundaries = set(distances)
    for index, (start, end) in enumerate(zip(track_vertices, track_vertices[1:])):
        segment = ShapeLine([start, end])
        for geometry, _, _ in features:
            crossing = segment.intersection(geometry.boundary)
            stack = [crossing]
            while stack:
                part = stack.pop()
                if part.is_empty:
                    continue
                if hasattr(part, "geoms"):
                    stack.extend(part.geoms)
                elif part.geom_type == "Point":
                    fraction = max(0.0, min(1.0, segment.project(part) / segment.length))
                    boundaries.add(track_distances[index] + fraction * (track_distances[index + 1] - track_distances[index]))
                elif part.geom_type == "LineString":
                    for coordinate in (part.coords[0], part.coords[-1]):
                        fraction = max(0.0, min(1.0, segment.project(Point(coordinate)) / segment.length))
                        boundaries.add(track_distances[index] + fraction * (track_distances[index + 1] - track_distances[index]))
    boundaries = sorted(boundaries)
    if len(boundaries) > 402:
        raise ProfileError("TOO_COMPLEX", "测线穿越边界过多，请缩短测线。")
    samples = []
    for left, right in zip(boundaries, boundaries[1:]):
        midpoint = Point(_at(vertices, distances, (left + right) / 2))
        match = next(((value, name) for geometry, value, name in features if geometry.covers(midpoint)), (None, "无数据"))
        for position in (left, right):
            lon, lat = _at(vertices, distances, position)
            samples.append({"distance_km": round(position / 1_000, 4), "lon": lon, "lat": lat,
                            "value": match[0], "label": match[1]})
    return {"samples": samples, "source_name": layer.name,
            "source_year": str(layer.metadata.get("source_year") or "未标明"),
            "sampling": "行政区边界分段；区内为区域平均密度", "resolution_m": None,
            "source_url": None}


def preview(project: Any, coordinates: Sequence[Sequence[float]], kind: str, source_id: str, cache_root: Path) -> Dict[str, Any]:
    vertices, distances = _line(coordinates)
    if kind == "population" and source_id == "gpw_2020":
        samples = _sample_points(vertices, distances, 121)
        with ThreadPoolExecutor(max_workers=8) as pool:
            values = list(pool.map(_gpw_value, samples))
        for point, value in zip(samples, values):
            point["value"] = value
        details = {"samples": samples, "source_name": "NASA SEDAC GPWv4.11 人口密度", "source_year": "2020",
                   "sampling": "原始 30 角秒栅格最近邻取值", "resolution_m": 1000,
                   "source_url": "https://us-ghg-center.github.io/ghgc-docs/user_data_notebooks/sedac-popdensity-yeargrid5yr-v4.11_User_Notebook.html"}
        unit = "人/km²"
    elif kind == "population":
        details = _polygon_profile(project, source_id, vertices, distances)
        unit = "人/km²"
    elif kind == "terrain" and source_id == "mapzen_terrain":
        samples = _sample_points(vertices, distances, 241)
        with ThreadPoolExecutor(max_workers=8) as pool:
            values = list(pool.map(lambda point: _terrain_value(point, cache_root), samples))
        for point, value in zip(samples, values):
            point["value"] = value
        details = {"samples": samples, "source_name": "Mapzen Terrain Tiles（多源全球 DEM）",
                   "source_year": "不同地区来源年份不同", "sampling": "Web Mercator z10 瓦片最近邻取值",
                   "resolution_m": round(156543.0339 * math.cos(math.radians((vertices[0][1] + vertices[-1][1]) / 2)) / 2 ** TERRAIN_ZOOM),
                   "source_url": "https://github.com/tilezen/joerd/blob/master/docs/attribution.md"}
        unit = "米"
    else:
        raise ProfileError("INVALID_SOURCE", "不支持所选剖面数据源。")
    samples = details["samples"]
    return {"kind": kind, "source_id": source_id, "unit": unit,
            "total_distance_km": round(distances[-1] / 1_000, 4),
            "sample_spacing_m": None if kind == "population" and source_id != "gpw_2020" else round(distances[-1] / max(1, len(samples) - 1), 1),
            "no_data_count": sum(point["value"] is None for point in samples), **details}
