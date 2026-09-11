from __future__ import annotations

import io
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from backend.app import main as app_main
from backend.app.config import AppConfig
from backend.app.runtime import WebGISRuntime


class WeatherTileApiTest(unittest.TestCase):
    """天气瓦片代理的三个关键场景：未配置密钥 / 瓦片成功 / 瓦片失败。

    回归背景：未配置 WEBGIS_AI_OPENWEATHERMAP_API_KEY 时端点曾返回一张
    1x1 透明 PNG，前端 tileloadend 正常触发，界面表现为「切换成功」，
    地图却没有任何变化。现在未配置必须 503，失败必须 502，成功必须
    返回上游真实瓦片。
    """

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_config = app_main.config
        self.previous_runtime = app_main.runtime
        self.previous_auth_service = app_main.auth_service
        config = AppConfig(root_dir=Path(self.temp_dir.name), auth_mode="users")
        config.minimax_api_key = ""
        config.minimax_token_plan_key = ""
        config.ensure_dirs()
        app_main.config = config
        app_main.runtime = WebGISRuntime(config=config)
        app_main.auth_service = None
        self.client = TestClient(app_main.app)

    def tearDown(self) -> None:
        self.client.close()
        app_main.config = self.previous_config
        app_main.runtime = self.previous_runtime
        app_main.auth_service = self.previous_auth_service
        mock.patch.stopall()
        self.temp_dir.cleanup()

    def _patch_key(self, api_key: str | None) -> None:
        app_main.config.openweathermap_api_key = api_key or ""

    def test_tile_requires_no_session_cookie(self) -> None:
        # OpenLayers 以 <img crossorigin="anonymous"> 加载瓦片，跨端口部署时
        # 不携带会话 cookie；该端点改为公共 GET 后未登录请求也不得 401。
        self._patch_key(None)
        response = self.client.get("/tiles/weather/precipitation_new/4/12/9.png")
        self.assertNotEqual(response.status_code, 401)

    def test_tile_returns_503_with_actionable_message_without_api_key(self) -> None:
        self._patch_key(None)
        response = self.client.get("/tiles/weather/precipitation_new/4/12/9.png")

        self.assertEqual(response.status_code, 503)
        self.assertIn("WEBGIS_AI_OPENWEATHERMAP_API_KEY", response.json()["detail"])
        self.assertIn("no-store", response.headers.get("cache-control", ""))

    def test_tile_returns_upstream_bytes_when_configured(self) -> None:
        self._patch_key("demo-weather-key")
        fake_png = b"\x89PNG\r\n\x1a\nfake-tile-bytes"
        response_context = mock.Mock()
        response_context.headers.get_content_type.return_value = "image/png"
        response_context.read.return_value = fake_png
        response_context.__enter__ = mock.Mock(return_value=response_context)
        response_context.__exit__ = mock.Mock(return_value=False)

        captured = {}

        def fake_urlopen(request, timeout=0):
            captured["url"] = request.full_url
            return response_context

        with mock.patch("backend.app.runtime.urllib.request.urlopen", side_effect=fake_urlopen):
            response = self.client.get("/tiles/weather/clouds_new/4/12/9.png")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertEqual(response.content, fake_png)
        # 密钥只出现在服务端拼装的上游 URL，绝不返回给浏览器。
        self.assertIn("tile.openweathermap.org/map/clouds_new/4/12/9.png", captured["url"])
        self.assertIn("appid=demo-weather-key", captured["url"])
        for header_value in response.headers.values():
            self.assertNotIn("demo-weather-key", header_value)

    def test_tile_returns_502_when_upstream_fails(self) -> None:
        self._patch_key("demo-weather-key")

        def fake_urlopen(request, timeout=0):
            raise urllib.error.HTTPError(
                request.full_url, 401, "Unauthorized", mock.Mock(), io.BytesIO(b"")
            )

        with mock.patch("backend.app.runtime.urllib.request.urlopen", side_effect=fake_urlopen):
            response = self.client.get("/tiles/weather/precipitation_new/4/12/9.png")

        self.assertEqual(response.status_code, 502)
        self.assertIn("天气瓦片上游不可用", response.json()["detail"])
        self.assertIn("no-store", response.headers.get("cache-control", ""))

    def test_tile_returns_502_when_upstream_unreachable(self) -> None:
        self._patch_key("demo-weather-key")

        def fake_urlopen(request, timeout=0):
            raise urllib.error.URLError("connection refused")

        with mock.patch("backend.app.runtime.urllib.request.urlopen", side_effect=fake_urlopen):
            response = self.client.get("/tiles/weather/precipitation_new/4/12/9.png")

        self.assertEqual(response.status_code, 502)
        self.assertIn("connection refused", response.json()["detail"])

    def test_saved_weather_basemap_falls_back_when_key_removed(self) -> None:
        # 历史项目保存过天气底图、密钥随后被移除：加载时回落到默认底图，
        # 而不是渲染只剩高德参考层的「伪天气」状态。
        self._patch_key(None)
        normalized = app_main.config.normalize_basemap({"id": "weather_precipitation"})
        self.assertEqual(normalized["id"], "amap_vector")


if __name__ == "__main__":
    unittest.main()
