"""Preprocessed raster population packages: pure-stdlib reader and writer.

数据包结构（由 ``scripts/build_shanghai_worldpop_2020.py`` 生成，部署在
``<data_dir>/population/<package_id>/`` 下，原始 GeoTIFF 不入 Git）：

- ``package.json``：自描述元数据（bbox/网格尺寸/换算方法/来源与授权/校验值）。
- ``density.f32``：float32 小端、行优先（北→南）的**人/km² 密度网格**；
  nodata 以 NaN 表示。

原始 WorldPop 产品值为“每像元估计人数”，构建时按像元实际面积换算为
人/km²（``cell_area_km2`` 随纬度变化）；本模块不重新做换算，只提供读取。
"""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

PACKAGE_FILENAME = "package.json"
DENSITY_FILENAME = "density.f32"
FORMAT_VERSION = 1
EARTH_RADIUS_KM = 6371.0088


def cell_area_km2(lat_deg: float, lat_step_deg: float, lon_step_deg: float) -> float:
    """纬度 lat 处一个 lat_step×lon_step 像元的实际面积（km²，球面近似）。"""
    if lat_step_deg <= 0 or lon_step_deg <= 0:
        raise ValueError("像元步长必须为正。")
    lat = math.radians(lat_deg)
    height = EARTH_RADIUS_KM * math.radians(lat_step_deg)
    width = EARTH_RADIUS_KM * math.radians(lon_step_deg) * math.cos(lat)
    return width * height


def write_package(root: Path, header: Dict[str, Any], densities: Sequence[float]) -> Dict[str, Any]:
    """写出自描述数据包（供构建脚本与测试使用）；返回最终 header。"""
    width = int(header["width"])
    height = int(header["height"])
    if width <= 0 or height <= 0:
        raise ValueError("网格尺寸必须为正。")
    if len(densities) != width * height:
        raise ValueError("密度数据长度与网格尺寸不一致。")
    header = {**header, "format_version": FORMAT_VERSION, "width": width, "height": height,
              "value_type": "density_per_km2", "nodata": "NaN"}
    root.mkdir(parents=True, exist_ok=True)
    (root / DENSITY_FILENAME).write_bytes(struct.pack(f"<{len(densities)}f", *[float(v) for v in densities]))
    (root / PACKAGE_FILENAME).write_text(json.dumps(header, ensure_ascii=False, indent=2), encoding="utf-8")
    return header


class RasterPopulationPackage:
    """按需取样的本地人口密度包：不整包载入，逐点 seek。"""

    def __init__(self, root: Path):
        self.root = Path(root)
        header = json.loads((self.root / PACKAGE_FILENAME).read_text(encoding="utf-8"))
        if int(header.get("format_version") or 0) != FORMAT_VERSION:
            raise ValueError("人口数据包版本不受支持，请重新构建数据包。")
        self.header = header
        self.width = int(header["width"])
        self.height = int(header["height"])
        self.minx, self.miny, self.maxx, self.maxy = (float(v) for v in header["bbox"])
        self.lon_step = float(header["lon_step"])
        self.lat_step = float(header["lat_step"])
        self.density_path = self.root / DENSITY_FILENAME
        if self.width <= 0 or self.height <= 0 or not all(math.isfinite(v) for v in (
            self.minx, self.miny, self.maxx, self.maxy, self.lon_step, self.lat_step
        )) or self.lon_step <= 0 or self.lat_step <= 0 or self.minx >= self.maxx or self.miny >= self.maxy:
            raise ValueError("人口数据包网格无效。")
        if self.density_path.stat().st_size != self.width * self.height * 4:
            raise ValueError("人口数据包文件长度与网格尺寸不一致。")

    @property
    def package_id(self) -> str:
        return str(self.header.get("package_id") or self.root.name)

    def contains(self, lon: float, lat: float) -> bool:
        return self.minx <= lon <= self.maxx and self.miny <= lat <= self.maxy

    def sample(self, lon: float, lat: float) -> Optional[float]:
        if not self.contains(lon, lat):
            return None
        col = min(self.width - 1, max(0, int((lon - self.minx) / self.lon_step)))
        row = min(self.height - 1, max(0, int((self.maxy - lat) / self.lat_step)))
        with self.density_path.open("rb") as handle:
            handle.seek((row * self.width + col) * 4)
            (value,) = struct.unpack("<f", handle.read(4))
        if not math.isfinite(value) or value < 0:
            return None
        return round(float(value), 3)

    def sample_line(self, points: Sequence[Tuple[float, float]]) -> List[Optional[float]]:
        values: List[Optional[float]] = []
        with self.density_path.open("rb") as handle:
            for lon, lat in points:
                if not self.contains(lon, lat):
                    values.append(None)
                    continue
                col = min(self.width - 1, max(0, int((lon - self.minx) / self.lon_step)))
                row = min(self.height - 1, max(0, int((self.maxy - lat) / self.lat_step)))
                handle.seek((row * self.width + col) * 4)
                (value,) = struct.unpack("<f", handle.read(4))
                values.append(round(float(value), 3) if math.isfinite(value) and value >= 0 else None)
        return values

    def public_summary(self) -> Dict[str, Any]:
        source = self.header.get("source") or {}
        return {
            "package_id": self.package_id,
            "title": str(self.header.get("title") or self.package_id),
            "bbox": self.header.get("bbox"),
            "resolution_m": source.get("resolution_m"),
            "year": source.get("year"),
            "unit": "人/km²",
            "caveats": self.header.get("caveats") or [],
            "attribution": self.header.get("attribution") or "",
        }


def load_package(root: Path) -> Optional[RasterPopulationPackage]:
    """数据包已部署则返回读取器，否则 None（不抛异常，便于课堂降级）。"""
    try:
        if not (Path(root) / PACKAGE_FILENAME).is_file() or not (Path(root) / DENSITY_FILENAME).is_file():
            return None
        return RasterPopulationPackage(Path(root))
    except (OSError, ValueError, json.JSONDecodeError, KeyError):
        return None
