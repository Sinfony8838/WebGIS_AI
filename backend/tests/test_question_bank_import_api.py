from __future__ import annotations

import io
import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import main as app_main
from backend.app.config import AppConfig
from backend.app.runtime import WebGISRuntime
from backend.app.services.auth import AuthService


class QuestionBankImportApiTest(unittest.TestCase):
    """题库导入的 HTTP 层回归：请求体校验必须可用（回归 List[UploadFile] 500）。

    E2E 验收发现：main.py 开启 `from __future__ import annotations` 后注解按
    模块命名空间求值，而 `List` 未导入，`List[UploadFile]` 在 FastAPI/pydantic
    请求校验阶段直接 500，UI 的「导入题库」完全不可用（单测直调 runtime 绕过了
    该层）。本用例锁住 HTTP 路径。
    """

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_config = app_main.config
        self.previous_runtime = app_main.runtime
        self.previous_auth_service = app_main.auth_service
        config = AppConfig(root_dir=Path(self.temp_dir.name), auth_mode="users")
        # 测试强制无 LLM key：导入走规则解析，不发起真实请求。
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

    def _bootstrap(self) -> str:
        response = self.client.post(
            "/auth/bootstrap",
            json={
                "email": "admin@school.edu.cn",
                "nickname": "系统管理员",
                "password": "Strong-Admin-2026!",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["csrf_token"]

    def _create_project(self, csrf: str) -> str:
        response = self.client.post(
            "/projects",
            json={"name": "题库导入回归"},
            headers={"X-WebGIS-CSRF": csrf},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["project_id"]

    def test_import_endpoint_accepts_multipart_and_runs_job(self) -> None:
        csrf = self._bootstrap()
        project_id = self._create_project(csrf)

        buffer = io.BytesIO()
        from docx import Document

        Document().save(buffer)
        buffer.seek(0)

        response = self.client.post(
            "/question-banks/import",
            data={"project_id": project_id},
            files={
                "files": (
                    "空题库.docx",
                    buffer.getvalue(),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
            headers={"X-WebGIS-CSRF": csrf},
        )
        # 修复前：pydantic 在请求校验阶段抛 PydanticUserError → 500。
        self.assertEqual(response.status_code, 200, response.text)
        job_id = response.json()["job_id"]

        status = ""
        for _ in range(50):
            job = self.client.get(f"/jobs/{job_id}").json()
            status = str(job.get("status") or "")
            if status in {"completed", "failed"}:
                break
            time.sleep(0.1)
        # 空 DOCX 不是合法题库：校验通过的请求应进入后台任务并如实失败，
        # 而不是在 HTTP 层崩溃。
        self.assertEqual(status, "failed")


if __name__ == "__main__":
    unittest.main()
