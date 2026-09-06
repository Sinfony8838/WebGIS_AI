from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import main as app_main
from backend.app.config import AppConfig
from backend.app.runtime import WebGISRuntime
from backend.app.services.auth import AuthService


class LessonRehearsalApiTest(unittest.TestCase):
    """模拟测试创建的 HTTP 层回归（E2E 验收发现）。

    create_lesson_rehearsal 路由曾用 ``_current_auth(request)["user"]`` 对
    AuthContext 下标访问，任何合法请求都 TypeError → 500，UI「开启模拟测试」
    完全不可用（单测直调 runtime 绕过了该层）。
    """

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_config = app_main.config
        self.previous_runtime = app_main.runtime
        self.previous_auth_service = app_main.auth_service
        config = AppConfig(root_dir=Path(self.temp_dir.name), auth_mode="users")
        config.minimax_api_key = ""
        config.minimax_token_plan_key = ""
        config.ensure_dirs()
        app_main.config = config
        app_main.runtime = WebGISRuntime(config=config)
        app_main.auth_service = AuthService(config.auth_db_path)
        self.client = TestClient(app_main.app)

    def tearDown(self) -> None:
        self.client.close()
        app_main.config = self.previous_config
        app_main.runtime = self.previous_runtime
        app_main.auth_service = self.previous_auth_service
        self.temp_dir.cleanup()

    def test_create_rehearsal_over_http(self) -> None:
        bootstrap = self.client.post(
            "/auth/bootstrap",
            json={
                "email": "admin@school.edu.cn",
                "nickname": "系统管理员",
                "password": "Strong-Admin-2026!",
            },
        )
        self.assertEqual(bootstrap.status_code, 200, bootstrap.text)
        csrf = bootstrap.json()["csrf_token"]
        headers = {"X-WebGIS-CSRF": csrf}
        project_id = self.client.post(
            "/projects", json={"name": "模拟测试回归"}, headers=headers
        ).json()["project_id"]
        lesson = app_main.runtime.classroom.lesson_service.create_lesson(
            {"title": "人口分布模拟课", "grade": "高一"},
            source="manual",
        )
        response = self.client.post(
            "/lesson-rehearsals",
            json={"project_id": project_id, "lesson_id": lesson.lesson_id},
            headers=headers,
        )
        # 修复前：AuthContext 不可下标 → 500。
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["status"], "success")
        self.assertTrue(body["rehearsal"]["rehearsal_id"])


if __name__ == "__main__":
    unittest.main()
