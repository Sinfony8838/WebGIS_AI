from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import main as app_main
from backend.app.config import AppConfig
from backend.app.runtime import WebGISRuntime
from backend.app.services.auth import AuthService, iso

STRONG_PASSWORD = "Teacher-Strong-2026!"
APPROVAL_MESSAGE = "注册申请已提交，管理员审核通过后方可登录。"


class RegistrationApiTestBase(unittest.TestCase):
    """API-level tests around POST /auth/register and the admin review flow."""

    registration_mode: str = "approval"
    trust_proxy_headers: bool = False
    auth_service_kwargs: dict = {}

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_config = app_main.config
        self.previous_runtime = app_main.runtime
        self.previous_auth_service = app_main.auth_service
        config = AppConfig(
            root_dir=Path(self.temp_dir.name),
            auth_mode="users",
            registration_mode=self.registration_mode,
            trust_proxy_headers=self.trust_proxy_headers,
        )
        config.ensure_dirs()
        app_main.config = config
        app_main.runtime = WebGISRuntime(config=config)
        app_main.auth_service = AuthService(config.auth_db_path, **self.auth_service_kwargs)
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
        payload = response.json()
        return payload["user"], payload["csrf_token"]

    def create_teacher(self, admin_csrf: str, email: str) -> dict:
        response = self.client.post(
            "/admin/users",
            json={"email": email, "nickname": "教师", "role": "teacher"},
            headers={"X-WebGIS-CSRF": admin_csrf},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def register(self, email: str, password: str = STRONG_PASSWORD, **overrides: str):
        payload = {
            "email": email,
            "nickname": "申请教师",
            "password": password,
            "password_confirm": password,
            **overrides,
        }
        return self.client.post("/auth/register", json=payload)

    @contextmanager
    def auth_db(self):
        """Context manager yielding a raw connection that is always closed.

        sqlite3 connections used with plain `with` only manage transactions;
        on Windows an open handle breaks TemporaryDirectory cleanup.
        """
        connection = sqlite3.connect(app_main.config.auth_db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()


class RegistrationApprovalModeTest(RegistrationApiTestBase):
    registration_mode = "approval"

    def test_bootstrap_status_advertises_approval_mode(self) -> None:
        response = self.client.get("/auth/bootstrap-status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["registration_mode"], "approval")

    def test_submission_queues_request_without_session(self) -> None:
        response = self.register("new.teacher@school.edu.cn", organization="上海中学", application_note="任教高一地理")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["status"], "submitted")
        self.assertEqual(body["message"], APPROVAL_MESSAGE)
        self.assertNotIn("set-cookie", {key.lower() for key in response.headers.keys()})

        # No session exists: the unauthenticated caller stays locked out of
        # every authenticated surface including the assistant.
        self.assertEqual(self.client.get("/auth/me").status_code, 401)
        self.assertEqual(
            self.client.post(
                "/assistant/messages",
                json={"project_id": "p", "message": "你好"},
            ).status_code,
            401,
        )

        with self.auth_db() as connection:
            user_count = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            row = connection.execute(
                "SELECT * FROM registration_requests WHERE email = ?",
                ("new.teacher@school.edu.cn",),
            ).fetchone()
        self.assertEqual(user_count, 0)
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["status"], "pending")
        self.assertEqual(row["organization"], "上海中学")
        self.assertEqual(row["application_note"], "任教高一地理")
        self.assertTrue(str(row["password_hash"]).startswith("$argon2id$"))

    def test_pending_request_cannot_login(self) -> None:
        self.register("waiting@school.edu.cn")
        response = self.client.post(
            "/auth/login",
            json={"email": "waiting@school.edu.cn", "password": STRONG_PASSWORD},
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"]["code"], "INVALID_CREDENTIALS")
        self.assertEqual(self.client.get("/auth/me").status_code, 401)

    def test_backend_ignores_password_confirm(self) -> None:
        response = self.register("confirm@school.edu.cn", password_confirm="different-value")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "submitted")

    def test_weak_password_rejected(self) -> None:
        for weak in ("abcdefgh", "12345678", "short1"):
            with self.subTest(password=weak):
                response = self.register("weak@school.edu.cn", password=weak)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["detail"]["code"], "WEAK_PASSWORD")
        with self.auth_db() as connection:
            count = connection.execute("SELECT COUNT(*) FROM registration_requests").fetchone()[0]
        self.assertEqual(count, 0)

    def test_invalid_email_rejected(self) -> None:
        for bad in ("not-an-email", "a@b", "a b@school.edu.cn", ""):
            with self.subTest(email=bad):
                response = self.register(bad)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["detail"]["code"], "INVALID_EMAIL")

    def test_overlong_fields_rejected(self) -> None:
        # Pydantic field caps answer 422; the service re-validates as 400.
        response = self.register("long@school.edu.cn", organization="学" * 121)
        self.assertIn(response.status_code, (400, 422))
        response = self.register("long@school.edu.cn", application_note="说" * 301)
        self.assertIn(response.status_code, (400, 422))

    def test_duplicate_pending_request_returns_stable_response(self) -> None:
        first = self.register("dup@school.edu.cn")
        second = self.register("dup@school.edu.cn", nickname="第二次申请")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json(), second.json())
        with self.auth_db() as connection:
            rows = connection.execute(
                "SELECT * FROM registration_requests WHERE email = ?", ("dup@school.edu.cn",)
            ).fetchall()
        self.assertEqual(len(rows), 1)
        actions = [
            item["outcome"] for item in AuthService(app_main.config.auth_db_path).list_audit_logs()
            if item["action"] == "register_request"
        ]
        self.assertIn("duplicate_request", actions)

    def test_duplicate_of_existing_account_returns_stable_response(self) -> None:
        self.bootstrap_admin()
        fresh = self.register("brand.new@school.edu.cn")
        duplicate = self.register("admin@school.edu.cn")
        self.assertEqual(fresh.status_code, 200)
        self.assertEqual(duplicate.status_code, 200)
        self.assertEqual(fresh.json(), duplicate.json())
        with self.auth_db() as connection:
            rows = connection.execute(
                "SELECT * FROM registration_requests WHERE email = ?", ("admin@school.edu.cn",)
            ).fetchall()
        self.assertEqual(rows, [])
        actions = [
            item["outcome"] for item in AuthService(app_main.config.auth_db_path).list_audit_logs()
            if item["action"] == "register_request"
        ]
        self.assertIn("duplicate_email", actions)

    def test_password_and_hash_never_leak(self) -> None:
        response = self.register("leak@school.edu.cn")
        self.assertNotIn(STRONG_PASSWORD, response.text)
        reviewed = self.approve("leak@school.edu.cn")
        self.assertNotIn(STRONG_PASSWORD, reviewed)
        service = AuthService(app_main.config.auth_db_path)
        for item in service.list_audit_logs():
            self.assertNotIn(STRONG_PASSWORD, json.dumps(item, ensure_ascii=False))
            self.assertNotIn("$argon2id$", json.dumps(item, ensure_ascii=False))
        for item in service.list_registration_requests():
            self.assertNotIn("password_hash", item)
        with self.auth_db() as connection:
            stored = connection.execute(
                "SELECT password_hash FROM registration_requests WHERE email = ?",
                ("leak@school.edu.cn",),
            ).fetchone()
        self.assertEqual(stored["password_hash"], "")

    def approve(self, email: str) -> str:
        _, csrf = self.bootstrap_admin()
        listing = self.client.get(
            "/admin/registration-requests",
            headers={"X-WebGIS-CSRF": csrf},
        )
        self.assertEqual(listing.status_code, 200, listing.text)
        items = listing.json()["items"]
        target = next(item for item in items if item["email"] == email)
        response = self.client.post(
            f"/admin/registration-requests/{target['request_id']}/review",
            json={"decision": "approved"},
            headers={"X-WebGIS-CSRF": csrf},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.text

    def test_admin_lists_searches_and_filters_requests(self) -> None:
        _, csrf = self.bootstrap_admin()
        self.register("alpha@school.edu.cn", nickname="阿尔法", organization="第一中学")
        self.register("beta@school.edu.cn", nickname="贝塔", organization="第二中学")
        listing = self.client.get(
            "/admin/registration-requests", headers={"X-WebGIS-CSRF": csrf}
        )
        payload = listing.json()
        self.assertEqual(payload["pending_count"], 2)
        self.assertEqual(len(payload["items"]), 2)

        by_school = self.client.get(
            "/admin/registration-requests",
            params={"query": "第一中学"},
            headers={"X-WebGIS-CSRF": csrf},
        ).json()["items"]
        self.assertEqual([item["email"] for item in by_school], ["alpha@school.edu.cn"])
        by_nickname = self.client.get(
            "/admin/registration-requests",
            params={"query": "贝塔"},
            headers={"X-WebGIS-CSRF": csrf},
        ).json()["items"]
        self.assertEqual([item["email"] for item in by_nickname], ["beta@school.edu.cn"])
        approved_only = self.client.get(
            "/admin/registration-requests",
            params={"status": "approved"},
            headers={"X-WebGIS-CSRF": csrf},
        ).json()["items"]
        self.assertEqual(approved_only, [])

    def test_admin_approves_creates_active_teacher(self) -> None:
        _, admin_csrf = self.bootstrap_admin()
        self.register("approvable@school.edu.cn", organization="第八中学")
        listing = self.client.get(
            "/admin/registration-requests", headers={"X-WebGIS-CSRF": admin_csrf}
        ).json()
        request_id = listing["items"][0]["request_id"]
        self.assertEqual(listing["pending_count"], 1)

        response = self.client.post(
            f"/admin/registration-requests/{request_id}/review",
            json={"decision": "approved"},
            headers={"X-WebGIS-CSRF": admin_csrf},
        )
        self.assertEqual(response.status_code, 200, response.text)
        reviewed = response.json()["request"]
        self.assertEqual(reviewed["status"], "approved")
        self.assertTrue(reviewed["resulting_user_id"])
        self.assertEqual(reviewed["organization"], "第八中学")

        users = self.client.get("/admin/users", headers={"X-WebGIS-CSRF": admin_csrf}).json()["items"]
        teacher = next(item for item in users if item["email"] == "approvable@school.edu.cn")
        self.assertEqual(teacher["role"], "teacher")
        self.assertEqual(teacher["status"], "active")
        self.assertFalse(teacher["must_change_password"])
        self.assertEqual(teacher["organization"], "第八中学")

        # The approved teacher now signs in with the password they chose.
        login = self.client.post(
            "/auth/login",
            json={"email": "approvable@school.edu.cn", "password": STRONG_PASSWORD},
        )
        self.assertEqual(login.status_code, 200, login.text)
        self.assertFalse(login.json()["user"]["must_change_password"])

        with self.auth_db() as connection:
            row = connection.execute(
                "SELECT password_hash FROM registration_requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()
        self.assertEqual(row["password_hash"], "")

    def test_admin_rejects_request_clears_hash_and_keeps_audit(self) -> None:
        _, admin_csrf = self.bootstrap_admin()
        self.register("rejectable@school.edu.cn")
        listing = self.client.get(
            "/admin/registration-requests", headers={"X-WebGIS-CSRF": admin_csrf}
        ).json()
        request_id = listing["items"][0]["request_id"]
        with self.auth_db() as connection:
            stored_hash = connection.execute(
                "SELECT password_hash FROM registration_requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()[0]
        self.assertTrue(stored_hash.startswith("$argon2id$"))

        response = self.client.post(
            f"/admin/registration-requests/{request_id}/review",
            json={"decision": "rejected"},
            headers={"X-WebGIS-CSRF": admin_csrf},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["request"]["status"], "rejected")

        users = self.client.get("/admin/users", headers={"X-WebGIS-CSRF": admin_csrf}).json()["items"]
        self.assertFalse(any(item["email"] == "rejectable@school.edu.cn" for item in users))
        with self.auth_db() as connection:
            row = connection.execute(
                "SELECT password_hash FROM registration_requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            audits = connection.execute(
                "SELECT COUNT(*) FROM audit_logs WHERE action = 'registration_review'"
            ).fetchone()[0]
        self.assertEqual(row["password_hash"], "")
        self.assertEqual(audits, 1)

    def test_double_review_returns_conflict(self) -> None:
        _, admin_csrf = self.bootstrap_admin()
        self.register("once.only@school.edu.cn")
        listing = self.client.get(
            "/admin/registration-requests", headers={"X-WebGIS-CSRF": admin_csrf}
        ).json()
        request_id = listing["items"][0]["request_id"]
        first = self.client.post(
            f"/admin/registration-requests/{request_id}/review",
            json={"decision": "approved"},
            headers={"X-WebGIS-CSRF": admin_csrf},
        )
        second = self.client.post(
            f"/admin/registration-requests/{request_id}/review",
            json={"decision": "rejected"},
            headers={"X-WebGIS-CSRF": admin_csrf},
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.json()["detail"]["code"], "ALREADY_REVIEWED")

    def test_approval_with_email_conflict_rolls_back(self) -> None:
        _, admin_csrf = self.bootstrap_admin()
        # An account with the same email appears after the request was filed.
        self.register("conflict@school.edu.cn")
        self.create_teacher(admin_csrf, "conflict@school.edu.cn")
        listing = self.client.get(
            "/admin/registration-requests", headers={"X-WebGIS-CSRF": admin_csrf}
        ).json()
        request_id = listing["items"][0]["request_id"]

        response = self.client.post(
            f"/admin/registration-requests/{request_id}/review",
            json={"decision": "approved"},
            headers={"X-WebGIS-CSRF": admin_csrf},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "EMAIL_EXISTS")

        with self.auth_db() as connection:
            row = connection.execute(
                "SELECT * FROM registration_requests WHERE request_id = ?", (request_id,)
            ).fetchone()
            user_rows = connection.execute(
                "SELECT user_id FROM users WHERE username = 'conflict@school.edu.cn'"
            ).fetchall()
        # Rolled back: request still pending with its hash, exactly one account.
        self.assertEqual(row["status"], "pending")
        self.assertTrue(str(row["password_hash"]).startswith("$argon2id$"))
        self.assertEqual(len(user_rows), 1)

    def test_teacher_cannot_list_or_review_requests(self) -> None:
        _, admin_csrf = self.bootstrap_admin()
        created = self.create_teacher(admin_csrf, "plain.teacher@school.edu.cn")
        teacher_client = TestClient(app_main.app)
        try:
            login = teacher_client.post(
                "/auth/login",
                json={"email": "plain.teacher@school.edu.cn", "password": created["temporary_password"]},
            )
            self.assertEqual(login.status_code, 200)
            teacher_csrf = login.json()["csrf_token"]
            self.assertEqual(
                teacher_client.get(
                    "/admin/registration-requests", headers={"X-WebGIS-CSRF": teacher_csrf}
                ).status_code,
                403,
            )
            self.assertEqual(
                teacher_client.post(
                    "/admin/registration-requests/regreq_missing/review",
                    json={"decision": "approved"},
                    headers={"X-WebGIS-CSRF": teacher_csrf},
                ).status_code,
                403,
            )
        finally:
            teacher_client.close()

    def test_unauthenticated_cannot_review(self) -> None:
        self.bootstrap_admin()
        self.client.cookies.clear()
        self.assertEqual(
            self.client.get("/admin/registration-requests").status_code,
            401,
        )

    def test_approved_teacher_project_isolation(self) -> None:
        _, admin_csrf = self.bootstrap_admin()
        self.register("isolated@school.edu.cn")
        listing = self.client.get(
            "/admin/registration-requests", headers={"X-WebGIS-CSRF": admin_csrf}
        ).json()
        self.client.post(
            f"/admin/registration-requests/{listing['items'][0]['request_id']}/review",
            json={"decision": "approved"},
            headers={"X-WebGIS-CSRF": admin_csrf},
        )
        other = self.create_teacher(admin_csrf, "colleague@school.edu.cn")

        teacher_client = TestClient(app_main.app)
        try:
            login = teacher_client.post(
                "/auth/login",
                json={"email": "isolated@school.edu.cn", "password": STRONG_PASSWORD},
            )
            self.assertEqual(login.status_code, 200, login.text)
            teacher_csrf = login.json()["csrf_token"]
            own = teacher_client.post(
                "/projects",
                json={"name": "新教师的课堂"},
                headers={"X-WebGIS-CSRF": teacher_csrf},
            )
            self.assertEqual(own.status_code, 200, own.text)
            own_project_id = own.json()["project_id"]
            admin_project = self.client.post(
                "/projects",
                json={"name": "管理员的项目"},
                headers={"X-WebGIS-CSRF": admin_csrf},
            ).json()["project_id"]

            self.assertEqual(
                teacher_client.get(f"/projects/{own_project_id}").status_code, 200
            )
            self.assertEqual(
                teacher_client.get(f"/projects/{admin_project}").status_code, 404
            )
            self.assertEqual(
                teacher_client.get("/admin/users").status_code, 403
            )

            # A colleague teacher cannot see the new teacher's project either.
            colleague_client = TestClient(app_main.app)
            try:
                colleague_login = colleague_client.post(
                    "/auth/login",
                    json={
                        "email": "colleague@school.edu.cn",
                        "password": other["temporary_password"],
                    },
                )
                colleague_csrf = colleague_login.json()["csrf_token"]
                # Clear the forced temporary-password gate first; the 403 it
                # produces is not an isolation signal.
                colleague_client.post(
                    "/auth/change-password",
                    json={
                        "current_password": other["temporary_password"],
                        "new_password": "Colleague-New-2026!",
                    },
                    headers={"X-WebGIS-CSRF": colleague_csrf},
                )
                colleague_csrf = colleague_client.get("/auth/me").json()["csrf_token"]
                self.assertEqual(
                    colleague_client.get(f"/projects/{own_project_id}").status_code,
                    404,
                )
            finally:
                colleague_client.close()
        finally:
            teacher_client.close()


class RegistrationRateLimitByIpTest(RegistrationApiTestBase):
    registration_mode = "approval"
    auth_service_kwargs = {"registration_ip_limit": 3, "registration_email_limit": 50}

    def test_fourth_submission_from_same_ip_is_rejected(self) -> None:
        for index in range(3):
            response = self.register(f"rate{index}@school.edu.cn")
            self.assertEqual(response.status_code, 200, response.text)
        blocked = self.register("rate3@school.edu.cn")
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked.json()["detail"]["code"], "RATE_LIMITED")


class RegistrationRateLimitByEmailTest(RegistrationApiTestBase):
    registration_mode = "approval"
    auth_service_kwargs = {"registration_ip_limit": 50, "registration_email_limit": 2}

    def test_third_submission_for_same_email_is_rejected(self) -> None:
        self.assertEqual(self.register("same@school.edu.cn").status_code, 200)
        self.assertEqual(self.register("same@school.edu.cn").status_code, 200)
        blocked = self.register("same@school.edu.cn")
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked.json()["detail"]["code"], "RATE_LIMITED")


class RegistrationOpenModeTest(RegistrationApiTestBase):
    registration_mode = "open"

    def test_open_registration_creates_active_teacher_without_session(self) -> None:
        response = self.register("instant@school.edu.cn", organization="即时中学")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["status"], "created")
        self.assertEqual(body["message"], "注册完成，请使用新账号登录。")
        self.assertNotIn("set-cookie", {key.lower() for key in response.headers.keys()})
        self.assertEqual(self.client.get("/auth/me").status_code, 401)

        users = AuthService(app_main.config.auth_db_path).list_users()
        teacher = next(item for item in users if item["email"] == "instant@school.edu.cn")
        self.assertEqual(teacher["role"], "teacher")
        self.assertEqual(teacher["status"], "active")
        self.assertFalse(teacher["must_change_password"])

        login = self.client.post(
            "/auth/login",
            json={"email": "instant@school.edu.cn", "password": STRONG_PASSWORD},
        )
        self.assertEqual(login.status_code, 200, login.text)

    def test_open_duplicate_returns_stable_response(self) -> None:
        first = self.register("twice@school.edu.cn")
        duplicate = self.register("twice@school.edu.cn")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(duplicate.status_code, 200)
        self.assertEqual(first.json(), duplicate.json())
        users = AuthService(app_main.config.auth_db_path).list_users()
        self.assertEqual(
            [item["email"] for item in users if item["email"] == "twice@school.edu.cn"],
            ["twice@school.edu.cn"],
        )

    def test_open_registration_converts_pending_request(self) -> None:
        # A deployment flipped from approval to open while a request waited.
        _, admin_csrf = self.bootstrap_admin()
        pending_listing = self.client.get(
            "/auth/bootstrap-status"
        )  # keep config untouched; register directly below
        del pending_listing
        service = app_main.auth_service
        outcome = service.submit_registration("waited@school.edu.cn", "等待者", STRONG_PASSWORD)
        self.assertEqual(outcome, "submitted")
        created = service.register_open("waited@school.edu.cn", "等待者", STRONG_PASSWORD)
        self.assertEqual(created, "created")
        requests = service.list_registration_requests()
        self.assertEqual(requests[0]["status"], "approved")
        self.assertEqual(requests[0]["password_hash"] if "password_hash" in requests[0] else "", "")


class RegistrationClosedModeTest(RegistrationApiTestBase):
    registration_mode = "closed"

    def test_closed_mode_rejects_registration(self) -> None:
        response = self.register("closed@school.edu.cn")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"]["code"], "REGISTRATION_CLOSED")
        with self.auth_db() as connection:
            count = connection.execute("SELECT COUNT(*) FROM registration_requests").fetchone()[0]
        self.assertEqual(count, 0)

    def test_closed_mode_reports_closed_registration(self) -> None:
        status = self.client.get("/auth/bootstrap-status").json()
        self.assertEqual(status["registration_mode"], "closed")


class RegistrationClientIpTest(RegistrationApiTestBase):
    def test_forgeable_header_ignored_by_default(self) -> None:
        response = self.client.post(
            "/auth/register",
            headers={"CF-Connecting-IP": "203.0.113.9"},
            json={
                "email": "ipcheck@school.edu.cn",
                "nickname": "来源测试",
                "password": STRONG_PASSWORD,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        with self.auth_db() as connection:
            row = connection.execute(
                "SELECT source_ip FROM registration_requests WHERE email = ?",
                ("ipcheck@school.edu.cn",),
            ).fetchone()
        self.assertNotEqual(row["source_ip"], "203.0.113.9")


class RegistrationTrustedProxyTest(RegistrationApiTestBase):
    trust_proxy_headers = True

    def test_cf_connecting_ip_recorded_when_trusted(self) -> None:
        response = self.client.post(
            "/auth/register",
            headers={"CF-Connecting-IP": "203.0.113.9"},
            json={
                "email": "proxied@school.edu.cn",
                "nickname": "代理测试",
                "password": STRONG_PASSWORD,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        with self.auth_db() as connection:
            row = connection.execute(
                "SELECT source_ip FROM registration_requests WHERE email = ?",
                ("proxied@school.edu.cn",),
            ).fetchone()
        self.assertEqual(row["source_ip"], "203.0.113.9")


class LegacyDatabaseUpgradeTest(unittest.TestCase):
    """An auth database from before registration must keep working."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "auth.db"
        self._build_legacy_database()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _build_legacy_database(self) -> None:
        from argon2.low_level import Type
        from argon2 import PasswordHasher

        hasher = PasswordHasher(time_cost=2, memory_cost=19_456, parallelism=1, hash_len=32, salt_len=16, type=Type.ID)
        connection = sqlite3.connect(self.db_path)
        try:
            connection.executescript(
                """
                CREATE TABLE users (
                    user_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    display_name TEXT NOT NULL,
                    email TEXT NOT NULL DEFAULT '',
                    role TEXT NOT NULL CHECK (role IN ('admin', 'teacher')),
                    status TEXT NOT NULL CHECK (status IN ('active', 'disabled')),
                    password_hash TEXT NOT NULL,
                    must_change_password INTEGER NOT NULL DEFAULT 0,
                    failed_attempts INTEGER NOT NULL DEFAULT 0,
                    locked_until TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_login_at TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    token_hash TEXT NOT NULL UNIQUE,
                    csrf_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    idle_expires_at TEXT NOT NULL,
                    absolute_expires_at TEXT NOT NULL,
                    revoked_at TEXT NOT NULL DEFAULT '',
                    ip_address TEXT NOT NULL DEFAULT '',
                    user_agent TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE audit_logs (
                    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    actor_user_id TEXT NOT NULL DEFAULT '',
                    action TEXT NOT NULL,
                    target_user_id TEXT NOT NULL DEFAULT '',
                    outcome TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    ip_address TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE auth_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE user_files (
                    path TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL
                );
                """
            )
            now = iso(datetime.now(timezone.utc))
            token = "legacy-session-token-0123456789"
            connection.execute(
                """
                INSERT INTO users (
                    user_id, username, display_name, email, role, status,
                    password_hash, must_change_password, created_at, updated_at
                ) VALUES ('user_legacy', 'old.admin@school.edu.cn', '旧管理员', 'old.admin@school.edu.cn', 'admin', 'active', ?, 0, ?, ?)
                """,
                (hasher.hash("Legacy-Admin-2026!"), now, now),
            )
            future = iso(datetime.now(timezone.utc) + timedelta(hours=2))
            connection.execute(
                """
                INSERT INTO sessions (
                    session_id, user_id, token_hash, csrf_hash, created_at,
                    last_seen_at, idle_expires_at, absolute_expires_at
                ) VALUES ('session_legacy', 'user_legacy', ?, ?, ?, ?, ?, ?)
                """,
                (
                    hashlib.sha256(token.encode("utf-8")).hexdigest(),
                    "csrf-legacy-hash",
                    now,
                    now,
                    future,
                    future,
                ),
            )
            connection.commit()
            self.legacy_token = token
        finally:
            connection.close()

    def test_users_and_sessions_survive_upgrade_and_registration_works(self) -> None:
        service = AuthService(self.db_path)
        self.assertTrue(service.has_users())
        context = service.authenticate(self.legacy_token)
        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(context.user["email"], "old.admin@school.edu.cn")
        self.assertEqual(context.user["organization"], "")

        # Registration tables exist and accept a request.
        outcome = service.submit_registration(
            "upgraded@school.edu.cn",
            "升级后申请",
            STRONG_PASSWORD,
            ip_address="127.0.0.1",
        )
        self.assertEqual(outcome, "submitted")
        self.assertEqual(service.count_pending_registration_requests(), 1)

        # The legacy account is still the last active admin and keeps its protection.
        from backend.app.services.auth import AuthError

        with self.assertRaises(AuthError) as caught:
            service.update_user(
                "user_legacy",
                {"status": "disabled"},
                actor_user_id="user_legacy",
            )
        self.assertEqual(caught.exception.code, "LAST_ADMIN_REQUIRED")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
