"""语音 WebSocket 端点（/assistant/voice/stream）行为测试。

用 fastapi.testclient 驱动真实端点：鉴权失败 4401、ASR 不可用 4403 附带
原因 JSON、就绪后二进制 PCM → partial/final 事件与 flush 协议。识别引擎
用 FakeEngine/FakeSession 替换，不依赖真实模型。
"""
from __future__ import annotations

import unittest
from importlib.util import find_spec
from typing import Any, Dict, List
from unittest import mock

if find_spec("fastapi") is not None:
    from fastapi import WebSocketDisconnect
    from fastapi.testclient import TestClient

    from backend.app import main as app_main


class FakeSession:
    """Echo 式识别会话：每次 feed 先给 partial 再给 final。"""

    def __init__(self) -> None:
        self.feed_calls: List[bytes] = []
        self.flushed = False
        self.closed = False

    def feed(self, pcm16: bytes) -> List[Dict[str, Any]]:
        self.feed_calls.append(pcm16)
        return [
            {"type": "partial", "text": "切换到"},
            {"type": "final", "text": "切换到三维地球"},
        ]

    def flush(self):
        self.flushed = True
        return {"type": "final", "text": "切换到三维地球"}

    def close(self) -> None:
        self.closed = True


def make_fake_engine(available: bool = True, state: str = "ready", reason: str = "") -> mock.Mock:
    engine = mock.Mock()
    engine.status.return_value = {
        "available": available,
        "state": state,
        "reason": reason,
        "model": "sherpa-onnx-streaming-paraformer-bilingual-zh-en" if available else "",
        "model_dir": "C:/fake",
    }
    if available:
        engine.create_session.return_value = FakeSession()
    else:
        engine.create_session.side_effect = RuntimeError("voice ASR models missing: encoder.int8.onnx")
    return engine


@unittest.skipIf(find_spec("fastapi") is None, "fastapi is not installed in this Python environment")
class VoiceStreamEndpointTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app_main.app)
        self.previous_auth_mode = app_main.config.auth_mode
        app_main.config.auth_mode = "disabled"

    def tearDown(self) -> None:
        app_main.config.auth_mode = self.previous_auth_mode
        mock.patch.stopall()

    def test_unauthorized_close_4401(self) -> None:
        with mock.patch.object(app_main, "_websocket_authorized", return_value=False):
            # 握手即被关闭：TestClient 在进入上下文时抛出断连。
            with self.assertRaises(WebSocketDisconnect) as ctx:
                with self.client.websocket_connect("/assistant/voice/stream") as websocket:
                    websocket.receive_text()
        self.assertEqual(ctx.exception.code, 4401)

    def test_asr_unavailable_returns_reason_then_4403(self) -> None:
        engine = make_fake_engine(available=False, state="not_installed", reason="models_not_downloaded")
        mock.patch.object(app_main.runtime, "voice_asr", engine).start()
        with self.client.websocket_connect("/assistant/voice/stream") as websocket:
            payload = websocket.receive_json()
            self.assertEqual(payload["type"], "error")
            self.assertEqual(payload["reason"], "not_installed")
            self.assertEqual(payload["detail"], "models_not_downloaded")
            with self.assertRaises(WebSocketDisconnect) as ctx:
                websocket.receive_text()
        self.assertEqual(ctx.exception.code, 4403)
        engine.create_session.assert_not_called()

    def test_binary_pcm_stream_receives_partial_and_final_then_flush(self) -> None:
        engine = make_fake_engine(available=True)
        mock.patch.object(app_main.runtime, "voice_asr", engine).start()
        session: FakeSession = engine.create_session.return_value
        with self.client.websocket_connect("/assistant/voice/stream") as websocket:
            websocket.send_bytes(b"\x01\x00" * 160)
            first = websocket.receive_json()
            self.assertEqual(first["type"], "partial")
            second = websocket.receive_json()
            self.assertEqual(second, {"type": "final", "text": "切换到三维地球"})
            # flush 文本帧：服务端返回尾句 final 并关闭。
            websocket.send_text("flush")
            final = websocket.receive_json()
            self.assertEqual(final, {"type": "final", "text": "切换到三维地球"})
        self.assertTrue(session.flushed)
        self.assertTrue(session.closed)
        self.assertEqual(session.feed_calls, [b"\x01\x00" * 160])

    def test_create_session_failure_returns_load_failed_and_4403(self) -> None:
        # 文件在但真实加载失败：available 通过、create_session 抛异常。
        engine = make_fake_engine(available=False, state="load_failed", reason="recognizer_init_failed: boom")
        mock.patch.object(app_main.runtime, "voice_asr", engine).start()
        with self.client.websocket_connect("/assistant/voice/stream") as websocket:
            payload = websocket.receive_json()
            self.assertEqual(payload["type"], "error")
            self.assertEqual(payload["reason"], "load_failed")
            with self.assertRaises(WebSocketDisconnect) as ctx:
                websocket.receive_text()
        self.assertEqual(ctx.exception.code, 4403)


if __name__ == "__main__":
    unittest.main()
