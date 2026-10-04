"""Population counts from a local, tiled WorldPop package (never image colours)."""
from __future__ import annotations

import json
import math
import sqlite3
import zlib
from pathlib import Path
from typing import Any, Dict


class PopulationDataError(ValueError):
    pass


class PopulationCountPackage:
    def __init__(self, root: Path):
        self.root = Path(root)
        try:
            self.header = json.loads((self.root / "package.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise PopulationDataError("全球人口统计数据包未部署，请先完成课前资料检查。") from exc
        h = self.header
        if h.get("format") != "worldpop-count-tiles-v1" or h.get("units") != "persons_per_pixel":
            raise PopulationDataError("人口数据包格式或单位不正确，不能用于人数统计。")
        if not (self.root / "counts.sqlite").is_file():
            raise PopulationDataError("人口统计数据文件缺失。")
        if not math.isfinite(float(h.get("total_population", -1))) or float(h.get("total_population", -1)) <= 0:
            raise PopulationDataError("人口数据包总量无效。")

    def summarize(self, geometry: Dict[str, Any]) -> Dict[str, Any]:
        import numpy as np
        from shapely.geometry import shape, box
        from shapely import contains_xy

        try:
            polygon = shape(geometry)
        except Exception as exc:
            raise PopulationDataError("请在地图上绘制有效的统计区域。") from exc
        if polygon.geom_type not in {"Polygon", "MultiPolygon"} or polygon.is_empty or not polygon.is_valid:
            raise PopulationDataError("统计区域必须是有效的多边形，不能使用折线或自相交边界。")
        vertices = sum(len(r.coords) for p in (polygon.geoms if polygon.geom_type == "MultiPolygon" else [polygon])
                       for r in [p.exterior, *p.interiors])
        x0, y0, x1, y1 = polygon.bounds
        if vertices > 2000 or not all(math.isfinite(v) for v in polygon.bounds) or not (-180 <= x0 <= x1 <= 180 and -90 <= y0 <= y1 <= 90):
            raise PopulationDataError("统计区域超出经纬度范围或过于复杂；跨日期变更线请分成两个区域。")
        h = self.header
        west, south, east, north = h["bbox"]
        dx, dy = h["resolution_degrees"]
        tile_size = int(h["tile_size"])
        count, valid, selected = 0.0, 0, 0
        # Each source pixel contributes once using its centre. Holes and disjoint
        # polygons are handled by the geometry predicate, without area scaling.
        uri = (self.root / "counts.sqlite").resolve().as_uri() + "?mode=ro"
        with sqlite3.connect(uri, uri=True) as db:
            for row, col, height, width, blob in db.execute(
                "SELECT row,col,height,width,data FROM tiles WHERE col < ? AND col+width > ? AND row < ? AND row+height > ?",
                ((x1-west)/dx, (x0-west)/dx, (north-y0)/dy, (north-y1)/dy),
            ):
                values = np.frombuffer(zlib.decompress(blob), dtype="<f4").reshape(height, width)
                xs = west + (col + np.arange(width) + .5) * dx
                ys = north - (row + np.arange(height) + .5) * dy
                if polygon.covers(box(west+col*dx, north-(row+height)*dy, west+(col+width)*dx, north-row*dy)):
                    mask = np.ones(values.shape, dtype=bool)
                else:
                    mask = contains_xy(polygon, xs[None, :], ys[:, None])
                good = np.isfinite(values) & (values >= 0)
                selected += int(mask.sum())
                valid += int((mask & good).sum())
                count += float(values[mask & good].sum(dtype="float64"))
        total = float(h["total_population"])
        count = min(total, max(0.0, count))
        return {
            "status": "success" if valid else "no_data",
            "inside_population": round(count, 2) if valid else None,
            "outside_population": round(total-count, 2) if valid else None,
            "total_population": round(total, 2),
            "inside_percent": round(count/total*100, 2) if valid else None,
            "outside_percent": round((total-count)/total*100, 2) if valid else None,
            "valid_pixels": valid, "selected_pixels": selected,
            "year": h["year"], "source": h["source"], "resolution_degrees": h["resolution_degrees"],
            "method": "按原始像元中心落入区域求和；圈外为同一数据包总量减去圈内。",
            "note": "WorldPop模型估计人数；海洋与部分水体为无数据，不代表零人口。统计仅覆盖数据包范围。" if valid else "区域内没有有效人口像元，请重新圈定陆地区域。",
        }
