from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image
from fastapi.testclient import TestClient

from backend.app import main as app_main
from backend.app.config import AppConfig
from backend.app.models import LayerRecord
from backend.app.runtime import WebGISRuntime
from backend.app.services.auth import AuthService
from backend.app.services import map_profiles


def density_project():
    polygons = []
    for x, value, name in ((0, 100, "西区"), (1, 400, "东区")):
        polygons.append({"type": "Feature", "properties": {"density": value, "name": name},
                         "geometry": {"type": "Polygon", "coordinates": [[[x, 0], [x + 1, 0], [x + 1, 1], [x, 1], [x, 0]]]}})
    layer = LayerRecord.create(name="测试区密度", kind="vector", source="one_map_catalog",
                               geometry_type="MultiPolygon", layer_id="district_density",
                               data={"type": "FeatureCollection", "features": polygons},
                               metadata={"source_year": "2020"})
    return SimpleNamespace(layers=[layer])


class MapProfileServiceTest(unittest.TestCase):
    def test_density_changes_only_at_boundaries(self):
        response = map_profiles.preview(density_project(), [[0.5, 0.5], [1.5, 0.5]],
                                        "population", "district_density", Path("unused"))
        self.assertEqual([sample["value"] for sample in response["samples"]], [100, 100, 400, 400])
        self.assertAlmostEqual(response["samples"][1]["distance_km"], response["samples"][2]["distance_km"], places=4)
        self.assertEqual(response["source_year"], "2020")
        self.assertEqual(response["no_data_count"], 0)

    def test_missing_polygon_data_is_gap(self):
        response = map_profiles.preview(density_project(), [[0.5, 0.5], [2.5, 0.5]],
                                        "population", "district_density", Path("unused"))
        self.assertIn(None, [sample["value"] for sample in response["samples"]])

    def test_rejects_invalid_line_and_unowned_source(self):
        for line in ([[0, 0]], [[0, 0], [0, 0]], [[0, 86], [1, 86]], [[0, 0], [100, 0]]):
            with self.subTest(line=line), self.assertRaises(map_profiles.ProfileError):
                map_profiles.preview(density_project(), line, "population", "district_density", Path("unused"))
        with self.assertRaises(map_profiles.ProfileError):
            map_profiles.preview(density_project(), [[0, 0], [1, 0]], "population", "other_project_layer", Path("unused"))

    def test_gpw_uses_numeric_source_and_preserves_missing_samples(self):
        with patch.object(map_profiles, "_gpw_value", side_effect=lambda p: None if p["lon"] > 0.01 else 123.5):
            response = map_profiles.preview(density_project(), [[0, 0], [0.02, 0]],
                                            "population", "gpw_2020", Path("unused"))
        self.assertEqual(response["source_year"], "2020")
        self.assertGreater(response["no_data_count"], 0)
        self.assertEqual(response["samples"][0]["value"], 123.5)

    def test_terrain_decodes_real_height_formula_and_caches_tile(self):
        image = Image.new("RGB", (256, 256), (128, 100, 0))  # 100 m
        data = io.BytesIO()
        image.save(data, format="PNG")
        with tempfile.TemporaryDirectory() as temp, patch.object(map_profiles, "_fetch", return_value=data.getvalue()) as fetch:
            point = {"lon": 121.5, "lat": 31.2}
            first = map_profiles._terrain_value(point, Path(temp))
            second = map_profiles._terrain_value(point, Path(temp))
        self.assertEqual((first, second), (100.0, 100.0))
        fetch.assert_called_once()


class MapProfileApiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous = app_main.config, app_main.runtime, app_main.auth_service
        app_main.config = AppConfig(root_dir=Path(self.temp.name), auth_mode="users")
        app_main.config.ensure_dirs()
        app_main.runtime = WebGISRuntime(app_main.config)
        app_main.auth_service = AuthService(app_main.config.auth_db_path)
        self.admin = TestClient(app_main.app)
        auth = self.admin.post("/auth/bootstrap", json={"email": "admin@school.test", "nickname": "管理员", "password": "Test-Admin-2026!"})
        self.headers = {"X-WebGIS-CSRF": auth.json()["csrf_token"]}
        self.project_id = self.admin.post("/projects", json={"name": "剖面测试"}, headers=self.headers).json()["project_id"]

    def tearDown(self):
        self.admin.close()
        app_main.config, app_main.runtime, app_main.auth_service = self.previous
        self.temp.cleanup()

    def test_preview_requires_project_access_and_never_uses_client_url(self):
        payload = {"kind": "terrain", "source_id": "mapzen_terrain", "coordinates": [[121.49, 31.2], [121.5, 31.2]]}
        anonymous = TestClient(app_main.app)
        self.assertEqual(anonymous.post(f"/projects/{self.project_id}/profiles/preview", json=payload).status_code, 401)
        anonymous.close()
        with patch.object(app_main, "preview_map_profile", return_value={"unit": "米"}) as preview:
            response = self.admin.post(f"/projects/{self.project_id}/profiles/preview", headers=self.headers,
                                       json={**payload, "url": "https://evil.example/tiles"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["unit"], "米")
        self.assertEqual(preview.call_args.args[3], "mapzen_terrain")
        self.assertEqual(self.admin.post(f"/projects/unknown/profiles/preview", headers=self.headers, json=payload).status_code, 404)
