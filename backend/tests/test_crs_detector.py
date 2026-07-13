"""Unit tests for the pure-Python CRS detector.

Does not require pyproj, pyshp, or QGIS — exercises every detection
path and every malformed-input edge case.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.app.services import crs_detector


WKT_4326 = (
    'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563,'
    'AUTHORITY["EPSG","7030"]],AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0],'
    'UNIT["degree",0.0174532925199433],AUTHORITY["EPSG","4326"]]'
)

WKT_UTM50N = (
    'PROJCS["WGS 84 / UTM zone 50N",'
    'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563,'
    'AUTHORITY["EPSG","7030"]],AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0],'
    'UNIT["degree",0.0174532925199433],AUTHORITY["EPSG","4326"]],'
    'PROJECTION["Transverse_Mercator"],PARAMETER["latitude_of_origin",0],'
    'PARAMETER["central_meridian",117],PARAMETER["scale_factor",0.9996],'
    'PARAMETER["false_easting",500000],PARAMETER["false_northing",0],'
    'UNIT["metre",1,AUTHORITY["EPSG","9001"]],AUTHORITY["EPSG","32650"]]'
)

WKT_NO_AUTHORITY = (
    'PROJCS["Custom Mercator",GEOGCS["WGS 84",DATUM["WGS_1984",'
    'SPHEROID["WGS 84",6378137,298.257223563]]],'
    'PROJECTION["Mercator_1SP"],UNIT["metre",1]]'
)


class NormalizeEpsgTests(unittest.TestCase):
    def test_canonical_string(self) -> None:
        self.assertEqual(crs_detector.normalize_epsg("EPSG:4326"), "EPSG:4326")

    def test_case_insensitive_and_spaces(self) -> None:
        self.assertEqual(crs_detector.normalize_epsg(" epsg : 32650 "), "EPSG:32650")

    def test_int_input(self) -> None:
        self.assertEqual(crs_detector.normalize_epsg(4326), "EPSG:4326")

    def test_negative_int_rejected(self) -> None:
        self.assertIsNone(crs_detector.normalize_epsg(-100))

    def test_ogc_urn(self) -> None:
        self.assertEqual(
            crs_detector.normalize_epsg("urn:ogc:def:crs:EPSG::4326"),
            "EPSG:4326",
        )

    def test_garbage_returns_none(self) -> None:
        self.assertIsNone(crs_detector.normalize_epsg(""))
        self.assertIsNone(crs_detector.normalize_epsg("hello"))
        self.assertIsNone(crs_detector.normalize_epsg(None))


class DetectGeoJsonCrsTests(unittest.TestCase):
    def test_modern_name_member(self) -> None:
        payload = {
            "type": "FeatureCollection",
            "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::32650"}},
            "features": [],
        }
        self.assertEqual(crs_detector.detect_geojson_crs(payload), "EPSG:32650")

    def test_legacy_code_member(self) -> None:
        payload = {
            "type": "FeatureCollection",
            "crs": {"type": "EPSG", "properties": {"code": 4326}},
            "features": [],
        }
        self.assertEqual(crs_detector.detect_geojson_crs(payload), "EPSG:4326")

    def test_no_crs_member_returns_none(self) -> None:
        payload = {"type": "FeatureCollection", "features": []}
        # No explicit CRS → None (callers should treat as "implicit 4326")
        self.assertIsNone(crs_detector.detect_geojson_crs(payload))

    def test_non_dict_payload(self) -> None:
        self.assertIsNone(crs_detector.detect_geojson_crs(["array"]))
        self.assertIsNone(crs_detector.detect_geojson_crs(None))

    def test_malformed_crs_member_returns_none(self) -> None:
        payload = {"type": "FeatureCollection", "crs": "not a dict", "features": []}
        self.assertIsNone(crs_detector.detect_geojson_crs(payload))
        payload = {"type": "FeatureCollection", "crs": {"type": "name"}, "features": []}
        self.assertIsNone(crs_detector.detect_geojson_crs(payload))


class ParseWktEpsgTests(unittest.TestCase):
    def test_wgs84_geogcs(self) -> None:
        self.assertEqual(crs_detector.parse_wkt_epsg(WKT_4326), "EPSG:4326")

    def test_utm_zone_50n_takes_last_authority(self) -> None:
        # Nested WKT — the projected outer AUTHORITY (32650) must win over
        # the geographic inner one (4326).
        self.assertEqual(crs_detector.parse_wkt_epsg(WKT_UTM50N), "EPSG:32650")

    def test_no_authority_block_returns_none(self) -> None:
        self.assertIsNone(crs_detector.parse_wkt_epsg(WKT_NO_AUTHORITY))

    def test_empty_input(self) -> None:
        self.assertIsNone(crs_detector.parse_wkt_epsg(""))
        self.assertIsNone(crs_detector.parse_wkt_epsg(None))


class DetectShapefileCrsTests(unittest.TestCase):
    def test_finds_prj_file_in_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data.shp").write_bytes(b"fake")
            (root / "data.prj").write_text(WKT_UTM50N, encoding="utf-8")
            self.assertEqual(crs_detector.detect_shapefile_crs(root), "EPSG:32650")

    def test_recurses_into_subdirectories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sub = root / "nested" / "deep"
            sub.mkdir(parents=True)
            (sub / "data.prj").write_text(WKT_4326, encoding="utf-8")
            self.assertEqual(crs_detector.detect_shapefile_crs(root), "EPSG:4326")

    def test_no_prj_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data.shp").write_bytes(b"fake")
            self.assertIsNone(crs_detector.detect_shapefile_crs(root))

    def test_missing_directory_returns_none(self) -> None:
        self.assertIsNone(crs_detector.detect_shapefile_crs(Path("/nonexistent/path")))


class LooksLikeProjectedMetersTests(unittest.TestCase):
    def test_lonlat_values_accepted(self) -> None:
        self.assertFalse(
            crs_detector.looks_like_projected_meters([116.4, 121.5, 113.2], axis="lon")
        )
        self.assertFalse(
            crs_detector.looks_like_projected_meters([39.9, 31.2, 23.1], axis="lat")
        )

    def test_projected_meters_flagged(self) -> None:
        # UTM 50N easting / northing are way outside [-180, 180] / [-90, 90]
        self.assertTrue(
            crs_detector.looks_like_projected_meters([500000.0, 700000.0], axis="lon")
        )
        self.assertTrue(
            crs_detector.looks_like_projected_meters([4500000.0, 4700000.0], axis="lat")
        )

    def test_empty_values_returns_false(self) -> None:
        self.assertFalse(crs_detector.looks_like_projected_meters([], axis="lon"))

    def test_unparseable_values_ignored(self) -> None:
        self.assertFalse(
            crs_detector.looks_like_projected_meters(["nope", "still no"], axis="lon")
        )


class IsWgs84Tests(unittest.TestCase):
    def test_match(self) -> None:
        self.assertTrue(crs_detector.is_wgs84("EPSG:4326"))

    def test_not_match(self) -> None:
        self.assertFalse(crs_detector.is_wgs84("EPSG:3857"))
        self.assertFalse(crs_detector.is_wgs84(None))
        self.assertFalse(crs_detector.is_wgs84(""))


if __name__ == "__main__":
    unittest.main()
