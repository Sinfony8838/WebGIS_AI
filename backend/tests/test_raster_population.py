from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

from backend.app.services.raster_dataset import (
    RasterPopulationPackage,
    cell_area_km2,
    load_package,
    write_package,
)
from backend.app.services.map_profiles import ProfileError, preview


def _header(width: int, height: int, bbox: list, lon_step: float, lat_step: float) -> dict:
    minx, miny, maxx, maxy = bbox
    return {
        "package_id": "shanghai_worldpop_2020",
        "width": width,
        "height": height,
        "title": "上海 2020 年人口网格（WorldPop ~100m）",
        "bbox": bbox,
        "lon_step": lon_step,
        "lat_step": lat_step,
        "source": {
            "product": "WorldPop Global 2015-2030 Individual countries 100m R2025A v1 (alpha)",
            "file": "chn_pop_2020_CN_100m_R2025A_v1.tif",
            "year": 2020,
            "resolution_m": 100,
            "units_original": "persons per pixel",
            "license": "CC BY 4.0",
            "doi": "10.5258/SOTON/WP00839",
            "url": "https://hub.worldpop.org/geodata/summary?id=72922",
        },
        "attribution": "WorldPop 2015-2030 R2025A (CC BY 4.0)",
        "caveats": ["alpha 产品，仍可能更新", "每像元估计人数换算为人/km²，非逐建筑实测"],
        "conversion": "value_per_pixel / cell_area_km2(lat)",
        "validation": {},
    }


def _build_synthetic_package(root: Path) -> RasterPopulationPackage:
    """3 列 × 2 行合成包：3 角秒像元；北行每像元 1000 人、南行 500 人，北行末列 nodata。

    与真实构建脚本一致：先按像元实际面积把“每像元人数”换算为人/km² 再写入。
    """
    lat_step, lon_step = 2 / 3600, 3 / 3600
    maxx, maxy = 121.0 + 3 * lon_step, 31.0 + 2 * lat_step
    header = _header(3, 2, [121.0, 31.0, maxx, maxy], lon_step, lat_step)
    densities: list = []
    for row in range(2):  # 行 0 = 最北
        center_lat = maxy - (row + 0.5) * lat_step
        area = cell_area_km2(center_lat, lat_step, lon_step)
        for col in range(3):
            if row == 0 and col == 2:
                densities.append(float("nan"))
            else:
                densities.append((1000.0 if row == 0 else 500.0) / area)
    write_package(root, header, densities)
    return RasterPopulationPackage(root)


class CellAreaConversionTest(unittest.TestCase):
    """人口像元面积换算：随纬度变化的正确性。"""

    def test_area_shrinks_with_latitude_by_cosine(self) -> None:
        step = 3 / 3600
        equator = cell_area_km2(0.0, step, step)
        shanghai = cell_area_km2(31.2, step, step)
        high = cell_area_km2(60.0, step, step)
        self.assertAlmostEqual(shanghai / equator, math.cos(math.radians(31.2)), places=6)
        self.assertAlmostEqual(high / equator, math.cos(math.radians(60.0)), places=6)
        self.assertLess(shanghai, equator)
        self.assertLess(high, shanghai)

    def test_shanghai_cell_area_is_about_7350_square_meters(self) -> None:
        area = cell_area_km2(31.2, 3 / 3600, 3 / 3600)
        self.assertAlmostEqual(area * 1_000_000, 7350, delta=120)

    def test_invalid_steps_rejected(self) -> None:
        with self.assertRaises(ValueError):
            cell_area_km2(31.0, 0, 3 / 3600)


class RasterPackageTest(unittest.TestCase):
    """数据包读写与 nodata 处理。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "population" / "shanghai_worldpop_2020"
        self.package = _build_synthetic_package(self.root)

    def test_per_pixel_counts_convert_to_density_on_read_path(self) -> None:
        # 构建时换算：密度 = 人数 / cell_area(像元中心纬度)
        lat_step, lon_step = 2 / 3600, 3 / 3600
        north_area = cell_area_km2(31.0 + 2 * lat_step - 0.5 * lat_step, lat_step, lon_step)
        south_area = cell_area_km2(31.0 + 0.5 * lat_step, lat_step, lon_step)
        value = self.package.sample(121.0004, 31.0 + 1.5 * lat_step)
        self.assertAlmostEqual(value, round(1000.0 / north_area, 3), delta=abs(1000.0 / north_area) * 1e-6)
        south = self.package.sample(121.0004, 31.0 + 0.5 * lat_step)
        self.assertAlmostEqual(south, round(500.0 / south_area, 3), delta=abs(500.0 / south_area) * 1e-6)

    def test_nodata_and_out_of_bbox_return_none(self) -> None:
        lat_step = 2 / 3600
        self.assertIsNone(self.package.sample(121.0 + 2.5 * (3 / 3600), 31.0 + 1.5 * lat_step))  # nodata 像元
        self.assertIsNone(self.package.sample(100.0, 31.0 + 0.5 * lat_step))  # 范围外
        self.assertIsNone(self.package.sample(121.0004, 20.0))

    def test_roundtrip_preserves_header_and_summary(self) -> None:
        summary = self.package.public_summary()
        self.assertEqual(summary["package_id"], "shanghai_worldpop_2020")
        self.assertEqual(summary["year"], 2020)
        self.assertIn("alpha", " ".join(summary["caveats"]))
        self.assertIn("非逐建筑实测", " ".join(summary["caveats"]))
        header = json.loads((self.root / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(header["source"]["units_original"], "persons per pixel")

    def test_load_package_missing_or_corrupt_returns_none(self) -> None:
        self.assertIsNone(load_package(Path(self.tmp.name) / "absent"))
        bad = Path(self.tmp.name) / "bad"
        bad.mkdir(parents=True)
        (bad / "package.json").write_text("{not json", encoding="utf-8")
        self.assertIsNone(load_package(bad))


class ShanghaiRasterProfileTest(unittest.TestCase):
    """剖面端点读取本地裁剪包：数值、nodata 与来源标注。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = Path(self.tmp.name)
        self.cache_root = self.data_dir / "cache" / "map_profiles"
        self.population_root = self.data_dir / "population"
        _build_synthetic_package(self.population_root / "shanghai_worldpop_2020")

    def test_profile_reads_local_package_with_attribution(self) -> None:
        result = preview(
            project=None,
            coordinates=[[121.0, 31.0 + 1.5 * (2 / 3600)], [121.0 + 2.4 * (3 / 3600), 31.0 + 1.5 * (2 / 3600)]],
            kind="population",
            source_id="shanghai_worldpop_2020",
            cache_root=self.cache_root,
            population_root=self.population_root,
        )
        self.assertEqual(result["source_id"], "shanghai_worldpop_2020")
        self.assertEqual(result["unit"], "人/km²")
        self.assertEqual(result["source_year"], "2020")
        self.assertEqual(result["resolution_m"], 100)
        self.assertIn("WorldPop", result["source_name"])
        self.assertIn("换算", result["value_note"])
        self.assertIn("CC BY 4.0", result["source_attribution"])
        self.assertTrue(any(caveat.startswith("alpha") for caveat in result["source_caveats"]))
        values = [point["value"] for point in result["samples"]]
        self.assertTrue(any(value is not None for value in values))

    def test_profile_reports_missing_package_without_network(self) -> None:
        empty_root = self.data_dir / "empty"
        with self.assertRaises(ProfileError) as ctx:
            preview(
                project=None,
                coordinates=[[121.0, 31.0 + 1.5 * (2 / 3600)], [121.0 + 2.4 * (3 / 3600), 31.0 + 1.5 * (2 / 3600)]],
                kind="population",
                source_id="shanghai_worldpop_2020",
                cache_root=self.cache_root,
                population_root=empty_root,
            )
        self.assertEqual(ctx.exception.code, "SOURCE_UNAVAILABLE")
        self.assertIn("未部署", str(ctx.exception))

    def test_unknown_source_still_rejected(self) -> None:
        with self.assertRaises(ProfileError):
            preview(
                project=None,
                coordinates=[[121.0, 31.0], [121.02, 31.0]],
                kind="population",
                source_id="nope",
                cache_root=self.cache_root,
                population_root=self.population_root,
            )


if __name__ == "__main__":
    unittest.main()
