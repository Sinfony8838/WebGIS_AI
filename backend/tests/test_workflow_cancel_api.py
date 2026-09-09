from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import main as app_main
from backend.app.config import AppConfig
from backend.app.models import WorkflowRecord
from backend.app.runtime import WebGISRuntime
from backend.app.services.auth import AuthService


class WorkflowCancelApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_config = app_main.config
        self.previous_runtime = app_main.runtime
        self.previous_auth_service = app_main.auth_service

        config = AppConfig(root_dir=Path(self.temp_dir.name), auth_mode="users")
        config.ensure_dirs()
        app_main.config = config
        app_main.runtime = WebGISRuntime(config=config)
        app_main.auth_service = AuthService(config.auth_db_path)
        self.client = TestClient(app_main.app)

        bootstrap = self.client.post(
            "/auth/bootstrap",
            json={
                "email": "admin@school.edu.cn",
                "nickname": "系统管理员",
                "password": "Strong-Admin-2026!",
            },
        )
        self.assertEqual(bootstrap.status_code, 200, bootstrap.text)
        self.csrf = bootstrap.json()["csrf_token"]
        project_response = self.client.post(
            "/projects",
            json={"name": "workflow cancellation"},
            headers={"X-WebGIS-CSRF": self.csrf},
        )
        self.assertEqual(project_response.status_code, 200, project_response.text)
        self.project_id = project_response.json()["project_id"]

        self.workflow = WorkflowRecord.create(
            project_id=self.project_id,
            workflow_json={"version": "1.0", "steps": []},
        )
        app_main.runtime.store.create_workflow(self.workflow)

    def tearDown(self) -> None:
        self.client.close()
        app_main.config = self.previous_config
        app_main.runtime = self.previous_runtime
        app_main.auth_service = self.previous_auth_service
        self.temp_dir.cleanup()

    def test_cancel_requires_csrf_and_routes_to_executor(self) -> None:
        missing_csrf = self.client.post(f"/workflow/{self.workflow.workflow_id}/cancel")
        self.assertEqual(missing_csrf.status_code, 403, missing_csrf.text)

        with patch.object(
            app_main.runtime.workflow_executor,
            "cancel_workflow",
            return_value=1,
        ) as cancel:
            response = self.client.post(
                f"/workflow/{self.workflow.workflow_id}/cancel",
                headers={"X-WebGIS-CSRF": self.csrf},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json(),
            {
                "status": "success",
                "workflow_id": self.workflow.workflow_id,
                "workflow_status": "pending",
                "cancelled_requests": 1,
            },
        )
        cancel.assert_called_once_with(self.workflow.workflow_id)

    def test_cancel_unknown_workflow_returns_404(self) -> None:
        response = self.client.post(
            "/workflow/wf_missing/cancel",
            headers={"X-WebGIS-CSRF": self.csrf},
        )
        self.assertEqual(response.status_code, 404, response.text)


if __name__ == "__main__":
    unittest.main()
