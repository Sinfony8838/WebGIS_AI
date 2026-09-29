"""Build the Shanghai 2020 WorldPop ~100m local population package.

从 WorldPop 全国 GeoTIFF（约 877MB，**不入 Git**）裁剪上海市范围，
把“每像元估计人数”按像元实际面积换算为人/km²，写出本地数据包：

    <data-dir>/population/shanghai_worldpop_2020/
        package.json   自描述元数据（含来源、授权、换算方法与校验值）
        density.f32    float32 小端、行优先（北→南）密度网格；nodata = NaN

数据源（构建时锁定版本）：
    WorldPop Global 2015-2030 Individual countries 100m, R2025A **v1**（alpha，仍可能更新）
    文件：chn_pop_2020_CN_100m_R2025A_v1.tif（3 角秒 ≈100m，WGS84，单位：persons per pixel）
    许可：CC BY 4.0　DOI: 10.5258/SOTON/WP00839
    https://hub.worldpop.org/geodata/summary?id=72922

用法（需构建依赖 numpy + rasterio：pip install -r scripts/requirements-geodata.txt rasterio）：

    python scripts/build_shanghai_worldpop_2020.py \
        --tif D:/data/chn_pop_2020_CN_100m_R2025A_v1.tif \
        --data-dir backend/data

校验：脚本打印上海范围估算总人口，并与 2020 年七普上海 24,870,895 人对照。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import from_bounds

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services.raster_dataset import cell_area_km2, write_package  # noqa: E402

SOURCE_URL = "https://data.worldpop.org/GIS/Population/Global_2015_2030/R2025A/2020/CHN/v1/100m/constrained/chn_pop_2020_CN_100m_R2025A_v1.tif"
BOUNDARY_PATH = (
    PROJECT_ROOT / "backend" / "app" / "data" / "builtin" / "one_map" / "boundaries" / "shanghai_districts.geojson"
)
CENSUS_2020_SHANGHAI = 24_870_895  # 七普上海常住人口（2020）
PACKAGE_ID = "shanghai_worldpop_2020"


def shanghai_bbox(buffer_deg: float) -> list[float]:
    geometry = json.loads(BOUNDARY_PATH.read_text(encoding="utf-8"))

    def walk(coords: Any) -> None:
        nonlocal minx, miny, maxx, maxy
        if isinstance(coords[0], (int, float)):
            lon, lat = float(coords[0]), float(coords[1])
            minx, miny = min(minx, lon), min(miny, lat)
            maxx, maxy = max(maxx, lon), max(maxy, lat)
            return
        for item in coords:
            walk(item)

    minx = miny = float("inf")
    maxx = maxy = float("-inf")
    for feature in geometry.get("features", []):
        walk(feature.get("geometry", {}).get("coordinates", []))
    if not (minx <= maxx and miny <= maxy):
        raise SystemExit("无法从 shanghai_districts.geojson 解析范围。")
    return [round(minx - buffer_deg, 6), round(miny - buffer_deg, 6),
            round(maxx + buffer_deg, 6), round(maxy + buffer_deg, 6)]


def sha256_of(path: Path, chunk: int = 1 << 22) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest().upper()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tif", required=True, help="原始全国 GeoTIFF 路径（不入 Git）")
    parser.add_argument("--data-dir", default=str(PROJECT_ROOT / "backend" / "data"), help="运行数据目录（部署包目标位置）")
    parser.add_argument("--buffer-deg", type=float, default=0.02, help="行政边界外扩（度）")
    parser.add_argument("--skip-hash", action="store_true", help="跳过源文件 SHA-256 计算（大文件提速）")
    args = parser.parse_args()

    tif_path = Path(args.tif)
    if not tif_path.is_file():
        raise SystemExit(f"找不到源文件：{tif_path}（可从 {SOURCE_URL} 下载）")
    bbox = shanghai_bbox(args.buffer_deg)
    minx, miny, maxx, maxy = bbox

    with rasterio.open(tif_path) as dataset:
        if dataset.width * dataset.height == 0:
            raise SystemExit("源栅格为空。")
        lon_step = float(abs(dataset.transform.a))
        lat_step = float(abs(dataset.transform.e))
        if abs(lon_step - 3 / 3600) > 1e-9 or abs(lat_step - 3 / 3600) > 1e-9:
            raise SystemExit(f"源栅格分辨率不是 3 角秒（~100m）：lon={lon_step}, lat={lat_step}")
        window = from_bounds(minx, miny, maxx, maxy, transform=dataset.transform)
        window = window.round_offsets().round_lengths()
        block = dataset.read(1, window=window, boundless=True, fill_value=np.nan).astype("float64")
        transform = dataset.window_transform(window)

    nodata_mask = ~np.isfinite(block)
    pixel_count = int(block.size - int(nodata_mask.sum()))
    if pixel_count == 0:
        raise SystemExit("裁剪范围内没有有效像元，请检查范围与源数据。")

    # 换算：每像元人数 → 人/km²（逐行按像元中心纬度的实际面积）。
    rows = height = block.shape[0]
    width = block.shape[1]
    densities = np.full(block.shape, np.nan, dtype="float64")
    total_population = 0.0
    for row in range(rows):
        center_lat = maxy - (row + 0.5) * lat_step
        area = cell_area_km2(center_lat, lat_step, lon_step)
        valid = ~nodata_mask[row]
        densities[row, valid] = block[row, valid] / area
        total_population += float(block[row, valid].sum())

    ratio = total_population / CENSUS_2020_SHANGHAI
    print(f"bbox={bbox}  网格={width}x{height}  有效像元={pixel_count}  nodata={int(nodata_mask.sum())}")
    print(f"估算总人口={total_population:,.0f}  七普对照={CENSUS_2020_SHANGHAI:,}  比值={ratio:.4f}")

    out_root = Path(args.data_dir) / "population" / PACKAGE_ID
    header = {
        "package_id": PACKAGE_ID,
        "title": "上海 2020 年人口网格（WorldPop ~100m 估计）",
        "bbox": bbox,
        "lon_step": lon_step,
        "lat_step": lat_step,
        "source": {
            "product": "WorldPop Global 2015-2030 Individual countries 100m R2025A v1 (alpha)",
            "file": tif_path.name,
            "year": 2020,
            "resolution_m": 100,
            "units_original": "persons per pixel",
            "license": "CC BY 4.0",
            "doi": "10.5258/SOTON/WP00839",
            "url": "https://hub.worldpop.org/geodata/summary?id=72922",
            "download_url": SOURCE_URL,
            "release_statement": "https://data.worldpop.org/repo/prj/Global_2015_2030/R2025A/doc/Global2_Release_Statement_R2025A_v1.pdf",
        },
        "attribution": (
            "WorldPop (www.worldpop.org - School of Geography and Environmental Science, "
            "University of Southampton; Department of Geography and Geosciences, University of Louisville; "
            "Département de Géographie, Université de Namur) and Center for International Earth Science "
            "Information Network (CIESIN), Columbia University (2025). Global 2015-2030 R2025A. "
            "DOI:10.5258/SOTON/WP00839. CC BY 4.0."
        ),
        "caveats": [
            "alpha 产品（R2025A v1），WorldPop 标注仍可能更新；构建时已锁定上述文件与 SHA-256。",
            "属性为“每像元估计人数”，按像元实际面积换算为人/km²；属统计估计，不是逐建筑实测。",
            "无数据像元以 NaN 表示；图表与剖面须标注来源、年份、分辨率与 nodata 点数。",
        ],
        "conversion": "density = persons_per_pixel / cell_area_km2(pixel_center_lat)；cell_area_km2 见 backend/app/services/raster_dataset.py",
        "validation": {
            "total_population": round(total_population, 1),
            "census_2020_shanghai": CENSUS_2020_SHANGHAI,
            "ratio_vs_census": round(ratio, 4),
            "pixel_count": pixel_count,
            "nodata_count": int(nodata_mask.sum()),
            "source_sha256": "(skipped)" if args.skip_hash else sha256_of(tif_path),
        },
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    result = write_package(out_root, header, densities.flatten().tolist())
    print(f"已写出数据包：{out_root}")
    print(f"校验值 total_population={result['validation']['total_population']:,}  ratio={result['validation']['ratio_vs_census']}")


if __name__ == "__main__":
    main()
