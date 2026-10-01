"""Async PPT render jobs: lifecycle, caching, ownership, cleanup and routes.

All renders are faked — no COM/LibreOffice is touched. The PowerPoint
incremental COM export itself is unit-tested in test_ppt_renderer.py with a
fake COM stack.
"""
from __future__ import annotations

import io
import json
import os
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from backend.app import main as app_main
from backend.app.config import AppConfig
from backend.app.runtime import WebGISRuntime
from backend.app.services import ppt_render_jobs
from backend.app.services.ppt_renderer import PptRenderError

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"fake-image-data" * 4


def build_pptx_bytes(slide_count: int = 3) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "ppt/presentation.xml",
            '<p:presentation xmlns:p="x"><p:sldSz cx="12192000" cy="6858000"/></p:presentation>',
        )
        for index in range(1, slide_count + 1):
            archive.writestr(f"ppt/slides/slide{index}.xml", "<p:sld/>")
    return buffer.getvalue()


class FakeRenderer:
    """Stands in for the real PowerPoint/LibreOffice render phases."""

    def __init__(self, slide_count: int = 3, fail: bool = False) -> None:
        self.slide_count = slide_count
        self.fail = fail
        self.calls = 0

    def __call__(self, config, job, source_path):
        self.calls += 1
        if self.fail:
            return None
        image_dir = job.cache_dir / "fake_png"
        image_dir.mkdir(parents=True, exist_ok=True)
        for index in range(1, self.slide_count + 1):
            (image_dir / f"slide_{index:03d}.png").write_bytes(PNG_BYTES)
        ppt_render_jobs._update_job_slides(job, "fake-renderer", image_dir, 320, 180, self.slide_count)
        return {"renderer": "fake-renderer", "width_px": 320, "height_px": 180}


class PptRenderJobServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config = AppConfig(root_dir=Path(self.temp_dir.name), auth_mode="disabled")
        self.config.ensure_dirs()
        ppt_render_jobs._jobs.clear()
        ppt_render_jobs._last_cleanup = 0.0

    def tearDown(self) -> None:
        ppt_render_jobs._jobs.clear()
        self.temp_dir.cleanup()

    def _start(self, raw: bytes, user_id: str = "user-a", fake: FakeRenderer | None = None) -> dict:
        fake = fake or FakeRenderer()
        with mock.patch.object(ppt_render_jobs, "_render_with_powerpoint", return_value=None), mock.patch.object(
            ppt_render_jobs, "_render_with_libreoffice", side_effect=fake
        ):
            payload = ppt_render_jobs.start_render_job(self.config, user_id, "deck.pptx", raw)
            job = ppt_render_jobs._jobs[payload["render_id"]]
            self.assertTrue(job.done_event.wait(timeout=5), "render thread did not finish")
        self.assertEqual(fake.calls, 1)
        return payload

    def test_job_renders_incrementally_and_completes(self) -> None:
        raw = build_pptx_bytes(3)
        payload = self._start(raw)
        self.assertTrue(payload["render_id"])
        final = ppt_render_jobs.get_render_job(self.config, "user-a", payload["render_id"])
        self.assertEqual(final["status"], "complete")
        self.assertEqual(final["renderer"], "fake-renderer")
        self.assertEqual(len(final["slides"]), 3)
        self.assertEqual([slide["index"] for slide in final["slides"]], [0, 1, 2])
        for slide in final["slides"]:
            self.assertTrue(slide["image_url"].startswith("/files/outputs/ppt_previews/cache/"))
            self.assertEqual(slide["width"], 320 * 9525)
        self.assertEqual(final["slide_width"], 320 * 9525)

    def test_manifest_written_and_reopen_uses_cache(self) -> None:
        raw = build_pptx_bytes(2)
        first = self._start(raw, fake=FakeRenderer(slide_count=2))
        self.assertTrue((self.config.outputs_dir / "ppt_previews" / "cache" / "v1" / first["render_id"] / "manifest.json").is_file())

        fake = FakeRenderer(slide_count=2)
        with mock.patch.object(ppt_render_jobs, "_render_with_powerpoint", return_value=None), mock.patch.object(
            ppt_render_jobs, "_render_with_libreoffice", side_effect=fake
        ):
            second = ppt_render_jobs.start_render_job(self.config, "user-a", "deck.pptx", raw)
        self.assertEqual(second["render_id"], first["render_id"])
        self.assertEqual(second["status"], "complete")
        self.assertTrue(second["cached"])
        self.assertEqual(fake.calls, 0, "cache hit must not re-render")
        self.assertEqual(len(second["slides"]), 2)

    def test_cache_is_per_user(self) -> None:
        raw = build_pptx_bytes(2)
        first = self._start(raw, user_id="user-a")
        fake = FakeRenderer(slide_count=2)
        with mock.patch.object(ppt_render_jobs, "_render_with_powerpoint", return_value=None), mock.patch.object(
            ppt_render_jobs, "_render_with_libreoffice", side_effect=fake
        ):
            second = ppt_render_jobs.start_render_job(self.config, "user-b", "deck.pptx", raw)
            job = ppt_render_jobs._jobs[second["render_id"]]
            self.assertTrue(job.done_event.wait(timeout=5))
        self.assertNotEqual(first["render_id"], second["render_id"])
        self.assertEqual(fake.calls, 1)

    def test_failed_job_reports_error_and_does_not_cache(self) -> None:
        raw = build_pptx_bytes(2)
        payload = self._start(raw, fake=FakeRenderer(fail=True))
        final = ppt_render_jobs.get_render_job(self.config, "user-a", payload["render_id"])
        self.assertEqual(final["status"], "failed")
        self.assertEqual(final["error"]["code"], "PPT_RENDERER_UNAVAILABLE")
        self.assertFalse(
            (self.config.outputs_dir / "ppt_previews" / "cache" / "v1" / payload["render_id"] / "manifest.json").exists()
        )

        fake = FakeRenderer()
        with mock.patch.object(ppt_render_jobs, "_render_with_powerpoint", return_value=None), mock.patch.object(
            ppt_render_jobs, "_render_with_libreoffice", side_effect=fake
        ):
            retry = ppt_render_jobs.start_render_job(self.config, "user-a", "deck.pptx", raw)
            job = ppt_render_jobs._jobs[retry["render_id"]]
            self.assertTrue(job.done_event.wait(timeout=5))
        self.assertEqual(fake.calls, 1, "failed renders must not be treated as cached")

    def test_get_render_job_ownership(self) -> None:
        job = ppt_render_jobs.PptRenderJob(
            render_id="pptj_owned",
            user_id="user-a",
            cache_dir=self.config.outputs_dir / "ppt_previews" / "cache" / "v1" / "pptj_owned",
            file_name="deck.pptx",
        )
        job.done_event.set()
        ppt_render_jobs._jobs[job.render_id] = job

        payload = ppt_render_jobs.get_render_job(self.config, "user-a", "pptj_owned")
        self.assertEqual(payload["render_id"], "pptj_owned")
        with self.assertRaises(PptRenderError) as ctx:
            ppt_render_jobs.get_render_job(self.config, "user-b", "pptj_owned")
        self.assertEqual(ctx.exception.status_code, 403)
        admin_payload = ppt_render_jobs.get_render_job(self.config, "user-b", "pptj_owned", is_admin=True)
        self.assertEqual(admin_payload["render_id"], "pptj_owned")

    def test_get_render_job_unknown_id_returns_404(self) -> None:
        with self.assertRaises(PptRenderError) as ctx:
            ppt_render_jobs.get_render_job(self.config, "user-a", "pptj_missing")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_start_rejects_invalid_payloads(self) -> None:
        with self.assertRaises(PptRenderError) as empty:
            ppt_render_jobs.start_render_job(self.config, "user-a", "deck.pptx", b"")
        self.assertEqual(empty.exception.status_code, 400)
        with self.assertRaises(PptRenderError) as wrong_format:
            ppt_render_jobs.start_render_job(self.config, "user-a", "deck.pdf", b"junk")
        self.assertEqual(wrong_format.exception.status_code, 400)

    def test_cleanup_removes_expired_and_oversized_entries(self) -> None:
        raw = build_pptx_bytes(1)
        kept = self._start(raw)
        cache_root = self.config.outputs_dir / "ppt_previews" / "cache" / "v1"

        expired = cache_root / "pptj_expired"
        expired.mkdir(parents=True)
        (expired / "manifest.json").write_text("{}", encoding="utf-8")
        old_time = time.time() - (ppt_render_jobs.CACHE_MAX_AGE_SECONDS + 3600)
        os.utime(expired / "manifest.json", (old_time, old_time))

        oversized = cache_root / "pptj_oversized"
        oversized.mkdir(parents=True)
        (oversized / "bulk.bin").write_bytes(b"x" * 4096)
        # Make oversized older than the kept render (but newer than expired) so
        # the LRU eviction order is deterministic: expired, oversized, kept.
        one_hour_ago = time.time() - 3600
        os.utime(oversized, (one_hour_ago, one_hour_ago))

        with mock.patch.object(ppt_render_jobs, "CACHE_MAX_TOTAL_BYTES", 2048):
            ppt_render_jobs._last_cleanup = 0.0
            ppt_render_jobs._maybe_cleanup_cache(self.config)

        self.assertFalse(expired.exists(), "entries older than 7 days must be removed")
        self.assertFalse(oversized.exists(), "oversized cache must evict oldest entries")
        self.assertTrue((cache_root / kept["render_id"]).exists(), "active/recent renders must be kept")


class PptRenderRouteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous = (app_main.config, app_main.runtime, app_main.auth_service)
        config = AppConfig(root_dir=Path(self.temp_dir.name), auth_mode="disabled")
        config.ensure_dirs()
        app_main.config = config
        app_main.runtime = WebGISRuntime(config=config)
        app_main.auth_service = None
        self.config = config
        ppt_render_jobs._jobs.clear()
        ppt_render_jobs._last_cleanup = 0.0
        self.client = TestClient(app_main.app)

    def tearDown(self) -> None:
        self.client.close()
        app_main.config, app_main.runtime, app_main.auth_service = self.previous
        ppt_render_jobs._jobs.clear()
        self.temp_dir.cleanup()

    def _fake_render(self, slide_count: int = 2) -> FakeRenderer:
        return FakeRenderer(slide_count=slide_count)

    def test_start_and_poll_until_complete(self) -> None:
        fake = self._fake_render(2)
        with mock.patch.object(ppt_render_jobs, "_render_with_powerpoint", return_value=None), mock.patch.object(
            ppt_render_jobs, "_render_with_libreoffice", side_effect=fake
        ):
            response = self.client.post(
                "/ppt/renders",
                files={"file": ("课件.pptx", build_pptx_bytes(2))},
            )
            self.assertEqual(response.status_code, 200, response.text)
            payload = response.json()
            self.assertTrue(payload["render_id"])
            self.assertIn(payload["status"], {"queued", "rendering", "complete"})

            final = None
            deadline = time.time() + 5
            while time.time() < deadline:
                poll = self.client.get(f"/ppt/renders/{payload['render_id']}")
                self.assertEqual(poll.status_code, 200, poll.text)
                final = poll.json()
                if final["status"] in {"complete", "failed"}:
                    break
                time.sleep(0.05)

        self.assertIsNotNone(final)
        self.assertEqual(final["status"], "complete")
        self.assertEqual(final["renderer"], "fake-renderer")
        self.assertEqual(len(final["slides"]), 2)
        self.assertEqual(final["file_name"], "课件.pptx")

    def test_start_returns_cached_result_without_rerender(self) -> None:
        fake = self._fake_render(2)
        raw = build_pptx_bytes(2)
        with mock.patch.object(ppt_render_jobs, "_render_with_powerpoint", return_value=None), mock.patch.object(
            ppt_render_jobs, "_render_with_libreoffice", side_effect=fake
        ):
            first = self.client.post("/ppt/renders", files={"file": ("deck.pptx", raw)})
            self.assertEqual(first.status_code, 200)
            deadline = time.time() + 5
            while time.time() < deadline:
                poll = self.client.get(f"/ppt/renders/{first.json()['render_id']}")
                if poll.json()["status"] == "complete":
                    break
                time.sleep(0.05)
            second = self.client.post("/ppt/renders", files={"file": ("deck.pptx", raw)})
        self.assertEqual(second.status_code, 200)
        body = second.json()
        self.assertEqual(body["status"], "complete")
        self.assertTrue(body["cached"])
        self.assertEqual(fake.calls, 1)

    def test_start_rejects_oversize_and_empty(self) -> None:
        original = self.config.max_ppt_upload_bytes
        self.config.max_ppt_upload_bytes = 128
        try:
            response = self.client.post(
                "/ppt/renders",
                files={"file": ("deck.pptx", b"PK\x03\x04" + b"z" * 512)},
            )
            self.assertEqual(response.status_code, 413, response.text)
        finally:
            self.config.max_ppt_upload_bytes = original

        empty = self.client.post("/ppt/renders", files={"file": ("deck.pptx", b"")})
        self.assertEqual(empty.status_code, 400)
        self.assertEqual(empty.json()["detail"]["code"], "EMPTY_PPTX")

    def test_poll_unknown_render_id_returns_404(self) -> None:
        response = self.client.get("/ppt/renders/pptj_does_not_exist")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"]["code"], "PPT_RENDER_NOT_FOUND")

    def test_legacy_sync_render_route_still_works(self) -> None:
        canned = {
            "status": "success",
            "file_name": "deck.pptx",
            "renderer": "fake",
            "slide_width": 100,
            "slide_height": 56,
            "slides": [{"index": 0, "image_url": "/files/outputs/ppt_previews/x/slide_001.png", "width": 100, "height": 56}],
        }
        with mock.patch.object(app_main, "render_pptx_to_images", return_value=canned) as fake_render:
            response = self.client.post("/ppt/render", files={"file": ("deck.pptx", build_pptx_bytes(1))})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "success")
        self.assertEqual(fake_render.call_count, 1)


if __name__ == "__main__":
    unittest.main()
