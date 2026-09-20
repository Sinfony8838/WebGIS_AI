"""Phase-1 audit task T3: public health minimization and voice WS hardening.

* /health is a minimal liveness payload (no paths, no provider endpoints).
* /ui/capabilities carries the sanitized feature set the frontend needs.
* /diagnostics is admin-only and holds build/runtime details.
* The voice WebSocket enforces an Origin whitelist, forced-password-change
  consistency, per-user session caps, frame-size and session-duration caps,
  with explicit close codes; it never echoes raw exception text.
"""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import main as app_main
from backend.app.config import AppConfig
from backend.app.runtime import WebGISRuntime
from backend.app.services.auth import AuthService


class _FakeVoiceSession:
    def feed(self, pcm: bytes):
        return []

    def flush(self):
        return None

    def close(self) -> None:
        pass


class _FakeVoiceEngine:
    """Always-available recognizer so WS tests skip real model loading."""

    def __init__(self) -> None:
        self.status_payload = {"available": True, "state": "ready", "reason": "", "model": "", "model_dir": ""}

    def status(self) -> dict:
        return dict(self.status_payload)

    def create_session(self) -> _FakeVoiceSession:
        return _FakeVoiceSession()


class HealthVoiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.sandbox = Path(self.temp_dir.name)
        self.previous = (app_main.config, app_main.runtime, app_main.auth_service)
        config = AppConfig(root_dir=self.sandbox, auth_mode="users")
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
        self.admin_csrf = bootstrap.json()["csrf_token"]
        self.teacher_client, self.teacher_csrf = self._create_teacher()

    def tearDown(self) -> None:
        self.client.close()
        self.teacher_client.close()
        app_main.config, app_main.runtime, app_main.auth_service = self.previous
        self.temp_dir.cleanup()

    def _create_teacher(self):
        created = self.client.post(
            "/admin/users",
            json={"email": "teacher@school.edu.cn", "nickname": "教师", "role": "teacher"},
            headers={"X-WebGIS-CSRF": self.admin_csrf},
        )
        self.assertEqual(created.status_code, 200, created.text)
        temp_password = created.json()["temporary_password"]
        client = TestClient(app_main.app)
        login = client.post("/auth/login", json={"email": "teacher@school.edu.cn", "password": temp_password})
        self.assertEqual(login.status_code, 200, login.text)
        return client, login.json()["csrf_token"]

    # ------------------------------------------------------------- health

    def test_health_is_minimal_liveness_payload(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json().keys()), {"status"})
        self.assertEqual(response.json()["status"], "success")

    def test_capabilities_public_and_sanitized(self) -> None:
        engine = _FakeVoiceEngine()
        engine.status_payload = {
            "available": False,
            "state": "load_failed",
            "reason": r"FileNotFoundError: C:\models\paraformer (root cause)",
            "model": "paraformer",
            "model_dir": r"C:\models\paraformer",
        }
        with patch.object(app_main.runtime, "voice_asr", engine):
            response = self.client.get("/ui/capabilities")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        for key in ("ui", "online_services", "basemaps", "voice_asr", "image_generation"):
            self.assertIn(key, payload)
        self.assertIn("assistant_v2_enabled", payload["ui"])
        self.assertIn("amap_poi_enabled", payload["online_services"])
        # No sensitive internals anywhere in the payload.
        text = response.text
        for forbidden in ("model_dir", "base_url", "manifest_path", "qgis_root", "workspace", "api_key_source"):
            self.assertNotIn(forbidden, text)
        # Load-failure exception text is reduced to a fixed label.
        self.assertEqual(payload["voice_asr"]["state"], "load_failed")
        self.assertEqual(payload["voice_asr"]["reason"], "voice_model_load_failed")
        self.assertNotIn("paraformer", payload["voice_asr"].get("reason", ""))

    def test_diagnostics_admin_only(self) -> None:
        anonymous = TestClient(app_main.app)
        self.assertEqual(anonymous.get("/diagnostics").status_code, 401)
        teacher = self.teacher_client.get("/diagnostics")
        self.assertEqual(teacher.status_code, 403)
        admin = self.client.get("/diagnostics")
        self.assertEqual(admin.status_code, 200)
        payload = admin.json()
        self.assertIn("build", payload)
        self.assertIn("app_version", payload["build"])
        self.assertIn("git_sha", payload["build"])
        self.assertIn("qgis_root", payload["gis_workflow"])

    # ------------------------------------------------------ voice websocket

    def test_ws_rejects_cross_origin_browser_handshake(self) -> None:
        with self.assertRaises(Exception) as ctx:
            with self.client.websocket_connect(
                "/assistant/voice/stream", headers={"Origin": "https://evil.example"}
            ):
                pass
        self.assertEqual(getattr(ctx.exception, "code", None), 4403)

    def test_ws_allows_whitelisted_origin_then_reports_model_unavailable(self) -> None:
        origin = app_main.config.cors_origins()[0]
        # Deterministic unavailable engine (this machine may have real models
        # installed, which would make the success path wait for audio).
        engine = _FakeVoiceEngine()
        engine.status_payload = {"available": False, "state": "not_installed", "reason": "models_not_downloaded"}
        previous = app_main.runtime.voice_asr
        app_main.runtime.voice_asr = engine
        try:
            with self.client.websocket_connect("/assistant/voice/stream", headers={"Origin": origin}) as ws:
                event = json_loads(ws.receive_text())
                self.assertEqual(event["type"], "error")
                self.assertEqual(event["reason"], "not_installed")
                self.assertNotIn("\\", event["detail"])
        finally:
            app_main.runtime.voice_asr = previous

    def test_ws_rejects_pending_password_change_users(self) -> None:
        origin = app_main.config.cors_origins()[0]
        cookie = self.teacher_client.cookies.get(app_main.SESSION_COOKIE)
        # The freshly created teacher still has must_change_password set.
        with self.assertRaises(Exception) as ctx:
            with self.teacher_client.websocket_connect(
                "/assistant/voice/stream", headers={"Origin": origin}
            ):
                pass
        self.assertEqual(getattr(ctx.exception, "code", None), 4407)
        self.assertTrue(cookie)

    def test_ws_enforces_frame_size_cap(self) -> None:
        origin = app_main.config.cors_origins()[0]
        previous_engine = app_main.runtime.voice_asr
        app_main.runtime.voice_asr = _FakeVoiceEngine()
        previous_frame = app_main.config.voice_max_frame_bytes
        try:
            app_main.config.voice_max_frame_bytes = 32
            with self.client.websocket_connect("/assistant/voice/stream", headers={"Origin": origin}) as ws:
                ws.send_bytes(b"x" * 64)
                event = json_loads(ws.receive_text())
                self.assertEqual(event["reason"], "frame_too_large")
        finally:
            app_main.runtime.voice_asr = previous_engine
            app_main.config.voice_max_frame_bytes = previous_frame

    def test_ws_enforces_session_duration_cap(self) -> None:
        origin = app_main.config.cors_origins()[0]
        previous_engine = app_main.runtime.voice_asr
        app_main.runtime.voice_asr = _FakeVoiceEngine()
        previous_seconds = app_main.config.voice_max_session_seconds
        try:
            app_main.config.voice_max_session_seconds = 0.0
            with self.client.websocket_connect("/assistant/voice/stream", headers={"Origin": origin}) as ws:
                # Windows time.monotonic() has ~15ms granularity; let some
                # wall time pass so the elapsed check is unambiguous.
                time.sleep(0.1)
                ws.send_bytes(b"x")
                event = json_loads(ws.receive_text())
                self.assertEqual(event["reason"], "session_timeout")
        finally:
            app_main.runtime.voice_asr = previous_engine
            app_main.config.voice_max_session_seconds = previous_seconds

    def test_ws_enforces_concurrent_session_cap(self) -> None:
        origin = app_main.config.cors_origins()[0]
        previous_engine = app_main.runtime.voice_asr
        app_main.runtime.voice_asr = _FakeVoiceEngine()
        connections = []
        try:
            for _ in range(2):
                connection = self.client.websocket_connect("/assistant/voice/stream", headers={"Origin": origin})
                connection.__enter__()
                connections.append(connection)
            self.assertEqual(app_main._VOICE_GATE._counts, {self._admin_user_id(): 2})
            # The rejection path accepts first, sends the reason, then closes
            # with 4429 — the client sees the event and then the disconnect.
            third = self.client.websocket_connect("/assistant/voice/stream", headers={"Origin": origin})
            with third as ws3:
                event = json_loads(ws3.receive_text())
                self.assertEqual(event["reason"], "session_limit")
                with self.assertRaises(Exception) as ctx:
                    ws3.receive_text()
                self.assertEqual(getattr(ctx.exception, "code", None), 4429)
            for connection in connections:
                try:
                    connection.close()
                except Exception:
                    pass
            connections.clear()
        finally:
            for connection in connections:
                try:
                    connection.close()
                except Exception:
                    pass
            app_main.runtime.voice_asr = previous_engine

    def _admin_user_id(self) -> str:
        me = self.client.get("/auth/me")
        return me.json()["user"]["user_id"]


def json_loads(text: str) -> dict:
    import json

    return json.loads(text)


def _expected_close(ws) -> int:
    """Read the close code from the starlette test session, best effort."""
    close = getattr(ws, "closed", None)
    if isinstance(close, tuple) and close:
        return int(close[0])
    return -1


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
