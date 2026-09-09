from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from backend.app.services.auth import AuthError, AuthService, iso, utc_now


class AuthServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.service = AuthService(
            Path(self.temp_dir.name) / "auth.db",
            idle_minutes=480,
            max_hours=24,
        )
        self.bootstrap = self.service.bootstrap(
            "admin@school.edu.cn",
            "系统管理员",
            "Strong-Admin-2026!",
            ip_address="127.0.0.1",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_bootstrap_is_single_use_and_creates_argon2id_hash(self) -> None:
        with self.assertRaises(AuthError) as caught:
            self.service.bootstrap("second@school.edu.cn", "第二管理员", "Strong-Second-2026!")
        self.assertEqual(caught.exception.code, "BOOTSTRAP_COMPLETE")
        connection = sqlite3.connect(self.service.db_path)
        try:
            stored = connection.execute(
                "SELECT password_hash FROM users WHERE username = 'admin@school.edu.cn'"
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertTrue(stored.startswith("$argon2id$"))
        self.assertNotIn("Strong-Admin-2026!", stored)

    def test_login_uses_opaque_revocable_session_and_csrf(self) -> None:
        login = self.service.login("admin@school.edu.cn", "Strong-Admin-2026!")
        self.assertNotEqual(login["session_token"], login["csrf_token"])
        context = self.service.authenticate(login["session_token"])
        self.assertIsNotNone(context)
        assert context is not None
        self.assertTrue(self.service.verify_csrf(context, login["csrf_token"]))
        self.assertFalse(self.service.verify_csrf(context, "wrong"))
        self.service.logout(context.session_id, actor_user_id=context.user["user_id"])
        self.assertIsNone(self.service.authenticate(login["session_token"]))

    def test_page_csrf_is_stable_session_bound_and_rotatable(self) -> None:
        login = self.bootstrap
        context = self.service.authenticate(login["session_token"])
        page_token = self.service.csrf_for_session(context)
        self.assertNotIn(page_token, {context.csrf_hash, login["session_token"], login["csrf_token"]})
        restarted = AuthService(self.service.db_path)
        current = restarted.authenticate(login["session_token"])
        self.assertEqual(restarted.csrf_for_session(current), page_token)
        self.assertTrue(restarted.verify_csrf(current, page_token))
        self.assertTrue(restarted.verify_csrf(current, login["csrf_token"]))
        other_login = self.service.login("admin@school.edu.cn", "Strong-Admin-2026!")
        other = self.service.authenticate(other_login["session_token"])
        self.assertFalse(self.service.verify_csrf(other, page_token))
        self.assertFalse(self.service.verify_csrf(other, login["csrf_token"]))
        for invalid in ("", "wrong", "错误令牌", context.csrf_hash, login["session_token"]):
            self.assertFalse(self.service.verify_csrf(context, invalid))
        self.service.rotate_csrf(context.session_id)
        rotated = self.service.authenticate(login["session_token"])
        self.assertFalse(self.service.verify_csrf(rotated, page_token))
        self.assertFalse(self.service.verify_csrf(rotated, login["csrf_token"]))
        self.service.logout(context.session_id)
        self.assertIsNone(self.service.authenticate(login["session_token"]))

    def test_five_failures_lock_account_without_revealing_unknown_user(self) -> None:
        messages = []
        for _ in range(5):
            with self.assertRaises(AuthError) as caught:
                self.service.login("admin@school.edu.cn", "wrong-password")
            messages.append(caught.exception.message)
        with self.assertRaises(AuthError) as locked:
            self.service.login("admin@school.edu.cn", "Strong-Admin-2026!")
        self.assertEqual(locked.exception.code, "ACCOUNT_LOCKED")
        with self.assertRaises(AuthError) as unknown:
            self.service.login("unknown@school.edu.cn", "wrong-password")
        self.assertEqual(messages[0], unknown.exception.message)

    def test_disabled_user_and_role_change_revoke_sessions(self) -> None:
        created = self.service.create_user(
            actor_user_id=self.bootstrap["user"]["user_id"],
            email="teacher.one@school.edu.cn",
            nickname="教师一",
            role="teacher",
        )
        login = self.service.login("teacher.one@school.edu.cn", created["temporary_password"])
        self.assertIsNotNone(self.service.authenticate(login["session_token"]))
        self.service.update_user(
            created["user"]["user_id"],
            {"status": "disabled"},
            actor_user_id=self.bootstrap["user"]["user_id"],
        )
        self.assertIsNone(self.service.authenticate(login["session_token"]))

    def test_temporary_password_requires_change_and_other_sessions_are_revoked(self) -> None:
        created = self.service.create_user(
            actor_user_id=self.bootstrap["user"]["user_id"],
            email="teacher.two@school.edu.cn",
            nickname="教师二",
            role="teacher",
        )
        login = self.service.login("teacher.two@school.edu.cn", created["temporary_password"])
        self.assertTrue(login["user"]["must_change_password"])
        changed = self.service.change_password(
            created["user"]["user_id"],
            created["temporary_password"],
            "teacher2026",
            current_session_id=login["session_id"],
        )
        self.assertFalse(changed["must_change_password"])
        self.assertIsNotNone(self.service.authenticate(login["session_token"]))

    def test_expired_session_is_rejected(self) -> None:
        token = self.bootstrap["session_token"]
        connection = sqlite3.connect(self.service.db_path)
        try:
            connection.execute(
                "UPDATE sessions SET idle_expires_at = ? WHERE session_id = ?",
                (iso(utc_now() - timedelta(minutes=1)), self.bootstrap["session_id"]),
            )
            connection.commit()
        finally:
            connection.close()
        self.assertIsNone(self.service.authenticate(token))

    def test_last_active_admin_cannot_be_disabled_or_demoted(self) -> None:
        admin_id = self.bootstrap["user"]["user_id"]
        for patch in ({"status": "disabled"}, {"role": "teacher"}):
            with self.assertRaises(AuthError) as caught:
                self.service.update_user(
                    admin_id,
                    patch,
                    actor_user_id=admin_id,
                )
            self.assertEqual(caught.exception.code, "LAST_ADMIN_REQUIRED")

    def test_reset_password_is_one_time_response_and_is_audited(self) -> None:
        created = self.service.create_user(
            actor_user_id=self.bootstrap["user"]["user_id"],
            email="teacher.three@school.edu.cn",
            nickname="教师三",
            role="teacher",
        )
        reset = self.service.reset_password(
            created["user"]["user_id"],
            actor_user_id=self.bootstrap["user"]["user_id"],
        )
        self.assertIn("temporary_password", reset)
        users = self.service.list_users(query="teacher.three@school.edu.cn")
        self.assertNotIn("temporary_password", users[0])
        actions = {item["action"] for item in self.service.list_audit_logs()}
        self.assertIn("reset_password", actions)
        self.assertIn("create_user", actions)

    def test_password_policy_requires_eight_characters_and_two_character_types(self) -> None:
        for weak in ("abcdef1", "abcdefgh", "12345678", "!!!!!!!!"):
            with self.subTest(password=weak), self.assertRaises(AuthError) as caught:
                self.service.change_password(
                    self.bootstrap["user"]["user_id"],
                    "Strong-Admin-2026!",
                    weak,
                    current_session_id=self.bootstrap["session_id"],
                )
            self.assertEqual(caught.exception.code, "WEAK_PASSWORD")

        changed = self.service.change_password(
            self.bootstrap["user"]["user_id"],
            "Strong-Admin-2026!",
            "abcd1234",
            current_session_id=self.bootstrap["session_id"],
        )
        self.assertFalse(changed["must_change_password"])


if __name__ == "__main__":
    unittest.main()
