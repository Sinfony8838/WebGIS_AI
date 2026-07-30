from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import main as app_main
from backend.app.config import AppConfig
from backend.app.runtime import WebGISRuntime
from backend.app.services.auth import AuthService


class AuthApiTest(unittest.TestCase):
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

    def tearDown(self) -> None:
        self.client.close()
        app_main.config = self.previous_config
        app_main.runtime = self.previous_runtime
        app_main.auth_service = self.previous_auth_service
        self.temp_dir.cleanup()

    def bootstrap_admin(self) -> tuple[dict, str]:
        response = self.client.post(
            "/auth/bootstrap",
            json={
                "email": "admin@school.edu.cn",
                "nickname": "系统管理员",
                "password": "Strong-Admin-2026!",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.last_bootstrap_response = response
        payload = response.json()
        return payload["user"], payload["csrf_token"]

    def test_bootstrap_cookie_csrf_and_origin_protection(self) -> None:
        _user, csrf = self.bootstrap_admin()
        cookie = self.client.cookies.get(app_main.SESSION_COOKIE)
        self.assertTrue(cookie)
        set_cookie = self.last_bootstrap_response.headers["set-cookie"].lower()
        self.assertIn("httponly", set_cookie)
        self.assertIn("samesite=lax", set_cookie)

        missing_csrf = self.client.post("/projects", json={"name": "blocked"})
        self.assertEqual(missing_csrf.status_code, 403)
        rejected_origin = self.client.post(
            "/projects",
            json={"name": "blocked"},
            headers={"X-WebGIS-CSRF": csrf, "Origin": "https://evil.example"},
        )
        self.assertEqual(rejected_origin.status_code, 403)
        accepted = self.client.post(
            "/projects",
            json={"name": "owned"},
            headers={"X-WebGIS-CSRF": csrf},
        )
        self.assertEqual(accepted.status_code, 200, accepted.text)

    def test_teacher_cannot_access_admin_or_another_teachers_project(self) -> None:
        _admin, csrf = self.bootstrap_admin()
        admin_project = self.client.post(
            "/projects",
            json={"name": "admin project"},
            headers={"X-WebGIS-CSRF": csrf},
        ).json()
        created = self.client.post(
            "/admin/users",
            json={
                "email": "teacher.one@school.edu.cn",
                "nickname": "教师一",
                "role": "teacher",
            },
            headers={"X-WebGIS-CSRF": csrf},
        )
        self.assertEqual(created.status_code, 200, created.text)

        teacher_client = TestClient(app_main.app)
        try:
            login = teacher_client.post(
                "/auth/login",
                json={
                    "email": "teacher.one@school.edu.cn",
                    "password": created.json()["temporary_password"],
                },
            )
            self.assertEqual(login.status_code, 200, login.text)
            teacher_csrf = login.json()["csrf_token"]
            changed = teacher_client.post(
                "/auth/change-password",
                json={
                    "current_password": created.json()["temporary_password"],
                    "new_password": "Teacher-New-Password-2026!",
                },
                headers={"X-WebGIS-CSRF": teacher_csrf},
            )
            self.assertEqual(changed.status_code, 200, changed.text)
            self.assertEqual(teacher_client.get("/admin/users").status_code, 403)
            self.assertEqual(
                teacher_client.get(f"/projects/{admin_project['project_id']}").status_code,
                404,
            )
            own = teacher_client.post(
                "/projects",
                json={"name": "teacher project"},
                headers={"X-WebGIS-CSRF": teacher_csrf},
            )
            self.assertEqual(own.status_code, 200, own.text)
        finally:
            teacher_client.close()

    def test_public_account_contract_uses_email_and_nickname(self) -> None:
        admin, _csrf = self.bootstrap_admin()

        self.assertEqual(admin["email"], "admin@school.edu.cn")
        self.assertEqual(admin["nickname"], "系统管理员")
        self.assertNotIn("username", admin)
        self.assertNotIn("display_name", admin)

    def test_kb_upload_uses_the_authenticated_owner(self) -> None:
        admin, csrf = self.bootstrap_admin()
        upload_result = {
            "status": "success",
            "material": {
                "material_id": "material_test",
                "url": "/files/uploads/kb_materials/test.png",
            },
        }
        with patch.object(
            app_main.runtime,
            "kb_upload_material",
            return_value=upload_result,
        ) as upload:
            response = self.client.post(
                "/kb/materials/upload",
                data={"kb_item_id": "kb_test"},
                files={"file": ("test.png", b"png", "image/png")},
                headers={"X-WebGIS-CSRF": csrf},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            upload.call_args.kwargs["owner_user_id"],
            admin["user_id"],
        )

    def test_population_version_compare_route_runs_after_login(self) -> None:
        self.bootstrap_admin()
        expected = {"status": "success", "changes": []}
        with patch.object(
            app_main.runtime,
            "compare_population_source_versions",
            return_value=expected,
        ):
            response = self.client.get(
                "/population-sources/versions/compare",
                params={"from_version": "v1", "to_version": "v2"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), expected)


if __name__ == "__main__":
    unittest.main()
