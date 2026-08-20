from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.app.config import AppConfig
from backend.app.services.minimax_mcp_client import MiniMaxMcpClient, MiniMaxMcpError


class MiniMaxMcpClientTest(unittest.TestCase):
    def build_client(self) -> MiniMaxMcpClient:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        config = AppConfig(root_dir=Path(temp_dir.name))
        config.vision_enabled = True
        config.minimax_token_plan_key = "test-key"
        return MiniMaxMcpClient(config)

    def test_image_call_sends_documented_and_runtime_compatibility_fields(self) -> None:
        client = self.build_client()
        captured: dict = {}

        def fake_call(name: str, arguments: dict) -> dict:
            captured.update({"name": name, "arguments": arguments})
            return {"result": {"content": [{"type": "text", "text": "识别完成"}]}}

        client._call_tool = fake_call  # type: ignore[method-assign]
        result = client.understand_image("分析地形", "C:/map.png")

        self.assertEqual(result["text"], "识别完成")
        self.assertEqual(captured["name"], "understand_image")
        self.assertEqual(captured["arguments"]["image_url"], "C:/map.png")
        self.assertEqual(captured["arguments"]["image_source"], "C:/map.png")

    def test_extract_text_does_not_turn_empty_tool_output_into_success(self) -> None:
        client = self.build_client()
        client._call_tool = lambda *args, **kwargs: {"result": {"content": []}}  # type: ignore[method-assign]

        with self.assertRaisesRegex(MiniMaxMcpError, "empty"):
            client.understand_image("分析", "C:/map.png")

    def test_gif_path_is_forwarded_as_a_correctly_typed_data_url(self) -> None:
        client = self.build_client()
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        gif_path = Path(temp_dir.name) / "weather.gif"
        gif_path.write_bytes(b"GIF89a" + b"0" * 20)
        captured: dict = {}

        def fake_call(name: str, arguments: dict) -> dict:
            captured.update(arguments)
            return {"result": {"content": [{"type": "text", "text": "weather map"}]}}

        client._call_tool = fake_call  # type: ignore[method-assign]
        client.understand_image("analyze", str(gif_path))

        self.assertTrue(captured["image_source"].startswith("data:image/gif;base64,"))

    def test_stdio_decoder_accepts_utf8_and_gb18030(self) -> None:
        self.assertEqual(MiniMaxMcpClient._decode_stdio_line("地形".encode("utf-8")), "地形")
        self.assertEqual(MiniMaxMcpClient._decode_stdio_line("地形".encode("gb18030")), "地形")


if __name__ == "__main__":
    unittest.main()
