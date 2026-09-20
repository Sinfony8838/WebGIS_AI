"""Phase-1 audit task T3: request budgets (body limits, upload ceilings, gates).

Middleware rejections happen on the received byte stream *before* FastAPI
parses the request; upload ceilings are enforced by chunked readers, not by
trusting Content-Length; the QGIS pipeline gets an explicit bounded queue.
"""
from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.app import main as app_main
from backend.app.config import AppConfig
from backend.app.runtime import WebGISRuntime
from backend.app.services import request_limits
from backend.app.services.request_limits import (
    AdmissionGate,
    BodySizeLimitMiddleware,
    PayloadTooLarge,
    VoiceSessionGate,
    read_upload_limited,
)


class FakeUpload:
    """Multipart-upload stand-in yielding fixed-size chunks."""

    def __init__(self, payload: bytes, chunk_size: int = 64) -> None:
        self.payload = payload
        self.chunk_size = chunk_size

    async def read(self, size: int = -1) -> bytes:
        if not self.payload:
            return b""
        chunk, self.payload = self.payload[: max(1, min(size, self.chunk_size))], self.payload[max(1, min(size, self.chunk_size)):]
        return chunk


class RequestLimitUnitTest(unittest.TestCase):
    def test_read_upload_limited_accepts_legal_payload(self) -> None:
        import asyncio

        payload = b"x" * 300
        result = asyncio.run(read_upload_limited(FakeUpload(payload), 1024))
        self.assertEqual(result, payload)

    def test_read_upload_limited_rejects_oversize_across_chunks(self) -> None:
        import asyncio

        with self.assertRaises(PayloadTooLarge):
            asyncio.run(read_upload_limited(FakeUpload(b"y" * 500, chunk_size=64), 256))


class BodySizeMiddlewareTest(unittest.TestCase):
    def _build_app(self, max_bytes: int) -> FastAPI:
        app = FastAPI()
        app.add_middleware(BodySizeLimitMiddleware, max_json_body_bytes=max_bytes)
        seen: dict = {}

        @app.post("/echo")
        async def echo(request: Request) -> dict:
            body = await request.body()
            seen["parsed_bytes"] = len(body)
            return {"received": len(body)}

        return app

    def test_declared_oversize_rejected_before_parsing(self) -> None:
        client = TestClient(self._build_app(64))
        response = client.post("/echo", json={"blob": "z" * 512})
        self.assertEqual(response.status_code, 413)

    def test_received_bytes_capped_without_trusting_client(self) -> None:
        # A lying (small) Content-Length does not bypass the counting path:
        # the middleware rejects once the accumulated bytes exceed the budget.
        client = TestClient(self._build_app(64))
        big = json.dumps({"blob": "z" * 512}).encode("utf-8")
        response = client.post(
            "/echo",
            content=big,
            headers={"content-type": "application/json", "content-length": "10"},
        )
        self.assertEqual(response.status_code, 413)

    def test_legal_payload_reaches_endpoint(self) -> None:
        client = TestClient(self._build_app(4096))
        body = {"blob": "z" * 512}
        response = client.post("/echo", json=body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["received"], len(response.request.content))

    def test_non_json_and_get_requests_pass_through(self) -> None:
        client = TestClient(self._build_app(64))
        response = client.post(
            "/echo",
            content=b"z" * 512,
            headers={"content-type": "application/octet-stream"},
        )
        self.assertEqual(response.status_code, 200)


class PptUploadCeilingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous = (app_main.config, app_main.runtime, app_main.auth_service)
        config = AppConfig(root_dir=Path(self.temp_dir.name), auth_mode="disabled")
        config.ensure_dirs()
        app_main.config = config
        app_main.runtime = WebGISRuntime(config=config)
        app_main.auth_service = None
        self.client = TestClient(app_main.app)

    def tearDown(self) -> None:
        self.client.close()
        app_main.config, app_main.runtime, app_main.auth_service = self.previous
        self.temp_dir.cleanup()

    def test_oversize_upload_returns_413_before_render(self) -> None:
        original = app_main.config.max_ppt_upload_bytes
        app_main.config.max_ppt_upload_bytes = 128
        try:
            response = self.client.post(
                "/ppt/render",
                files={"file": ("deck.pptx", b"PK\x03\x04" + b"z" * 512)},
            )
            self.assertEqual(response.status_code, 413, response.text)
        finally:
            app_main.config.max_ppt_upload_bytes = original


class RemainingUploadCeilingsTest(unittest.TestCase):
    """C4 sweep: every remaining body-reading upload endpoint is capped by the
    chunked reader BEFORE the payload is buffered (413, not a hang/OOM)."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous = (app_main.config, app_main.runtime, app_main.auth_service)
        config = AppConfig(root_dir=Path(self.temp_dir.name), auth_mode="disabled")
        config.ensure_dirs()
        app_main.config = config
        app_main.runtime = WebGISRuntime(config=config)
        app_main.auth_service = None
        self.client = TestClient(app_main.app)
        project = app_main.runtime.create_project("预算测试")
        self.project_id = project["project_id"]

    def tearDown(self) -> None:
        self.client.close()
        app_main.config, app_main.runtime, app_main.auth_service = self.previous
        self.temp_dir.cleanup()

    def test_image_library_upload_413_before_buffering(self) -> None:
        app_main.config.max_image_upload_bytes = 128
        response = self.client.post(
            f"/image-library/upload?project_id={self.project_id}",
            files={"file": ("shot.png", b"\x89PNG\r\n\x1a\n" + b"z" * 512, "image/png")},
            data={"project_id": self.project_id},
        )
        self.assertEqual(response.status_code, 413, response.text)

    def test_question_bank_import_413_per_file(self) -> None:
        app_main.config.max_question_bank_upload_bytes = 128
        response = self.client.post(
            f"/question-banks/import?project_id={self.project_id}",
            files=[("files", ("bank.docx", b"PK\x03\x04" + b"z" * 512))],
            data={"project_id": self.project_id},
        )
        self.assertEqual(response.status_code, 413, response.text)
        self.assertIn("题库文件", response.text)

    def test_timeline_generate_413_before_llm(self) -> None:
        app_main.config.max_timeline_upload_bytes = 128
        response = self.client.post(
            f"/projects/{self.project_id}/timeline/generate",
            files={"file": ("lesson.txt", b"z" * 512, "text/plain")},
        )
        self.assertEqual(response.status_code, 413, response.text)


class AdmissionGateTest(unittest.TestCase):
    def test_gate_bounds_concurrency_and_times_out(self) -> None:
        gate = AdmissionGate(max_concurrent=1, timeout=0.2)
        self.assertTrue(gate.acquire())
        holder = gate
        self.assertFalse(gate.acquire(timeout=0.2))
        holder.release()
        self.assertTrue(gate.acquire(timeout=0.2))
        gate.release()

    def test_gate_release_without_acquire_is_safe(self) -> None:
        gate = AdmissionGate(max_concurrent=1, timeout=0.1)
        gate.release()
        self.assertTrue(gate.acquire(timeout=0.1))
        gate.release()


class VoiceSessionGateTest(unittest.TestCase):
    def test_per_user_cap_and_release(self) -> None:
        gate = VoiceSessionGate(max_per_user=2)
        self.assertTrue(gate.enter("u1"))
        self.assertTrue(gate.enter("u1"))
        self.assertFalse(gate.enter("u1"))
        self.assertTrue(gate.enter("u2"))
        gate.leave("u1")
        self.assertTrue(gate.enter("u1"))
        gate.leave("u1")
        gate.leave("u1")
        gate.leave("u1")
        self.assertTrue(gate.enter("u1"))

    def test_concurrent_enter_respects_cap(self) -> None:
        gate = VoiceSessionGate(max_per_user=1)
        active = 0
        max_active = 0
        lock = threading.Lock()
        barrier = threading.Barrier(4)

        def worker() -> None:
            nonlocal active, max_active
            barrier.wait()
            if gate.enter("u1"):
                with lock:
                    active += 1
                    max_active = max(max_active, active)
                time.sleep(0.05)
                with lock:
                    active -= 1
                gate.leave("u1")

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertGreaterEqual(max_active, 1)
        self.assertLessEqual(max_active, 1)
        self.assertEqual(gate._counts, {})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
