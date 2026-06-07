from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.app.config import AppConfig
from backend.app.models import ProjectRecord
from backend.app.runtime import WebGISRuntime
from backend.app.services.vision import MapVisionService
from backend.app.store import RuntimeStore


SAMPLE_SNAPSHOT = {
    "image_data_url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAEElEQVR42mP8z8BQDwAFgwJ/lU9nWQAAAABJRU5ErkJggg==",
    "width": 1,
    "height": 1,
    "captured_at": "2026-05-06T00:00:00Z",
}


class FakeMcpClient:
    def __init__(self) -> None:
        self.calls = []

    def understand_image(self, prompt: str, image_url: str):
        self.calls.append({"prompt": prompt, "image_url": image_url})
        return {"text": "这是一张中国年降水量分布图，东南多、西北少。", "raw": {"content": []}}


class FakeLLMClient:
    """Captures the multimodal messages sent to chat_completion."""

    def __init__(self, response_text: str = "Xiaomi MiMo 直读结果：图中东南沿海降水多、西北少。") -> None:
        self.calls = []
        self.response_text = response_text

    def chat_completion(self, messages, temperature=0.2, **kwargs):
        self.calls.append({"messages": messages, "temperature": temperature, **kwargs})
        return self.response_text


class MapVisionServiceTest(unittest.TestCase):
    def build_config(self) -> AppConfig:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root_dir = Path(temp_dir.name)
        config = AppConfig(root_dir=root_dir)
        config.data_dir = root_dir / "backend" / "data"
        config.outputs_dir = config.data_dir / "outputs"
        config.uploads_dir = config.data_dir / "uploads"
        config.state_dir = config.data_dir / "state"
        config.vision_enabled = False
        config.mimo_api_key = ""
        config.minimax_token_plan_key = ""
        config.ensure_dirs()
        return config

    def test_understand_map_uses_minimax_mcp_when_configured(self) -> None:
        config = self.build_config()
        config.vision_enabled = True
        config.vision_provider = "minimax_mcp"
        config.minimax_token_plan_key = "token-plan-key"
        fake_client = FakeMcpClient()
        service = MapVisionService(config, mcp_client=fake_client)
        project = ProjectRecord.create(name="课堂项目", base_map=config.default_basemap())

        result = service.understand_map(
            project_id=project.project_id,
            project=project,
            map_context={"zoom": 4, "visible_layers": ["中国年降水量分布图"]},
            focus="读图讲解",
            screen_snapshot=SAMPLE_SNAPSHOT,
        )

        self.assertTrue(result["used_vision"])
        self.assertIn("东南多", result["summary"])
        self.assertTrue(Path(result["snapshot_path"]).exists())
        self.assertEqual(len(fake_client.calls), 1)
        self.assertIn("直接读取", fake_client.calls[0]["prompt"])

    def test_understand_map_falls_back_when_not_configured(self) -> None:
        config = self.build_config()
        service = MapVisionService(config)
        project = ProjectRecord.create(name="课堂项目", base_map=config.default_basemap())

        result = service.understand_map(
            project_id=project.project_id,
            project=project,
            map_context={},
            screen_snapshot=SAMPLE_SNAPSHOT,
        )

        self.assertFalse(result["used_vision"])
        self.assertIn("未配置", result["reason"])
        self.assertTrue(Path(result["snapshot_path"]).exists())

    def test_understand_map_uses_mimo_direct_when_configured(self) -> None:
        # v1.2 default provider is Mimo. Vision goes through chat completions
        # with a multimodal ``content`` array; no subprocess required.
        config = self.build_config()
        config.vision_enabled = True
        config.vision_provider = "mimo"
        config.mimo_api_key = "mimo-test-key"
        fake_llm = FakeLLMClient()
        service = MapVisionService(config, llm_client=fake_llm)
        project = ProjectRecord.create(name="课堂项目", base_map=config.default_basemap())

        result = service.understand_map(
            project_id=project.project_id,
            project=project,
            map_context={"zoom": 4, "visible_layers": ["中国年降水量分布图"]},
            focus="读图讲解",
            screen_snapshot=SAMPLE_SNAPSHOT,
        )

        self.assertTrue(result["used_vision"])
        self.assertEqual(result["provider"], "mimo")
        self.assertIn("东南沿海", result["summary"])
        self.assertTrue(Path(result["snapshot_path"]).exists())

        # Verify the multimodal message shape — should contain a text block
        # AND an image_url data-URL block.
        self.assertEqual(len(fake_llm.calls), 1)
        call = fake_llm.calls[0]
        self.assertEqual(call["model"], "mimo-v2.5")
        content_blocks = call["messages"][0]["content"]
        self.assertEqual(content_blocks[0]["type"], "text")
        self.assertIn("直接读取", content_blocks[0]["text"])
        self.assertEqual(content_blocks[1]["type"], "image_url")
        self.assertTrue(content_blocks[1]["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_understand_map_mimo_path_reports_runtime_error_gracefully(self) -> None:
        config = self.build_config()
        config.vision_enabled = True
        config.vision_provider = "mimo"
        config.mimo_api_key = "mimo-test-key"

        class _ExplodingLLM:
            def chat_completion(self, messages, **kwargs):
                raise RuntimeError("network down")

        service = MapVisionService(config, llm_client=_ExplodingLLM())
        project = ProjectRecord.create(name="课堂项目", base_map=config.default_basemap())

        result = service.understand_map(
            project_id=project.project_id,
            project=project,
            map_context={},
            screen_snapshot=SAMPLE_SNAPSHOT,
        )

        self.assertFalse(result["used_vision"])
        self.assertIn("Xiaomi MiMo", result["reason"])
        self.assertIn("已回退", result["reason"])
        # Snapshot still saved so the operator can inspect what was sent.
        self.assertTrue(Path(result["snapshot_path"]).exists())


class RuntimeVisionIntegrationTest(unittest.TestCase):
    def test_explain_current_view_prefers_vision_summary_when_available(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root_dir = Path(temp_dir.name)
        config = AppConfig(root_dir=root_dir)
        config.data_dir = root_dir / "backend" / "data"
        config.state_dir = config.data_dir / "state"
        config.uploads_dir = config.data_dir / "uploads"
        config.outputs_dir = config.data_dir / "outputs"
        config.ensure_dirs()
        runtime = WebGISRuntime(config=config, store=RuntimeStore(config.state_file))
        project = runtime.create_project()

        runtime.vision_service.understand_map = lambda **kwargs: {
            "used_vision": True,
            "summary": "视觉读图：图中降水量呈现东南沿海高、西北内陆低。",
        }
        result = runtime._execute_assistant_action(
            project["project_id"],
            {"tool_name": "explain_current_view", "tool_params": {"focus": "读图讲解"}},
            {"screen_snapshot": SAMPLE_SNAPSHOT},
        )

        self.assertIn("视觉读图", result["assistant_message"])
        self.assertIn("结构化地图上下文补充", result["assistant_message"])
