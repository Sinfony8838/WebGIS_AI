from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from backend.app.config import AppConfig
from backend.app.services.datasets import DatasetService
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
