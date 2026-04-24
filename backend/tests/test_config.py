from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from backend.app.config import AppConfig


class AppConfigTest(unittest.TestCase):
    def test_basemap_catalog_contains_amap_presets(self) -> None:
        config = AppConfig()
        catalog = config.basemap_catalog()
        ids = {item["id"] for item in catalog["items"]}
        self.assertIn("amap_vector", ids)
        self.assertIn("amap_imagery", ids)
        self.assertIn("amap_light", ids)

    def test_normalize_basemap_from_legacy_xyz_shape(self) -> None:
        config = AppConfig()
        normalized = config.normalize_basemap(
            {
                "id": "legacy-custom",
                "title": "旧版底图",
                "type": "xyz",
                "url": "https://example.com/{z}/{x}/{y}.png",
                "attribution": "Example",
            }
        )
        self.assertEqual(normalized["id"], "legacy_xyz")
        self.assertEqual(normalized["layers"][0]["urls"][0], "https://example.com/{z}/{x}/{y}.png")
        self.assertTrue(normalized.get("legacy"))

    def test_public_path_round_trip_only_allows_uploads_and_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = AppConfig(root_dir=Path(temp_dir))
            config.ensure_dirs()

            upload_file = config.project_upload_dir("project_demo") / "demo.geojson"
            upload_file.write_text("{}", encoding="utf-8")
            public_url = config.public_url_for_path(upload_file)

            self.assertEqual(public_url, "/files/uploads/project_demo/demo.geojson")
            self.assertEqual(config.resolve_public_path("uploads/project_demo/demo.geojson"), upload_file.resolve())

            state_file = config.state_dir / "runtime.json"
            state_file.write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                config.public_url_for_path(state_file)
            with self.assertRaises(ValueError):
                config.resolve_public_path("../state/runtime.json")

    def test_unique_path_deduplicates_existing_filename(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = AppConfig(root_dir=Path(temp_dir))
            config.ensure_dirs()

            first = config.unique_path(config.outputs_dir, "report.md")
            first.write_text("one", encoding="utf-8")
            second = config.unique_path(config.outputs_dir, "report.md")

            self.assertNotEqual(first, second)
            self.assertEqual(second.name[:6], "report")

    def test_minimax_alias_envs_are_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.dict(
            os.environ,
            {
                "LLM_PROVIDER": "minimax",
                "MINIMAX_API_KEY": "alias-key",
                "MINIMAX_BASE_URL": "https://api-alias.minimax.test/v1",
                "MINIMAX_MODEL": "MiniMax-Alias",
            },
            clear=True,
        ):
            config = AppConfig(root_dir=Path(temp_dir))
            status = config.llm_status()

            self.assertTrue(status["configured"])
            self.assertTrue(status["enabled"])
            self.assertEqual(status["provider"], "minimax")
            self.assertEqual(status["provider_source"], "LLM_PROVIDER")
            self.assertEqual(status["api_key_source"], "MINIMAX_API_KEY")
            self.assertEqual(status["base_url"], "https://api-alias.minimax.test/v1")
            self.assertEqual(status["model"], "MiniMax-Alias")
            self.assertNotIn("error", status)

    def test_minimax_primary_envs_override_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.dict(
            os.environ,
            {
                "WEBGIS_AI_LLM_PROVIDER": "minimax",
                "LLM_PROVIDER": "legacy-provider",
                "WEBGIS_AI_MINIMAX_API_KEY": "primary-key",
                "MINIMAX_API_KEY": "legacy-key",
            },
            clear=True,
        ):
            config = AppConfig(root_dir=Path(temp_dir))
            status = config.llm_status()

            self.assertTrue(status["configured"])
            self.assertEqual(config.llm_provider, "minimax")
            self.assertEqual(config.minimax_api_key, "primary-key")
            self.assertEqual(status["provider_source"], "WEBGIS_AI_LLM_PROVIDER")
            self.assertEqual(status["api_key_source"], "WEBGIS_AI_MINIMAX_API_KEY")

    def test_minimax_missing_key_returns_actionable_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.dict(
            os.environ,
            {"WEBGIS_AI_LLM_PROVIDER": "minimax"},
            clear=True,
        ):
            config = AppConfig(root_dir=Path(temp_dir))
            status = config.llm_status()

            self.assertFalse(status["configured"])
            self.assertFalse(status["enabled"])
            self.assertEqual(status["provider_source"], "WEBGIS_AI_LLM_PROVIDER")
            self.assertEqual(status["api_key_source"], "unset")
            self.assertIsInstance(status["error"], str)
            self.assertIn("WEBGIS_AI_MINIMAX_API_KEY", status["error"])
            self.assertIn("重启后端", status["error"])
            self.assertNotIn("primary-key", status["error"])
            self.assertNotIn("legacy-key", status["error"])
