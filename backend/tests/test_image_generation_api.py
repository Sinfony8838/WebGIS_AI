from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import main as app_main
from backend.app.config import AppConfig
from backend.app.runtime import TRANSPARENT_PNG, WebGISRuntime
from backend.app.services.auth import AuthService


class ImageGenerationApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.previous = app_main.config, app_main.runtime, app_main.auth_service
        app_main.config = AppConfig(root_dir=Path(self.temp.name), auth_mode="users", minimax_api_key="test-key")
        app_main.config.ensure_dirs()
        app_main.runtime = WebGISRuntime(app_main.config)
        app_main.auth_service = AuthService(app_main.config.auth_db_path)
        self.client = TestClient(app_main.app)
        auth = self.client.post("/auth/bootstrap", json={
            "email": "admin@school.test", "nickname": "管理员", "password": "Test-Admin-2026!",
        })
        self.assertEqual(auth.status_code, 200, auth.text)
        self.headers = {"X-WebGIS-CSRF": auth.json()["csrf_token"]}
        self.project_id = self.client.post("/projects", json={"name": "图片测试"}, headers=self.headers).json()["project_id"]

    def tearDown(self) -> None:
        self.client.close()
        app_main.config, app_main.runtime, app_main.auth_service = self.previous
        self.temp.cleanup()

    def wait_job(self, job_id: str) -> dict:
        for _ in range(500):
            job = self.client.get(f"/jobs/{job_id}").json()
            if job["status"] in {"completed", "failed"}:
                return job
            time.sleep(0.02)
        self.fail("image job did not finish")

    def test_admin_can_use_sync_api_without_confirmation(self) -> None:
        with patch.object(app_main.runtime, "generate_image_asset", return_value={"status": "success"}) as generate:
            response = self.client.post("/image-generation", json={"project_id": self.project_id, "prompt": "地貌"}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        generate.assert_called_once()
        caps = self.client.get("/image-generation/capabilities").json()
        self.assertFalse(caps["requires_confirmation"])
        self.assertNotIn("21:9", caps["aspect_ratios"]["image-01-live"])
        self.assertNotIn("test-key", str(caps))

    def test_async_api_returns_before_provider_finishes_and_exposes_download(self) -> None:
        release = threading.Event()

        def generate(*_args, **_kwargs):
            release.wait(10)
            return {"raw_bytes": TRANSPARENT_PNG, "mime_type": "image/png", "suffix": ".png",
                    "model": "image-01", "aspect_ratio": "16:9", "request_id": "api-test"}

        with patch.object(app_main.runtime.image_generation_service, "generate", side_effect=generate) as upstream:
            try:
                response = self.client.post("/image-generation/jobs", json={"project_id": self.project_id, "prompt": "地貌"}, headers=self.headers)
                self.assertEqual(response.status_code, 202, response.text)
                job_id = response.json()["job_id"]
                self.assertIn(self.client.get(f"/jobs/{job_id}").json()["status"], {"queued", "running"})
            finally:
                release.set()
            completed = self.wait_job(job_id)
        self.assertEqual(completed["status"], "completed", completed)
        artifact = completed["result"]["artifact"]
        self.assertEqual(artifact["metadata"]["teaching_review"], "required")
        self.assertEqual(self.client.get(artifact["metadata"]["public_url"]).content, TRANSPARENT_PNG)
        upstream.assert_called_once()

    def test_failed_job_and_invalid_requests_do_not_create_artifacts(self) -> None:
        with patch.object(app_main.runtime.image_generation_service, "generate", side_effect=RuntimeError("upstream unavailable")) as generate:
            for prompt, ratio in [("  ", "16:9"), ("x" * 1501, "16:9"), ("地貌", "5:4")]:
                response = self.client.post("/image-generation/jobs", json={"project_id": self.project_id, "prompt": prompt, "aspect_ratio": ratio}, headers=self.headers)
                self.assertEqual(response.status_code, 400, response.text)
            generate.assert_not_called()
            response = self.client.post("/image-generation/jobs", json={"project_id": self.project_id, "prompt": "地貌"}, headers=self.headers)
            job = self.wait_job(response.json()["job_id"])
        self.assertEqual(job["status"], "failed")
        self.assertIn("upstream unavailable", job["error"])
        self.assertEqual(app_main.runtime.list_outputs(self.project_id)["items"], [])

    def test_role_is_taken_only_from_authenticated_session(self) -> None:
        for forged_role in ("teacher", "admin"):
            with patch.object(app_main.runtime, "submit_assistant_message", return_value={"job_id": "test"}) as submit:
                response = self.client.post("/assistant/messages", json={"project_id": self.project_id, "message": "生成一张地貌图", "actor_role": forged_role}, headers=self.headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(submit.call_args.kwargs["actor_role"], "admin")

    def test_unauthenticated_and_missing_csrf_requests_are_rejected(self) -> None:
        payload = {"project_id": self.project_id, "prompt": "地貌"}
        with patch.object(app_main.runtime, "submit_image_generation") as submit:
            self.assertEqual(self.client.post("/image-generation/jobs", json=payload).status_code, 403)
            self.client.cookies.clear()
            self.assertEqual(self.client.post("/image-generation/jobs", json=payload).status_code, 401)
            self.assertEqual(self.client.get("/image-generation/capabilities").status_code, 401)
            submit.assert_not_called()
