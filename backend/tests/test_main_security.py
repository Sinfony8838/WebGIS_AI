from __future__ import annotations

import asyncio
import unittest
from importlib.util import find_spec
from types import SimpleNamespace

if find_spec("fastapi") is not None:
    from backend.app import main as app_main


def _request(method: str = "GET", path: str = "/health", headers: dict[str, str] | None = None, query: dict[str, str] | None = None):
    return SimpleNamespace(
        method=method,
        url=SimpleNamespace(path=path),
        headers=headers or {},
        query_params=query or {},
    )


async def _ok_response(_request):
    return {"ok": True}


@unittest.skipIf(find_spec("fastapi") is None, "fastapi is not installed in this Python environment")
class MainSecurityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_token = app_main.config.auth_token
        self.previous_exempt_paths = app_main.config.auth_exempt_paths

    def tearDown(self) -> None:
        app_main.config.auth_token = self.previous_token
        app_main.config.auth_exempt_paths = self.previous_exempt_paths

    def test_auth_disabled_keeps_local_runtime_compatible(self) -> None:
        app_main.config.auth_token = ""
        app_main.config.auth_exempt_paths = ""

        response = asyncio.run(app_main.require_access_token(_request(), _ok_response))

        self.assertEqual(response, {"ok": True})

    def test_auth_enabled_requires_bearer_token(self) -> None:
        app_main.config.auth_token = "secret-token"
        app_main.config.auth_exempt_paths = ""

        missing = asyncio.run(app_main.require_access_token(_request(), _ok_response))
        wrong = asyncio.run(
            app_main.require_access_token(_request(headers={"Authorization": "Bearer wrong"}), _ok_response)
        )
        valid = asyncio.run(
            app_main.require_access_token(_request(headers={"Authorization": "Bearer secret-token"}), _ok_response)
        )

        self.assertEqual(missing.status_code, 401)
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(valid, {"ok": True})

    def test_auth_enabled_accepts_query_token_for_eventsource_and_file_links(self) -> None:
        app_main.config.auth_token = "secret-token"
        app_main.config.auth_exempt_paths = ""

        response = asyncio.run(
            app_main.require_access_token(_request(query={"access_token": "secret-token"}), _ok_response)
        )

        self.assertEqual(response, {"ok": True})

    def test_auth_exempt_paths_allow_public_healthcheck_when_configured(self) -> None:
        app_main.config.auth_token = "secret-token"
        app_main.config.auth_exempt_paths = "/health"

        response = asyncio.run(app_main.require_access_token(_request(), _ok_response))

        self.assertEqual(response, {"ok": True})
