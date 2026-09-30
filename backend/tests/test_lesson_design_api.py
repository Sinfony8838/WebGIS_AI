from __future__ import annotations

import tempfile
import unittest
from io import BytesIO
from pathlib import Path

import fitz
from docx import Document
from fastapi.testclient import TestClient
from PIL import Image

from backend.app import main as app_main
from backend.app.config import AppConfig
from backend.app.runtime import WebGISRuntime
from backend.app.services.auth import AuthService
from backend.tests.test_lesson_docx_import import _sample_docx_bytes


class LessonDesignApiTest(unittest.TestCase):
    """教案设计 HTTP 层：Word 导入、迁移、导出（docx/pdf）与访问控制。"""

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
        bootstrap = self.client.post(
            "/auth/bootstrap",
            json={"email": "admin@school.edu.cn", "nickname": "系统管理员", "password": "Strong-Admin-2026!"},
        )
        self.assertEqual(bootstrap.status_code, 200, bootstrap.text)
        self.headers = {"X-WebGIS-CSRF": bootstrap.json()["csrf_token"]}
        self.project_id = self.client.post(
            "/projects", json={"name": "教案导入"}, headers=self.headers
        ).json()["project_id"]

    def tearDown(self) -> None:
        self.client.close()
        app_main.config = self.previous_config
        app_main.runtime = self.previous_runtime
        app_main.auth_service = self.previous_auth_service
        self.temp_dir.cleanup()

    def test_import_docx_creates_new_unconfirmed_design(self) -> None:
        response = self.client.post(
            "/lesson-design/import-docx",
            data={"project_id": self.project_id},
            files={"file": ("人口迁移教案.docx", BytesIO(_sample_docx_bytes()), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["design"]["status"], "active")
        self.assertEqual(payload["design"]["draft"]["title"], "人口的空间变化")
        self.assertTrue(any(item["kind"] == "image" for item in payload["unclassified"]))
        # 返回的图片 public_url 可访问
        image_url = next(item["url"] for item in payload["unclassified"] if item["kind"] == "image")
        fetched = self.client.get(image_url, headers=self.headers)
        self.assertEqual(fetched.status_code, 200)

    def test_import_docx_rejects_non_docx(self) -> None:
        response = self.client.post(
            "/lesson-design/import-docx",
            data={"project_id": self.project_id},
            files={"file": ("教案.doc", BytesIO(b"old format"), "application/msword")},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(".docx", response.json()["detail"])

    def test_design_export_endpoints_return_artifacts(self) -> None:
        created = self.client.post(
            "/lesson-design/sessions", json={"project_id": self.project_id}, headers=self.headers
        ).json()
        design_id = created["design_id"]
        for fmt in ("docx", "pdf"):
            response = self.client.post(
                f"/lesson-design/sessions/{design_id}/export/{fmt}",
                json={"project_id": self.project_id},
                headers=self.headers,
            )
            self.assertEqual(response.status_code, 200, response.text)
            artifact = response.json()["artifact"]
            self.assertTrue(Path(artifact["path"]).is_file())
            if fmt == "pdf":
                with fitz.open(artifact["path"]) as pdf:
                    self.assertGreaterEqual(pdf.page_count, 1)

    def test_lesson_pdf_export_endpoint(self) -> None:
        lesson = app_main.runtime.classroom.lesson_service.create_lesson(
            {"title": "人口分布", "grade": "高一", "objectives": [], "stages": [],
             "metadata": {"project_id": self.project_id}}
        )
        response = self.client.post(
            f"/lessons/{lesson.lesson_id}/exports/pdf",
            json={"project_id": self.project_id},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(Path(response.json()["artifact"]["path"]).is_file())

    def test_migration_endpoints(self) -> None:
        created = self.client.post(
            "/lesson-design/sessions", json={"project_id": self.project_id}, headers=self.headers
        ).json()
        design_id = created["design_id"]
        # 直接写旧字段
        record = app_main.runtime.store.get_lesson_design(design_id)
        record.draft["core_questions"] = {"core": "人口为何迁移？", "sub_questions": ["谁在迁移？"]}
        record.draft["stages"] = [{"stage_id": "s1", "title": "导入", "minutes": 40, "scene": {}}]
        app_main.runtime.store.upsert_lesson_design(record)
        preview = self.client.get(f"/lesson-design/sessions/{design_id}/migration-preview", headers=self.headers)
        self.assertEqual(preview.status_code, 200)
        self.assertTrue(preview.json()["available"])
        applied = self.client.post(
            f"/lesson-design/sessions/{design_id}/migration/apply",
            json={"expected_revision": preview.json().get("revision", record.revision)},
            headers=self.headers,
        )
        self.assertEqual(applied.status_code, 200, applied.text)
        again = self.client.post(
            f"/lesson-design/sessions/{design_id}/migration/apply",
            json={},
            headers=self.headers,
        )
        self.assertEqual(again.status_code, 400)

    def test_accept_all_endpoint(self) -> None:
        created = self.client.post(
            "/lesson-design/sessions", json={"project_id": self.project_id}, headers=self.headers
        ).json()
        design_id = created["design_id"]
        record = app_main.runtime.store.get_lesson_design(design_id)
        record.draft["objectives"] = ["描述人口分布"]
        app_main.runtime.store.upsert_lesson_design(record)
        response = self.client.post(
            f"/lesson-design/sessions/{design_id}/sections/all/resolve",
            json={"decision": "accept", "expected_revision": record.revision},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["design"]["section_status"]["objectives"], "confirmed")


if __name__ == "__main__":
    unittest.main()
