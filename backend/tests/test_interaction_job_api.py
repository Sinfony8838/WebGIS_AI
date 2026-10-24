"""Authenticated HTTP boundary for task cancellation and UI observations."""
from __future__ import annotations
from contextlib import closing
import time
import unittest
from fastapi.testclient import TestClient
from backend.app import main as app_main
from backend.tests import test_workflow_cancel_api as fixtures


class InteractionJobApiTest(unittest.TestCase):
    setUp = fixtures.WorkflowCancelApiTest.setUp

    def tearDown(self):
        app_main.runtime.store.close()
        fixtures.WorkflowCancelApiTest.tearDown(self)

    def create_job(self, owner=None):
        user = self.client.get("/auth/me").json()["user"]["user_id"]
        job = app_main.runtime.store.create_job(self.project_id, "assistant", "test", request={"actor_user_id": user if owner is None else owner, "assistant_mode": "interaction"})
        app_main.runtime.store.set_job_status(job.job_id, "running")
        app_main.runtime.store.update_job_activity(job.job_id, ui_actions=[{"action_id": "uia_test", "project_id": self.project_id, "session_id": "", "type": "open_panel", "panel": "layers", "status": "pending", "expires_at": time.time() + 30, "observation": None}])
        return job

    def receipt(self):
        return {"action_id": "uia_test", "project_id": self.project_id, "session_id": "", "status": "applied", "detail": "UI applied"}

    def test_observation_requires_authentication_csrf_and_matching_scope(self):
        job = self.create_job()
        route = f"/jobs/{job.job_id}/ui-observations"
        # This client shares the fixture application; closing it must not
        # start/stop the application lifespan owned by the surrounding test.
        with closing(TestClient(app_main.app)) as anonymous:
            self.assertEqual(anonymous.post(route, json=self.receipt()).status_code, 401)
        self.assertEqual(self.client.post(route, json=self.receipt()).status_code, 403)
        headers = {"X-WebGIS-CSRF": self.csrf}
        bad = {**self.receipt(), "session_id": "other_class"}
        self.assertEqual(self.client.post(route, json=bad, headers=headers).status_code, 409)
        self.assertEqual(self.client.post(route, json=self.receipt(), headers=headers).status_code, 200)
        self.assertEqual(self.client.post(route, json=self.receipt(), headers=headers).status_code, 200)
        self.assertEqual(self.client.post(route, json={**self.receipt(), "status": "failed"}, headers=headers).status_code, 409)

    def test_another_actor_cannot_cancel_or_acknowledge_a_job_even_with_project_access(self):
        job = self.create_job(owner="other_teacher")
        headers = {"X-WebGIS-CSRF": self.csrf}
        self.assertEqual(self.client.post(f"/jobs/{job.job_id}/cancel", headers=headers).status_code, 403)
        self.assertEqual(self.client.post(f"/jobs/{job.job_id}/ui-observations", json=self.receipt(), headers=headers).status_code, 403)
        self.assertFalse(job.activity.get("cancel_requested"))

    def test_cancellation_is_scoped_sticky_and_unknown_job_returns_404(self):
        job = self.create_job()
        headers = {"X-WebGIS-CSRF": self.csrf}
        self.assertEqual(self.client.post(f"/jobs/{job.job_id}/cancel", headers=headers).status_code, 200)
        app_main.runtime.store.update_job_activity(job.job_id, {"phase": "thinking", "label": "late stage"})
        self.assertTrue(job.activity["cancel_requested"])
        self.assertEqual(self.client.post(f"/jobs/{job.job_id}/ui-observations", json=self.receipt(), headers=headers).status_code, 409)
        self.assertEqual(self.client.post("/jobs/missing/cancel", headers=headers).status_code, 404)

    def test_message_records_authenticated_owner_and_negated_request_spends_no_model_calls(self):
        headers = {"X-WebGIS-CSRF": self.csrf}
        response = self.client.post("/assistant/messages", headers=headers, json={"project_id": self.project_id, "message": "不要切换到三维地球", "assistant_mode": "interaction", "ui_observation_protocol": 1})
        self.assertEqual(response.status_code, 200, response.text)
        job = app_main.runtime.store.get_job(response.json()["job_id"])
        self.assertEqual(job.request["actor_user_id"], self.client.get("/auth/me").json()["user"]["user_id"])
        deadline = time.monotonic() + 3
        while job.status in {"queued", "running"} and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(job.status, "completed")
        self.assertEqual(job.usage["model_calls"], 0)
        self.assertEqual(job.result["actions_executed"], [])
