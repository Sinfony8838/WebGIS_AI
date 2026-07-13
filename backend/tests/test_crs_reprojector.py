"""Tests for the optional pyproj-backed reprojector.

The reprojection logic only fires when source != target CRS. When pyproj
is not installed in the test env, we assert the graceful-degrade path:
input returned unchanged + a structured PYPROJ_UNAVAILABLE warning.

If pyproj IS available we run an actual EPSG:32650 → EPSG:4326 round
trip to verify geometry coordinates change in the expected direction.
"""
from __future__ import annotations

import unittest

from backend.app.services import crs_reprojector


def _utm50_point_feature() -> dict:
    # UTM zone 50N centered around 117°E; (500000, 4500000) is near the
    # central meridian at roughly 40.6°N when transformed to EPSG:4326.
    return {
        "type": "Feature",
        "properties": {"name": "test"},
        "geometry": {"type": "Point", "coordinates": [500000.0, 4500000.0]},
    }


class ReportShapeTests(unittest.TestCase):
    def test_to_dict_contains_expected_keys(self) -> None:
        report = crs_reprojector.ReprojectionReport(source_crs="EPSG:32650")
        report.add_warning("X", "中文消息")
        payload = report.to_dict()
        self.assertEqual(
            set(payload.keys()),
            {"source_crs", "target_crs", "reprojected", "warnings"},
        )
        self.assertEqual(payload["target_crs"], "EPSG:4326")
        self.assertEqual(payload["warnings"], [{"code": "X", "message_zh": "中文消息"}])

    def test_default_not_reprojected(self) -> None:
        self.assertFalse(crs_reprojector.ReprojectionReport(source_crs=None).reprojected)


class NoOpPathTests(unittest.TestCase):
    """Exercising no-CRS / matching-CRS branches that do NOT need pyproj."""

    def test_no_source_crs_returns_input_unchanged(self) -> None:
        coll = {"type": "FeatureCollection", "features": [_utm50_point_feature()]}
        out, report = crs_reprojector.reproject_feature_collection(coll, source_crs=None)
        self.assertIs(out, coll)
        self.assertFalse(report.reprojected)
        self.assertEqual(report.warnings, [])

    def test_matching_crs_returns_input_unchanged(self) -> None:
        coll = {"type": "FeatureCollection", "features": [_utm50_point_feature()]}
        out, report = crs_reprojector.reproject_feature_collection(
            coll, source_crs="EPSG:4326", target_crs="EPSG:4326"
        )
        self.assertIs(out, coll)
        self.assertFalse(report.reprojected)


class GracefulDegradeOrTransformTests(unittest.TestCase):
    """When source != target the behaviour branches on pyproj availability."""

    def test_graceful_degrade_or_transform(self) -> None:
        coll = {"type": "FeatureCollection", "features": [_utm50_point_feature()]}
        out, report = crs_reprojector.reproject_feature_collection(
            coll, source_crs="EPSG:32650", target_crs="EPSG:4326"
        )

        if crs_reprojector.pyproj_available():
            # Real transform happened: the easting (500000m) should now sit
            # near 117° lon (the UTM50 central meridian), not stay at
            # 500000. We allow a loose tolerance so the test is not pinned
            # to a specific PROJ version.
            self.assertTrue(report.reprojected)
            self.assertEqual(report.warnings, [])
            new_coords = out["features"][0]["geometry"]["coordinates"]
            self.assertAlmostEqual(new_coords[0], 117.0, delta=0.5)
            self.assertGreater(new_coords[1], 35.0)
            self.assertLess(new_coords[1], 45.0)
            # crs member must be stripped to avoid stale tag travelling with
            # reprojected geometry.
            self.assertNotIn("crs", out)
        else:
            # No pyproj — input passes through, warning emitted.
            self.assertFalse(report.reprojected)
            self.assertIs(out, coll)
            codes = [w["code"] for w in report.warnings]
            self.assertIn("PYPROJ_UNAVAILABLE", codes)


class InvalidCrsTests(unittest.TestCase):
    """When pyproj is present but the requested CRS is bogus we must not
    crash — we report REPROJECTION_FAILED and pass the data through."""

    @unittest.skipUnless(crs_reprojector.pyproj_available(), "pyproj not installed")
    def test_invalid_source_crs_yields_failure_warning(self) -> None:
        coll = {"type": "FeatureCollection", "features": [_utm50_point_feature()]}
        out, report = crs_reprojector.reproject_feature_collection(
            coll, source_crs="EPSG:99999999"
        )
        self.assertFalse(report.reprojected)
        codes = [w["code"] for w in report.warnings]
        self.assertTrue(
            any(c in {"REPROJECTION_FAILED"} for c in codes),
            msg=f"expected REPROJECTION_FAILED, got {codes}",
        )
        # Geometry not mutated.
        self.assertEqual(
            out["features"][0]["geometry"]["coordinates"],
            [500000.0, 4500000.0],
        )


if __name__ == "__main__":
    unittest.main()
