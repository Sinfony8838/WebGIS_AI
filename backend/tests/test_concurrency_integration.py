"""Admission at HTTP boundaries, independent health reads and cancellation."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.config import AppConfig
from backend.app.runtime import WebGISRuntime
from backend.app.services.auth import AuthError, AuthService
from backend.app.services.background_tasks import BackgroundBusy, BoundedTaskPool
from backend.app.services.blocking_work import BlockingWorkPool
from backend.app.services import document_processing
from backend.app.services.request_limits import AdmissionGate, VoiceSessionGate


def test_blocked_timeline_keeps_health_live_and_full_pool_rejects(monkeypatch, tmp_path):
    entered, release = Event(), Event()
    calls = []
    def generate(**kwargs):
        calls.append(kwargs)
        entered.set()
        assert release.wait(5)
        return {"status": "success"}
    config = AppConfig(root_dir=tmp_path, auth_mode="disabled")
    monkeypatch.setattr(main, "config", config)
    monkeypatch.setattr(main, "_require_project_access", lambda *args: None)
    monkeypatch.setattr(main, "runtime", SimpleNamespace(generate_timeline=generate, health=lambda: {"status": "ok"}))
    pool = BlockingWorkPool(workers=1, max_waiting=0)
    monkeypatch.setattr(main.app.state, "request_work", pool)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
            first = asyncio.create_task(client.post("/projects/p/timeline/generate", files={"file": ("lesson.txt", b"fixture")}))
            try:
                assert await asyncio.to_thread(entered.wait, 3)
                health = await asyncio.wait_for(client.get("/health"), 1)
                assert health.status_code == 200
                full = await asyncio.wait_for(client.post("/projects/p/timeline/generate", files={"file": ("lesson.txt", b"fixture")}), 1)
                assert full.status_code == 503 and full.headers["retry-after"] == "2"
                assert len(calls) == 1
            finally:
                release.set()
                assert (await first).status_code == 200
                await pool.aclose()
    asyncio.run(scenario())


@pytest.mark.parametrize("method,args", [
    ("submit_template", ("p", "fixture")),
    ("submit_assistant_message", ("p", "fixture")),
    ("confirm_assistant_action", ("confirmation",)),
    ("submit_image_generation", ("p", "fixture")),
])
def test_runtime_rejects_before_creating_jobs_or_conversations(method, args):
    runtime = WebGISRuntime.__new__(WebGISRuntime)
    runtime.background_tasks = BoundedTaskPool(max_workers=1, max_queued=0)
    runtime.store = Mock()
    with runtime.background_tasks.reserve():
        with pytest.raises(BackgroundBusy):
            getattr(runtime, method)(*args)
    assert runtime.store.mock_calls == []
    runtime.background_tasks.shutdown()


def test_population_route_rejects_before_creating_job(monkeypatch):
    pool = BoundedTaskPool(max_workers=1, max_queued=0)
    store = Mock()
    monkeypatch.setattr(main, "runtime", SimpleNamespace(background_tasks=pool, store=store))
    monkeypatch.setattr(main, "_require_project_access", lambda *args: None)
    with pool.reserve(), pytest.raises(BackgroundBusy):
        main.population_zonal_summary("p", main.PopulationZoneRequest(geometry={}), None)
    assert store.mock_calls == []
    pool.shutdown()


def test_bank_full_rejects_before_reading_uploaded_payload(monkeypatch):
    pool = BoundedTaskPool(max_workers=1, max_queued=0)
    classroom = SimpleNamespace(reserve_question_bank_import=pool.reserve)
    monkeypatch.setattr(main, "runtime", SimpleNamespace(classroom=classroom))
    monkeypatch.setattr(main, "_require_project_access", lambda *args: None)
    upload = Mock(filename="fixture.docx")
    with pool.reserve(), pytest.raises(BackgroundBusy):
        asyncio.run(main.import_question_banks(None, "p", [upload]))
    assert upload.mock_calls == []
    pool.shutdown()


@pytest.mark.parametrize("trusted,expected", [(False, "testclient"), (True, "192.0.2.7")])
def test_login_retry_header_and_proxy_trust(monkeypatch, tmp_path, trusted, expected):
    service = Mock()
    service.login.side_effect = AuthError("RATE_LIMITED", "busy", 429, retry_after=9)
    monkeypatch.setattr(main, "config", AppConfig(root_dir=tmp_path, auth_mode="users", trust_proxy_headers=trusted))
    monkeypatch.setattr(main, "auth_service", service)
    client = TestClient(main.app)
    try:
        response = client.post("/auth/login", json={"email": "teacher@example.invalid", "password": "fixture"}, headers={"CF-Connecting-IP": "192.0.2.7"})
    finally:
        client.close()
    assert response.status_code == 429 and response.headers["retry-after"] == "9"
    assert service.login.call_args.kwargs["ip_address"] == expected


def test_auth_pool_reopens_for_next_lifespan(tmp_path):
    service = AuthService(tmp_path / "auth.sqlite")
    service.close()
    service.startup()
    assert asyncio.run(service.authenticate_async("missing")) is None
    service.close()


def test_model_wait_queue_is_bounded():
    gate = AdmissionGate(1, timeout=0.5, max_waiting=1)
    assert gate.acquire()
    with ThreadPoolExecutor(max_workers=1) as executor:
        waiting = executor.submit(gate.acquire)
        import time
        deadline = time.monotonic() + 2
        while gate.waiting != 1 and time.monotonic() < deadline:
            time.sleep(0.005)
        assert gate.waiting == 1
        assert not gate.acquire()
        gate.release()
        assert waiting.result(timeout=2)
        gate.release()


def test_voice_sessions_are_bounded_across_accounts():
    gate = VoiceSessionGate(max_per_user=2, max_total=3)
    assert gate.enter("a") and gate.enter("a") and gate.enter("b")
    assert not gate.enter("c")
    gate.leave("a")
    assert gate.enter("c")


def test_cancelled_request_signals_parser_before_releasing_capacity(monkeypatch):
    entered, cancelled = Event(), Event()
    def parse(operation, raw, *, cancel_event):
        entered.set()
        assert cancel_event.wait(3)
        cancelled.set()
        raise RuntimeError("cancelled fixture parser")
    monkeypatch.setattr(document_processing, "_executor", SimpleNamespace(run=parse))
    pool = BlockingWorkPool(workers=1, max_waiting=0)
    async def scenario():
        task = asyncio.create_task(pool.run(document_processing.run_document, "lesson_docx", b"fixture"))
        assert await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await pool.aclose()
        assert cancelled.is_set()
    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["handshake", "capacity"])
def test_voice_failure_releases_global_admission(monkeypatch, failure):
    from unittest.mock import AsyncMock
    from fastapi import WebSocketDisconnect
    from backend.app.services.password_work import WorkBusy
    gate = VoiceSessionGate(1, max_total=1)
    monkeypatch.setattr(main, "_VOICE_GATE", gate)
    monkeypatch.setattr(main, "_voice_origin_allowed", lambda ws: True)
    monkeypatch.setattr(main, "_websocket_user", AsyncMock(return_value=({"user_id": "fixture"}, 0)))
    monkeypatch.setattr(main, "runtime", SimpleNamespace(voice_asr=SimpleNamespace(status=lambda: {"available": True}, create_session=lambda: None)))
    reject = AsyncMock()
    monkeypatch.setattr(main, "_reject_voice_stream", reject)
    if failure == "capacity":
        monkeypatch.setattr(main, "_run_voice_work", AsyncMock(side_effect=WorkBusy()))
    websocket = SimpleNamespace(accept=AsyncMock(side_effect=WebSocketDisconnect() if failure == "handshake" else None))
    asyncio.run(main.assistant_voice_stream(websocket))
    assert gate.enter("next-account")
    if failure == "capacity":
        assert reject.call_args.args[1] == "server_busy"


def test_lifespan_cancellation_finishes_cleanup_and_restores_pools(monkeypatch):
    from unittest.mock import AsyncMock
    def pool():
        return BoundedTaskPool()
    workflow_pool = pool()
    runtime = SimpleNamespace(background_tasks=pool(),
        workflow_executor=SimpleNamespace(tasks=workflow_pool, startup=workflow_pool.startup, shutdown=workflow_pool.shutdown),
        classroom=SimpleNamespace(startup=lambda: None, background_tasks=pool(), question_bank_tasks=pool(),
                                  population_lesson_prep=SimpleNamespace(tasks=pool())))
    identity = SimpleNamespace(startup=lambda: None, aclose=AsyncMock())
    monkeypatch.setattr(main, "runtime", runtime)
    monkeypatch.setattr(main, "auth_service", identity)
    monkeypatch.setattr(main.app.state, "presentation_library", None, raising=False)
    previous_request = main.app.state.request_work
    previous_document = document_processing._executor
    entered, release = Event(), Event()
    async def scenario():
        lifetime = main._lifespan(main.app)
        await lifetime.__aenter__()
        active = main.app.state.request_work
        def work():
            entered.set()
            assert release.wait(5)
        work_task = asyncio.create_task(active.run(work))
        assert await asyncio.to_thread(entered.wait, 2)
        closing = asyncio.create_task(lifetime.__aexit__(None, None, None))
        try:
            for _ in range(100):
                if active.closed:
                    break
                await asyncio.sleep(0.005)
            assert active.closed
            closing.cancel()
            await asyncio.sleep(0)
            closing.cancel()
            assert not closing.done()
        finally:
            release.set()
            await work_task
            with pytest.raises(asyncio.CancelledError):
                await closing
        assert main.app.state.request_work is previous_request
        assert document_processing._executor is previous_document
        identity.aclose.assert_awaited_once()
    asyncio.run(scenario())
