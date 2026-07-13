from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from backend.app.config import AppConfig
from backend.app.services import crs_reprojector
from backend.app.services.datasets import CrsAssumptionError, DatasetService
from backend.app.store import RuntimeStore


class DatasetServiceTest(unittest.TestCase):
    def build_service(self) -> tuple[AppConfig, RuntimeStore, DatasetService, str]:
        temp_dir = tempfile.TemporaryDirectory()
        root_dir = Path(__file__).resolve().parents[2]
        config = AppConfig(root_dir=root_dir)
        config.data_dir = Path(temp_dir.name) / "backend" / "data"
        config.state_dir = config.data_dir / "state"
        config.uploads_dir = config.data_dir / "uploads"
        config.outputs_dir = config.data_dir / "outputs"
        config.state_file = config.state_dir / "runtime.json"
        config.ensure_dirs()
        store = RuntimeStore(config.state_file)
        project = store.create_project(base_map=config.default_basemap())
        service = DatasetService(config, store)
        self.addCleanup(temp_dir.cleanup)
        return config, store, service, project.project_id

    def test_geojson_import_normalizes_feature_collection(self) -> None:
        _config, _store, service, project_id = self.build_service()
        raw = b'{"type":"Feature","properties":{"name":"A"},"geometry":{"type":"Point","coordinates":[120,30]}}'
        result = service.import_upload(project_id, "points.geojson", raw)
        self.assertEqual(result["layer"]["geometry_type"], "Point")
        self.assertEqual(result["layer"]["metadata"]["feature_count"], 1)

    def test_csv_import_uses_lat_lon_fields(self) -> None:
        _config, _store, service, project_id = self.build_service()
        raw = "name,lon,lat,value\nA,120,30,1\nB,121,31,2\n".encode("utf-8")
        result = service.import_upload(project_id, "samples.csv", raw)
        self.assertEqual(result["layer"]["geometry_type"], "Point")
        self.assertEqual(result["layer"]["metadata"]["feature_count"], 2)

    def test_csv_import_rejects_rows_without_valid_coordinates(self) -> None:
        _config, _store, service, project_id = self.build_service()
        raw = "name,lon,lat\nA,hello,30\nB,121,120\n".encode("utf-8")
        with self.assertRaises(ValueError):
            service.import_upload(project_id, "invalid.csv", raw)

    def test_repeated_upload_filename_gets_unique_storage_path(self) -> None:
        _config, _store, service, project_id = self.build_service()
        raw = b'{"type":"FeatureCollection","features":[]}'
        first = service.import_upload(project_id, "repeat.geojson", raw)
        second = service.import_upload(project_id, "repeat.geojson", raw)

        self.assertNotEqual(first["artifact"]["path"], second["artifact"]["path"])

    def test_safe_extract_zip_rejects_path_traversal_entries(self) -> None:
        _config, _store, service, _project_id = self.build_service()
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "unsafe.zip"
            extract_dir = Path(temp_dir) / "extract"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("../escape.shp", "bad")
            with zipfile.ZipFile(archive_path) as archive:
                with self.assertRaises(ValueError):
                    service._safe_extract_zip(archive, extract_dir)


class DatasetServiceCrsTests(unittest.TestCase):
    """Verify CRS detection + reprojection paths added in v1.2 Phase 1.5."""

    def build_service(self) -> tuple[AppConfig, RuntimeStore, DatasetService, str]:
        temp_dir = tempfile.TemporaryDirectory()
        root_dir = Path(__file__).resolve().parents[2]
        config = AppConfig(root_dir=root_dir)
        config.data_dir = Path(temp_dir.name) / "backend" / "data"
        config.state_dir = config.data_dir / "state"
        config.uploads_dir = config.data_dir / "uploads"
        config.outputs_dir = config.data_dir / "outputs"
        config.state_file = config.state_dir / "runtime.json"
        config.ensure_dirs()
        store = RuntimeStore(config.state_file)
        project = store.create_project(base_map=config.default_basemap())
        service = DatasetService(config, store)
        self.addCleanup(temp_dir.cleanup)
        return config, store, service, project.project_id

    def test_geojson_without_crs_member_marked_implicit_wgs84(self) -> None:
        _config, _store, service, project_id = self.build_service()
        raw = (
            b'{"type":"FeatureCollection","features":'
            b'[{"type":"Feature","properties":{"name":"A"},'
            b'"geometry":{"type":"Point","coordinates":[120,30]}}]}'
        )
        result = service.import_upload(project_id, "no_crs.geojson", raw)
        crs = result["crs"]
        self.assertEqual(crs["source_crs"], "EPSG:4326")
        self.assertEqual(crs["target_crs"], "EPSG:4326")
        self.assertFalse(crs["reprojected"])
        self.assertEqual(crs["detection_method"], "implicit_wgs84")
        self.assertEqual(crs["warnings"], [])

        layer_meta = result["layer"]["metadata"]
        self.assertEqual(layer_meta["source_crs"], "EPSG:4326")
        self.assertEqual(layer_meta["stored_crs"], "EPSG:4326")
        self.assertEqual(layer_meta["crs_detection"], "implicit_wgs84")

    def test_geojson_with_explicit_4326_crs_member_recorded(self) -> None:
        _config, _store, service, project_id = self.build_service()
        payload = {
            "type": "FeatureCollection",
            "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::4326"}},
            "features": [
                {
                    "type": "Feature",
                    "properties": {"name": "X"},
                    "geometry": {"type": "Point", "coordinates": [120, 30]},
                }
            ],
        }
        result = service.import_upload(project_id, "with_crs.geojson", json.dumps(payload).encode("utf-8"))
        crs = result["crs"]
        self.assertEqual(crs["source_crs"], "EPSG:4326")
        self.assertEqual(crs["detection_method"], "geojson_crs_member")
        self.assertFalse(crs["reprojected"])  # same source/target → no transform
        # Stored geojson must NOT carry a stale top-level crs.
        self.assertNotIn("crs", result["layer"]["data"])

    def test_geojson_with_non_wgs84_crs_uses_reprojector_or_warns(self) -> None:
        _config, _store, service, project_id = self.build_service()
        payload = {
            "type": "FeatureCollection",
            "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::32650"}},
            "features": [
                {
                    "type": "Feature",
                    "properties": {"name": "Beijing-ish"},
                    "geometry": {"type": "Point", "coordinates": [500000.0, 4500000.0]},
                }
            ],
        }
        result = service.import_upload(project_id, "utm.geojson", json.dumps(payload).encode("utf-8"))
        crs = result["crs"]
        self.assertEqual(crs["source_crs"], "EPSG:32650")
        self.assertEqual(crs["detection_method"], "geojson_crs_member")

        coords = result["layer"]["data"]["features"][0]["geometry"]["coordinates"]
        if crs_reprojector.pyproj_available():
            self.assertTrue(crs["reprojected"])
            # After reprojection, x should be near 117° lon (UTM50 central meridian).
            self.assertAlmostEqual(coords[0], 117.0, delta=0.5)
            self.assertGreater(coords[1], 35.0)
            self.assertLess(coords[1], 45.0)
        else:
            # Graceful degrade: coordinates unchanged + PYPROJ_UNAVAILABLE warning.
            self.assertFalse(crs["reprojected"])
            self.assertEqual(coords, [500000.0, 4500000.0])
            codes = [w["code"] for w in crs["warnings"]]
            self.assertIn("PYPROJ_UNAVAILABLE", codes)

    def test_csv_with_projected_meters_raises_friendly_error(self) -> None:
        _config, _store, service, project_id = self.build_service()
        raw = "name,lon,lat\nA,500000,4500000\nB,510000,4510000\n".encode("utf-8")
        with self.assertRaises(CrsAssumptionError) as ctx:
            service.import_upload(project_id, "projected.csv", raw)
        # Chinese message includes the actionable hint.
        self.assertIn("EPSG:4326", str(ctx.exception))

    def test_csv_with_valid_lonlat_produces_implicit_wgs84_report(self) -> None:
        _config, _store, service, project_id = self.build_service()
        raw = "name,lon,lat\nA,120,30\n".encode("utf-8")
        result = service.import_upload(project_id, "lonlat.csv", raw)
        self.assertEqual(result["crs"]["source_crs"], "EPSG:4326")
        self.assertEqual(result["crs"]["detection_method"], "csv_lonlat_validated")
        self.assertFalse(result["crs"]["reprojected"])

    def test_image_overlay_records_implicit_wgs84(self) -> None:
        _config, _store, service, project_id = self.build_service()
        # tiny 1x1 PNG (just a placeholder; the service does not inspect contents)
        png_bytes = bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
            "00000001735247420080e21cb40000000a49444154789c63600100000005000170"
            "ec61ee0000000049454e44ae426082"
        )
        result = service.import_upload(
            project_id,
            "overlay.png",
            png_bytes,
            image_bounds=[120.0, 30.0, 121.0, 31.0],
        )
        self.assertEqual(result["crs"]["source_crs"], "EPSG:4326")
        self.assertEqual(result["crs"]["detection_method"], "image_bounds_assumed_wgs84")

    def test_shapefile_zip_without_prj_warns(self) -> None:
        _config, _store, service, project_id = self.build_service()
        # Build a minimal point shapefile zip without .prj using pyshp.
        try:
            import shapefile  # type: ignore
        except ImportError:
            self.skipTest("pyshp not installed")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            shp_stem = tmp_path / "points"
            writer = shapefile.Writer(str(shp_stem), shapeType=shapefile.POINT)
            writer.field("name", "C", size=20)
            writer.point(120.0, 30.0)
            writer.record("Shanghai")
            writer.close()
            zip_path = tmp_path / "no_prj.zip"
            with zipfile.ZipFile(zip_path, "w") as archive:
                for suffix in ("shp", "shx", "dbf"):
                    archive.write(tmp_path / f"points.{suffix}", arcname=f"points.{suffix}")
            raw = zip_path.read_bytes()

        result = service.import_upload(project_id, "no_prj.zip", raw)
        crs = result["crs"]
        self.assertEqual(crs["detection_method"], "shapefile_no_prj_assumed_wgs84")
        self.assertEqual(crs["source_crs"], "EPSG:4326")
        codes = [w["code"] for w in crs["warnings"]]
        self.assertIn("SHAPEFILE_NO_PRJ", codes)

    def test_shapefile_zip_with_4326_prj_no_warning(self) -> None:
        _config, _store, service, project_id = self.build_service()
        try:
            import shapefile  # type: ignore
        except ImportError:
            self.skipTest("pyshp not installed")

        wgs84_wkt = (
            'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563,'
            'AUTHORITY["EPSG","7030"]],AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0],'
            'UNIT["degree",0.0174532925199433],AUTHORITY["EPSG","4326"]]'
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            shp_stem = tmp_path / "points"
            writer = shapefile.Writer(str(shp_stem), shapeType=shapefile.POINT)
            writer.field("name", "C", size=20)
            writer.point(120.0, 30.0)
            writer.record("Shanghai")
            writer.close()
            (tmp_path / "points.prj").write_text(wgs84_wkt, encoding="utf-8")
            zip_path = tmp_path / "with_prj.zip"
            with zipfile.ZipFile(zip_path, "w") as archive:
                for suffix in ("shp", "shx", "dbf", "prj"):
                    archive.write(tmp_path / f"points.{suffix}", arcname=f"points.{suffix}")
            raw = zip_path.read_bytes()

        result = service.import_upload(project_id, "with_prj.zip", raw)
        crs = result["crs"]
        self.assertEqual(crs["source_crs"], "EPSG:4326")
        self.assertEqual(crs["detection_method"], "shapefile_prj")
        self.assertFalse(crs["reprojected"])
        self.assertEqual(crs["warnings"], [])

    def test_shapefile_zip_with_utm_prj_emits_reproject_or_warning(self) -> None:
        _config, _store, service, project_id = self.build_service()
        try:
            import shapefile  # type: ignore
        except ImportError:
            self.skipTest("pyshp not installed")

        utm50_wkt = (
            'PROJCS["WGS 84 / UTM zone 50N",'
            'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563,'
            'AUTHORITY["EPSG","7030"]],AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0],'
            'UNIT["degree",0.0174532925199433],AUTHORITY["EPSG","4326"]],'
            'PROJECTION["Transverse_Mercator"],PARAMETER["latitude_of_origin",0],'
            'PARAMETER["central_meridian",117],PARAMETER["scale_factor",0.9996],'
            'PARAMETER["false_easting",500000],PARAMETER["false_northing",0],'
            'UNIT["metre",1,AUTHORITY["EPSG","9001"]],AUTHORITY["EPSG","32650"]]'
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            shp_stem = tmp_path / "points"
            writer = shapefile.Writer(str(shp_stem), shapeType=shapefile.POINT)
            writer.field("name", "C", size=20)
            writer.point(500000.0, 4500000.0)
            writer.record("Site A")
            writer.close()
            (tmp_path / "points.prj").write_text(utm50_wkt, encoding="utf-8")
            zip_path = tmp_path / "utm.zip"
            with zipfile.ZipFile(zip_path, "w") as archive:
                for suffix in ("shp", "shx", "dbf", "prj"):
                    archive.write(tmp_path / f"points.{suffix}", arcname=f"points.{suffix}")
            raw = zip_path.read_bytes()

        result = service.import_upload(project_id, "utm.zip", raw)
        crs = result["crs"]
        self.assertEqual(crs["source_crs"], "EPSG:32650")
        self.assertEqual(crs["detection_method"], "shapefile_prj")
        coords = result["layer"]["data"]["features"][0]["geometry"]["coordinates"]
        # pyshp returns Point coordinates as tuples via __geo_interface__; compare
        # element-wise so the test passes whether the upstream type is list or tuple.
        if crs_reprojector.pyproj_available():
            self.assertTrue(crs["reprojected"])
            self.assertAlmostEqual(coords[0], 117.0, delta=0.5)
        else:
            self.assertFalse(crs["reprojected"])
            self.assertEqual(tuple(coords), (500000.0, 4500000.0))
            codes = [w["code"] for w in crs["warnings"]]
            self.assertIn("PYPROJ_UNAVAILABLE", codes)
