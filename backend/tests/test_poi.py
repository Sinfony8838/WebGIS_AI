from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from backend.app.config import AppConfig
from backend.app.services.poi import PoiService
from backend.app.store import RuntimeStore


class PoiServiceTest(unittest.TestCase):
    def build_service(self) -> tuple[AppConfig, RuntimeStore, PoiService, str]:
        temp_dir = tempfile.TemporaryDirectory()
        root_dir = Path(__file__).resolve().parents[2]
        config = AppConfig(root_dir=root_dir)
        config.data_dir = Path(temp_dir.name) / "backend" / "data"
        config.state_dir = config.data_dir / "state"
        config.uploads_dir = config.data_dir / "uploads"
        config.outputs_dir = config.data_dir / "outputs"
        config.state_file = config.state_dir / "runtime.json"
        config.amap_web_service_key = "demo-key"
        config.ensure_dirs()
        store = RuntimeStore(config.state_file)
        project = store.create_project(base_map=config.default_basemap())

        def fake_fetch(url: str) -> dict:
            self.last_url = url
            return {
                "status": "1",
                "pois": [
                    {
                        "id": "poi_1",
                        "name": "青岛港",
                        "address": "青岛市黄岛区",
                        "type": "港口码头",
                        "adname": "青岛",
                        "cityname": "青岛市",
                        "location": "120.30,36.06",
                    }
                ],
            }

        service = PoiService(config, store, fetch_json=fake_fetch)
        self.addCleanup(temp_dir.cleanup)
        return config, store, service, project.project_id

    def test_view_search_maps_extent_to_polygon_parameter(self) -> None:
        _config, store, service, project_id = self.build_service()
        result = service.search(project_id, "港口", mode="view", extent=[100, 20, 120, 40])
        query = parse_qs(urlparse(self.last_url).query)
        self.assertEqual(query["polygon"][0], "100.0,40.0|120.0,20.0")
        self.assertEqual(result["items"][0]["name"], "青岛港")
        layer = store.get_project(project_id).layers[-1]
        self.assertEqual(layer.layer_id, "poi_search_results")

    def test_polygon_search_normalizes_results_to_geojson_layer(self) -> None:
        _config, _store, service, project_id = self.build_service()
        result = service.search(
            project_id,
            "高铁站",
            mode="polygon",
            geometry={
                "type": "Polygon",
                "coordinates": [[[120.0, 30.0], [121.0, 30.0], [121.0, 31.0], [120.0, 31.0], [120.0, 30.0]]],
            },
        )
        feature = result["layer"]["data"]["features"][0]
        self.assertEqual(feature["properties"]["name"], "青岛港")
        self.assertEqual(feature["geometry"]["coordinates"], [120.3, 36.06])

    def test_search_skips_poi_without_valid_location(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        root_dir = Path(__file__).resolve().parents[2]
        config = AppConfig(root_dir=root_dir)
        config.data_dir = Path(temp_dir.name) / "backend" / "data"
        config.state_dir = config.data_dir / "state"
        config.uploads_dir = config.data_dir / "uploads"
        config.outputs_dir = config.data_dir / "outputs"
        config.state_file = config.state_dir / "runtime.json"
        config.amap_web_service_key = "demo-key"
        config.ensure_dirs()
        store = RuntimeStore(config.state_file)
        project = store.create_project(base_map=config.default_basemap())

        service = PoiService(
            config,
            store,
            fetch_json=lambda _url: {
                "status": "1",
                "pois": [
                    {"id": "ok", "name": "有效结果", "location": "120.30,36.06"},
                    {"id": "bad", "name": "无效结果", "location": "not-a-point"},
                ],
            },
        )
        self.addCleanup(temp_dir.cleanup)

        result = service.search(project.project_id, "港口", mode="view", extent=[100, 20, 120, 40])

        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["poi_id"], "ok")
