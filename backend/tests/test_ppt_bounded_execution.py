"""Bounded PPT execution uses synthetic converters, never Office or a model."""
import asyncio
import io
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
from fastapi import HTTPException, Request, UploadFile

from backend.app import main
from backend.app.services.auth import AuthContext
from backend.app.services.bounded_executor import BoundedExecutor, ExecutorBusy
from backend.app.services.ppt_renderer import PptRenderError


class PptBoundedExecutionTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.executor = BoundedExecutor()
        self.previous_executor = main.app.state.ppt_executor
        main.app.state.ppt_executor = self.executor
        self.release = threading.Event()
        self.started = threading.Event()
        self.patches = [
            patch.object(main, "config", SimpleNamespace(
                auth_mode="disabled", max_ppt_upload_bytes=1024,
                outputs_dir=Path(self.directory.name),
            )),
            patch.object(main, "auth_service", None),
            patch.object(main, "runtime", SimpleNamespace(health=lambda: {"status": "ok"})),
        ]
        for item in self.patches:
            item.start()

    async def asyncTearDown(self):
        self.release.set()
        await asyncio.to_thread(self.executor.shutdown)
        main.app.state.ppt_executor = self.previous_executor
        for item in reversed(self.patches):
            item.stop()
        self.directory.cleanup()

    def blocked(self, *args):
        self.started.set()
        if not self.release.wait(3):
            raise TimeoutError("synthetic converter was not released")
        return {"status": "success", "slides": []}

    async def wait_started(self):
        self.assertTrue(await asyncio.to_thread(self.started.wait, 2))

    async def wait_capacity(self):
        deadline = asyncio.get_running_loop().time() + 2
        while True:
            try:
                return await self.executor.run(lambda: "reused")
            except ExecutorBusy:
                if asyncio.get_running_loop().time() >= deadline:
                    raise
                await asyncio.sleep(0.005)

    def request(self, user="teacher-a"):
        request = Request({"type": "http", "app": main.app})
        request.state.auth = AuthContext(user={"user_id": user}, session_id="", csrf_hash="")
        return request

    def upload(self, payload=b"synthetic", filename="deck.pptx"):
        return UploadFile(io.BytesIO(payload), filename=filename)

    async def test_slow_render_keeps_actual_health_responsive_and_rejects_third_request(self):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
            with patch.object(main, "render_pptx_to_images", side_effect=self.blocked) as converter:
                first = asyncio.create_task(client.post("/ppt/render", files={"file": ("one.pptx", b"one")}))
                await self.wait_started()
                # This submission reaches admission before its first await.
                queued = asyncio.create_task(self.executor.run(
                    main.render_pptx_to_images, main.config, "queued.pptx", b"queued"
                ))
                await asyncio.sleep(0)
                health = await asyncio.wait_for(client.get("/health"), timeout=1)
                self.assertEqual(health.status_code, 200)
                self.assertEqual(health.json(), {"status": "ok"})
                overloaded = await asyncio.wait_for(client.post("/ppt/render", files={"file": ("three.pptx", b"three")}), timeout=1)
                self.assertEqual(overloaded.status_code, 503)
                self.assertEqual(overloaded.json()["detail"]["code"], "PPT_RENDERER_BUSY")
                self.assertEqual(converter.call_count, 1)
                self.release.set()
                self.assertEqual((await first).status_code, 200)
                self.assertEqual((await queued)["status"], "success")
                self.assertEqual(converter.call_count, 2)

    async def test_result_filename_bytes_and_grant_stay_on_original_request(self):
        request = self.request()
        loop_thread = threading.get_ident()
        converter_threads = []
        payload = {"status": "success", "renderer": "synthetic", "slides": [{"index": 0}]}

        def convert(config, filename, raw):
            self.assertIs(config, main.config)
            self.assertEqual((filename, raw), ("deck.ppt", b"source"))
            converter_threads.append(threading.get_ident())
            return payload

        def grant(seen_request, seen_payload, *, allowed_roots):
            self.assertEqual(threading.get_ident(), loop_thread)
            self.assertIs(seen_request, request)
            self.assertIs(seen_payload, payload)
            self.assertEqual(allowed_roots, (main.config.outputs_dir / "ppt_previews",))

        with patch.object(main, "render_pptx_to_images", side_effect=convert), patch.object(main, "_grant_response_files", side_effect=grant) as grants:
            self.assertIs(await main.render_ppt(request, self.upload(b"source", "deck.ppt")), payload)
        self.assertNotEqual(converter_threads, [loop_thread])
        grants.assert_called_once()

    async def test_existing_converter_errors_preserve_status_and_detail(self):
        for status in (400, 503):
            with self.subTest(status=status):
                error = PptRenderError("EXISTING_ERROR", "preserved", {"retained": True}, status)
                with patch.object(main, "render_pptx_to_images", side_effect=error), patch.object(main, "_grant_response_files") as grants:
                    with self.assertRaises(HTTPException) as raised:
                        await main.render_ppt(self.request(), self.upload())
                self.assertEqual(raised.exception.status_code, status)
                self.assertEqual(raised.exception.detail, error.to_dict())
                grants.assert_not_called()
        self.assertEqual(await self.wait_capacity(), "reused")

    async def test_upload_ceiling_precedes_execution_and_grants(self):
        main.config.max_ppt_upload_bytes = 4
        with patch.object(main, "render_pptx_to_images") as converter, patch.object(main, "_grant_response_files") as grants:
            with self.assertRaises(HTTPException) as raised:
                await main.render_ppt(self.request(), self.upload(b"oversize"))
        self.assertEqual(raised.exception.status_code, 413)
        converter.assert_not_called()
        grants.assert_not_called()
        self.assertIsNone(self.executor._worker)

    async def test_cancelled_running_request_keeps_capacity_and_never_grants_late_result(self):
        with patch.object(main, "render_pptx_to_images", side_effect=self.blocked), patch.object(main, "_grant_response_files") as grants:
            running = asyncio.create_task(main.render_ppt(self.request(), self.upload()))
            await self.wait_started()
            running.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await running
            queued = asyncio.create_task(self.executor.run(lambda: "next"))
            await asyncio.sleep(0)
            with self.assertRaises(ExecutorBusy):
                await self.executor.run(lambda: "overload")
            self.release.set()
            self.assertEqual(await queued, "next")
            grants.assert_not_called()
        self.assertEqual(await self.wait_capacity(), "reused")

    async def test_cancelled_queued_request_never_runs_or_accumulates_backlog(self):
        running = asyncio.create_task(self.executor.run(self.blocked))
        await self.wait_started()
        converter = Mock(return_value="should not run")
        queued = asyncio.create_task(self.executor.run(converter))
        await asyncio.sleep(0)
        queued.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await queued
        for _ in range(20):
            with self.assertRaises(ExecutorBusy):
                await self.executor.run(converter)
        self.release.set()
        await running
        self.assertEqual(await self.wait_capacity(), "reused")
        converter.assert_not_called()

    async def test_unexpected_converter_exception_releases_capacity_and_worker_continues(self):
        with self.assertRaisesRegex(RuntimeError, "synthetic"):
            await self.executor.run(Mock(side_effect=RuntimeError("synthetic")))
        self.assertEqual(await self.executor.run(lambda: 42), 42)

    async def test_shutdown_cancels_queue_drains_running_and_rejects_new_work(self):
        running = asyncio.create_task(self.executor.run(self.blocked))
        await self.wait_started()
        skipped = Mock()
        queued = asyncio.create_task(self.executor.run(skipped))
        await asyncio.sleep(0)
        worker = self.executor._worker
        closing = asyncio.create_task(asyncio.to_thread(self.executor.shutdown))
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(queued, timeout=1)
        self.assertFalse(closing.done())
        with self.assertRaises(ExecutorBusy):
            await self.executor.run(lambda: None)
        self.release.set()
        await running
        await closing
        skipped.assert_not_called()
        self.assertFalse(worker.is_alive())
        self.assertIsNone(self.executor._worker)
        await asyncio.to_thread(self.executor.shutdown)

    async def test_worker_start_failure_does_not_consume_capacity(self):
        with patch("backend.app.services.bounded_executor.Thread.start", side_effect=RuntimeError("start failed")):
            with self.assertRaisesRegex(RuntimeError, "start failed"):
                await self.executor.run(lambda: None)
        self.assertEqual(await self.executor.run(lambda: "retry"), "retry")

    async def test_lifespan_owns_fresh_worker_and_joins_at_shutdown(self):
        async with main.app.router.lifespan_context(main.app):
            owned = main.app.state.ppt_executor
            self.assertIsNot(owned, self.executor)
            self.assertEqual(await owned.run(lambda: "owned"), "owned")
            worker = owned._worker
        self.assertFalse(worker.is_alive())
        with self.assertRaises(ExecutorBusy):
            await owned.run(lambda: "closed")
        # A new application lifespan receives a new bounded facility.
        async with main.app.router.lifespan_context(main.app):
            self.assertIsNot(main.app.state.ppt_executor, owned)
            self.assertEqual(await main.app.state.ppt_executor.run(lambda: "restart"), "restart")

    async def test_idle_lifespan_closes_without_default_pool_or_background_thread(self):
        async def idle_lifespan():
            async with main.app.router.lifespan_context(main.app):
                self.assertIsNone(main.app.state.ppt_executor._worker)

        # Existing confirmation tests patch this shared module attribute.
        # Idle lifecycle cleanup must not submit work to that mocked thread.
        with patch("backend.app.runtime.threading.Thread") as background:
            await asyncio.wait_for(idle_lifespan(), timeout=0.5)
            background.assert_not_called()

    async def test_actual_file_grant_uses_original_actor_and_authorized_preview_root(self):
        preview = main.config.outputs_dir / "ppt_previews" / "synthetic" / "slide.png"
        preview.parent.mkdir(parents=True)
        preview.write_bytes(b"synthetic image")
        result = {"slides": [{"image_url": "/files/outputs/ppt_previews/synthetic/slide.png"}]}
        request = self.request("teacher-a")
        service = Mock()
        with patch.object(main, "auth_service", service), patch.object(main, "render_pptx_to_images", return_value=result), patch.object(main.resource_access, "resolve_public_reference", return_value=preview):
            self.assertEqual(await main.render_ppt(request, self.upload()), result)
        service.grant_file.assert_called_once_with("teacher-a", preview)

    async def test_zero_queue_configuration_rejects_second_running_request(self):
        only_worker = BoundedExecutor(max_queued=0)
        try:
            first = asyncio.create_task(only_worker.run(self.blocked))
            await self.wait_started()
            with self.assertRaises(ExecutorBusy):
                await only_worker.run(lambda: "second")
            self.release.set()
            await first
        finally:
            self.release.set()
            await asyncio.to_thread(only_worker.shutdown)


if __name__ == "__main__":
    unittest.main()
