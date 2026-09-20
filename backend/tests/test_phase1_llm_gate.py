"""Phase-1 acceptance C6: outbound LLM admission gate (fake provider only).

No real provider is contacted — ``urllib.request.urlopen`` is patched with
an in-process fake. Covers saturation, queue timeout, slot release on
failure, and full release after completion.
"""
from __future__ import annotations

import json
import threading
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from backend.app.config import AppConfig
from backend.app.services.minimax_client import LLMClient


def _make_client(tmp_path: Path, max_concurrent: int, queue_timeout: float) -> LLMClient:
    config = AppConfig(root_dir=tmp_path)
    config.minimax_api_key = "test-key"
    # Force the OpenAI wire format so the fake response shape is stable.
    config.minimax_base_url = "http://127.0.0.1:9/v1"
    config.llm_max_concurrent = max_concurrent
    config.llm_queue_timeout_seconds = queue_timeout
    return LLMClient(config)


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class LlmAdmissionGateTest(unittest.TestCase):
    def test_concurrent_calls_bounded_and_all_complete(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            client = _make_client(Path(tmp), max_concurrent=2, queue_timeout=30.0)
            entered = []
            peak = []
            lock = threading.Lock()
            release = threading.Event()

            def fake_urlopen(request, timeout=None):
                with lock:
                    entered.append(1)
                    peak.append(len(entered))
                release.wait(timeout=10)
                with lock:
                    entered.pop()
                return _FakeResponse(json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode())

            results = []
            errors = []

            def worker():
                try:
                    results.append(client.chat_completion([{"role": "user", "content": "hi"}]))
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)

            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                threads = [threading.Thread(target=worker) for _ in range(6)]
                for thread in threads:
                    thread.start()
                import time

                deadline = time.time() + 5
                while len(entered) < 2 and time.time() < deadline:
                    time.sleep(0.02)
                self.assertEqual(len(entered), 2, "concurrency must be bounded at the gate size")
                release.set()
                for thread in threads:
                    thread.join(timeout=10)
            self.assertFalse(errors)
            self.assertEqual(results, ["ok"] * 6)
            # Gate fully released afterwards.
            self.assertTrue(client._admission.acquire(timeout=0.1))
            client._admission.release()

    def test_queue_timeout_raises_actionable_error(self) -> None:
        import tempfile
        import time

        with tempfile.TemporaryDirectory() as tmp:
            client = _make_client(Path(tmp), max_concurrent=1, queue_timeout=0.2)
            holder_done = threading.Event()

            def slow_urlopen(request, timeout=None):
                time.sleep(0.6)
                return _FakeResponse(json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode())

            def holder():
                try:
                    client.chat_completion([{"role": "user", "content": "hi"}])
                finally:
                    holder_done.set()

            with patch("urllib.request.urlopen", side_effect=slow_urlopen):
                thread = threading.Thread(target=holder)
                thread.start()
                time.sleep(0.15)
                with self.assertRaises(RuntimeError) as ctx:
                    client.chat_completion([{"role": "user", "content": "second"}])
                self.assertIn("并发", str(ctx.exception))
                thread.join(timeout=10)
            self.assertTrue(holder_done.is_set())

    def test_slot_released_after_transport_failure(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            client = _make_client(Path(tmp), max_concurrent=1, queue_timeout=1.0)

            def failing_urlopen(request, timeout=None):
                raise urllib.error.URLError("connection refused (synthetic)")

            with patch("urllib.request.urlopen", side_effect=failing_urlopen):
                with self.assertRaises(RuntimeError):
                    client.chat_completion([{"role": "user", "content": "hi"}])
            # The failed call must have returned its slot.
            self.assertTrue(client._admission.acquire(timeout=0.1))
            client._admission.release()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
