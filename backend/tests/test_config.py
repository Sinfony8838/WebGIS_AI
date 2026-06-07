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

    def test_weather_basemaps_are_visible_without_openweather_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.dict(os.environ, {}, clear=True):
            config = AppConfig(root_dir=Path(temp_dir))
            catalog = config.basemap_catalog()
            ids = {item["id"] for item in catalog["items"]}

            self.assertIn("weather_precipitation", ids)
            self.assertIn("weather_clouds", ids)
            self.assertIn("weather_temperature", ids)
            weather_item = next(item for item in catalog["items"] if item["id"] == "weather_precipitation")
            self.assertIn("WEBGIS_AI_OPENWEATHERMAP_API_KEY", weather_item["description"])
            self.assertEqual(catalog["default_id"], "amap_vector")

    def test_weather_basemaps_use_backend_proxy_and_keep_key_server_side(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.dict(
            os.environ,
            {
                "WEBGIS_AI_OPENWEATHERMAP_API_KEY": "demo-weather-key",
                "WEBGIS_AI_OPENWEATHERMAP_LAYER": "clouds_new",
            },
            clear=True,
        ):
            config = AppConfig(root_dir=Path(temp_dir))
            catalog = config.basemap_catalog()
            weather_item = next(item for item in catalog["items"] if item["id"] == "weather_clouds")

            self.assertEqual(
                weather_item["layers"][1]["urls"][0],
                "http://127.0.0.1:18999/tiles/weather/clouds_new/{z}/{x}/{y}.png",
            )
            self.assertNotIn("demo-weather-key", weather_item["layers"][1]["urls"][0])
            self.assertEqual(
                config.weather_tile_upstream_url("clouds_new", 4, 12, 9),
                "https://tile.openweathermap.org/map/clouds_new/4/12/9.png?appid=demo-weather-key",
            )

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

    # ------------------------------------------------------------------
    # v1.2 Xiaomi MiMo provider tests
    # ------------------------------------------------------------------

    def test_default_provider_is_mimo(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.dict(os.environ, {}, clear=True):
            config = AppConfig(root_dir=Path(temp_dir))
            self.assertEqual(config.llm_provider, "mimo")
            self.assertEqual(config.mimo_base_url, "https://api.xiaomimimo.com/v1")
            self.assertEqual(config.mimo_model, "mimo-v2.5-pro")
            # No key set → provider chosen but unconfigured.
            status = config.llm_status()
            self.assertFalse(status["configured"])
            self.assertEqual(status["provider"], "mimo")
            self.assertEqual(status["api_key_source"], "unset")
            self.assertIn("WEBGIS_AI_MIMO_API_KEY", status["error"])

    def test_mimo_primary_envs_configure_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.dict(
            os.environ,
            {
                "WEBGIS_AI_MIMO_API_KEY": "mimo-primary-key",
                "WEBGIS_AI_MIMO_MODEL": "mimo-v2.5-flash",
            },
            clear=True,
        ):
            config = AppConfig(root_dir=Path(temp_dir))
            status = config.llm_status()
            self.assertTrue(status["enabled"])
            self.assertTrue(status["configured"])
            self.assertEqual(status["provider"], "mimo")
            self.assertEqual(status["api_key_source"], "WEBGIS_AI_MIMO_API_KEY")
            self.assertEqual(status["model"], "mimo-v2.5-flash")
            self.assertEqual(config.active_llm_api_key(), "mimo-primary-key")

    def test_mimo_alias_envs_are_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.dict(
            os.environ,
            {
                "MIMO_API_KEY": "alias-mimo-key",
                "XIAOMI_MIMO_API_KEY": "longer-alias",
            },
            clear=True,
        ):
            config = AppConfig(root_dir=Path(temp_dir))
            # The first env in the alias tuple wins, so MIMO_API_KEY is used.
            self.assertEqual(config.mimo_api_key, "alias-mimo-key")
            self.assertEqual(config.llm_provider, "mimo")
            self.assertTrue(config.llm_enabled())

    def test_legacy_minimax_only_env_softly_falls_back_to_minimax(self) -> None:
        # If the caller never sets LLM_PROVIDER but DOES set a MiniMax key and
        # no Mimo key, we keep using MiniMax so v1.1 dev setups don't break.
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.dict(
            os.environ,
            {"MINIMAX_API_KEY": "legacy-only-key"},
            clear=True,
        ):
            config = AppConfig(root_dir=Path(temp_dir))
            self.assertEqual(config.llm_provider, "minimax")
            self.assertEqual(config.llm_provider_source, "default_fallback_minimax_only")
            self.assertTrue(config.llm_enabled())

    def test_explicit_mimo_overrides_legacy_minimax_key(self) -> None:
        # When BOTH Mimo and MiniMax keys are set without LLM_PROVIDER, we prefer
        # the new default (Mimo) — only the "MiniMax-only" shape triggers the fallback.
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.dict(
            os.environ,
            {
                "MIMO_API_KEY": "mimo-key",
                "MINIMAX_API_KEY": "legacy-key",
            },
            clear=True,
        ):
            config = AppConfig(root_dir=Path(temp_dir))
            self.assertEqual(config.llm_provider, "mimo")
            self.assertEqual(config.active_llm_api_key(), "mimo-key")

    def test_vision_provider_auto_tracks_llm_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.dict(
            os.environ,
            {"WEBGIS_AI_MIMO_API_KEY": "mimo-key", "WEBGIS_AI_VISION_ENABLED": "1"},
            clear=True,
        ):
            config = AppConfig(root_dir=Path(temp_dir))
            self.assertEqual(config.vision_provider, "mimo")
            self.assertEqual(config.vision_model, "mimo-v2.5")
            status = config.vision_status()
            self.assertTrue(status["configured"])
            self.assertEqual(status["provider"], "mimo")
            self.assertEqual(status["model"], "mimo-v2.5")

    def test_vision_provider_explicit_minimax_mcp_overrides_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.dict(
            os.environ,
            {
                "WEBGIS_AI_LLM_PROVIDER": "minimax",
                "WEBGIS_AI_MINIMAX_API_KEY": "key",
                "WEBGIS_AI_VISION_PROVIDER": "minimax_mcp",
                "WEBGIS_AI_MINIMAX_TOKEN_PLAN_KEY": "token-plan",
                "WEBGIS_AI_VISION_ENABLED": "1",
            },
            clear=True,
        ):
            config = AppConfig(root_dir=Path(temp_dir))
            self.assertEqual(config.vision_provider, "minimax_mcp")
            status = config.vision_status()
            self.assertTrue(status["configured"])
            self.assertEqual(status["provider"], "minimax_mcp")

    def test_minimax_mcp_vision_reuses_existing_minimax_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.dict(
            os.environ,
            {
                "WEBGIS_AI_LLM_PROVIDER": "minimax",
                "WEBGIS_AI_MINIMAX_API_KEY": "shared-minimax-key",
                "WEBGIS_AI_VISION_ENABLED": "1",
            },
            clear=True,
        ):
            config = AppConfig(root_dir=Path(temp_dir))
            self.assertEqual(config.vision_provider, "minimax_mcp")
            self.assertEqual(config.minimax_token_plan_key, "shared-minimax-key")
            status = config.vision_status()
            self.assertTrue(status["configured"])
            self.assertEqual(status["provider"], "minimax_mcp")
            self.assertEqual(status["token_plan_key_source"], "WEBGIS_AI_MINIMAX_API_KEY")
