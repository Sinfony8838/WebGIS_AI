"""Optional pyproj-backed reprojection of GeoJSON feature collections.

``pyproj`` is **not** a hard dependency. When it's unavailable, the
reprojection functions return the input unchanged plus a structured
warning so the upload pipeline can degrade gracefully — features end up
displayed using whatever CRS the uploader sent, and the user is told
they need pyproj to auto-convert non-WGS84 datasets.

This module is intentionally narrow: it only reprojects vector GeoJSON
geometries in-process. Heavier raster / PyQGIS reprojection lives in
the PyQGIS worker's :mod:`reproject` handler and is invoked through the
workflow pipeline, not here.
"""
from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# Cached pyproj presence flag (one importlib check per process).
_PYPROJ_AVAILABLE = importlib.util.find_spec("pyproj") is not None


@dataclass
class ReprojectionReport:
    """Structured outcome of an attempted reprojection."""
    source_crs: Optional[str]
    target_crs: str = "EPSG:4326"
    reprojected: bool = False
    warnings: List[Dict[str, str]] = field(default_factory=list)

    def add_warning(self, code: str, message_zh: str) -> None:
        self.warnings.append({"code": code, "message_zh": message_zh})

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_crs": self.source_crs,
            "target_crs": self.target_crs,
            "reprojected": self.reprojected,
            "warnings": list(self.warnings),
        }


def pyproj_available() -> bool:
    """True iff ``import pyproj`` would succeed in this environment."""
    return _PYPROJ_AVAILABLE


def reproject_feature_collection(
    collection: Dict[str, Any],
    source_crs: Optional[str],
    target_crs: str = "EPSG:4326",
) -> tuple[Dict[str, Any], ReprojectionReport]:
    """Reproject a GeoJSON FeatureCollection in place-friendly fashion.

    Behaviour:

    * No source_crs OR source == target → no-op, ``reprojected=False``,
      no warning.
    * Source ≠ target AND pyproj present → reproject every geometry.
      Returns a NEW collection (does not mutate input).
    * Source ≠ target AND pyproj missing → returns input unchanged plus
      a ``PYPROJ_UNAVAILABLE`` warning so callers can surface it.
    * Any pyproj transformation error → returns input unchanged plus a
      ``REPROJECTION_FAILED`` warning. We never crash the upload.
    """
    report = ReprojectionReport(source_crs=source_crs, target_crs=target_crs)

    if not source_crs or source_crs == target_crs:
        return collection, report

    if not _PYPROJ_AVAILABLE:
        report.add_warning(
            "PYPROJ_UNAVAILABLE",
            f"未安装 pyproj，未将 {source_crs} 自动转换为 {target_crs}。"
            "图层坐标已保留原始数值，渲染位置可能错位。",
        )
        return collection, report

    try:
        from pyproj import Transformer  # type: ignore
    except Exception as exc:  # pragma: no cover - defensive
        report.add_warning(
            "PYPROJ_IMPORT_FAILED",
            f"pyproj 加载失败：{exc}。坐标未转换。",
        )
        return collection, report

    try:
        transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)
    except Exception as exc:
        report.add_warning(
            "REPROJECTION_FAILED",
            f"无法构建 {source_crs} → {target_crs} 的坐标转换：{exc}。",
        )
        return collection, report

    try:
        new_collection = _transform_collection(collection, transformer)
    except Exception as exc:
        report.add_warning(
            "REPROJECTION_FAILED",
            f"坐标转换过程中出错：{exc}。已保留原始坐标。",
        )
        return collection, report

    report.reprojected = True
    return new_collection, report


# ---------------------------------------------------------------------------
# Internal helpers (no external deps; called only when pyproj is available)
# ---------------------------------------------------------------------------


def _transform_collection(collection: Dict[str, Any], transformer) -> Dict[str, Any]:
    features = collection.get("features") or []
    new_features = []
    for feature in features:
        if not isinstance(feature, dict):
            new_features.append(feature)
            continue
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict):
            new_features.append(feature)
            continue
        new_geom = _transform_geometry(geometry, transformer)
        new_feature = dict(feature)
        new_feature["geometry"] = new_geom
        new_features.append(new_feature)
    new_collection = dict(collection)
    new_collection["features"] = new_features
    # Strip stale top-level crs so the stored payload is unambiguous EPSG:4326.
    new_collection.pop("crs", None)
    return new_collection


def _transform_geometry(geometry: Dict[str, Any], transformer) -> Dict[str, Any]:
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if gtype == "Point":
        return {"type": "Point", "coordinates": _transform_point(coords, transformer)}
    if gtype == "MultiPoint" or gtype == "LineString":
        return {
            "type": gtype,
            "coordinates": [_transform_point(p, transformer) for p in coords or []],
        }
    if gtype == "MultiLineString" or gtype == "Polygon":
        return {
            "type": gtype,
            "coordinates": [
                [_transform_point(p, transformer) for p in ring or []]
                for ring in coords or []
            ],
        }
    if gtype == "MultiPolygon":
        return {
            "type": gtype,
            "coordinates": [
                [
                    [_transform_point(p, transformer) for p in ring or []]
                    for ring in poly or []
                ]
                for poly in coords or []
            ],
        }
    if gtype == "GeometryCollection":
        geoms = geometry.get("geometries") or []
        return {
            "type": gtype,
            "geometries": [_transform_geometry(g, transformer) for g in geoms],
        }
    # Unknown geometry type — leave as-is to avoid losing data.
    return geometry


def _transform_point(point, transformer):
    if not isinstance(point, (list, tuple)) or len(point) < 2:
        return point
    x, y = float(point[0]), float(point[1])
    nx, ny = transformer.transform(x, y)
    if len(point) >= 3:
        # Preserve Z / M dimensions as-is.
        return [nx, ny, *list(point[2:])]
    return [nx, ny]
