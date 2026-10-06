"""S2b: synthetic teacher/admin cases; no real model or production data."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from backend.app.config import AppConfig
from backend.app.runtime import WebGISRuntime
from backend.app.services.agent_harness import HarnessExecutionError
from backend.app.services.classroom_binding import (
    assistant_actor_scope, require_context_lesson, require_project_lesson,
)


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    for name in ("WEBGIS_AI_DATA_DIR", "WEBGIS_AI_AUTH_DB", "WEBGIS_AI_MINIMAX_API_KEY", "MINIMAX_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    config = AppConfig(root_dir=tmp_path, auth_mode="disabled")
    config.minimax_api_key = ""
    config.ensure_dirs()
    assert config.data_dir.resolve().is_relative_to(tmp_path.resolve())
    runtime = WebGISRuntime(config=config)
    a = runtime.create_project("A", owner_user_id="teacher-A")["project_id"]
    b = runtime.create_project("B", owner_user_id="teacher-B")["project_id"]
    service = runtime.classroom.lesson_service
    own = service.create_lesson({"title": "Own lesson"}, owner_user_id="teacher-A")
    foreign = service.create_lesson({"title": "Private foreign lesson"}, owner_user_id="teacher-B")
    builtin = service.create_lesson({"title": "Shared fixture"}, source="builtin", owner_user_id="teacher-B")
    return runtime, a, b, own, foreign, builtin


def context(lesson, **extra):
    return {"teaching_context": {"lesson_id": lesson.lesson_id, **extra}}


@pytest.mark.parametrize("path", ["top", "embedded"])
@pytest.mark.parametrize("spoof", [False, True])
def test_foreign_lesson_rejected_before_job_attachment_and_thread(fixture, path, spoof):
    runtime, a, _, _, foreign, _ = fixture
    ctx = context(foreign, actor_role="admin" if spoof else "", owner_user_id="teacher-A")
    kwargs = {"teaching_context": ctx["teaching_context"]} if path == "top" else {"map_context": ctx}
    before = runtime.config.state_file.read_bytes()
    with patch.object(runtime, "resolve_image_attachments") as images, patch("backend.app.runtime.threading.Thread") as worker:
        with pytest.raises(KeyError, match="Unknown lesson"):
            runtime.submit_assistant_message(a, "课堂", **kwargs)
        images.assert_not_called()
        worker.assert_not_called()
    assert runtime.config.state_file.read_bytes() == before


@pytest.mark.parametrize("kind", ["own", "builtin", "admin"])
def test_legitimate_context_retained(fixture, kind):
    runtime, a, _, own, foreign, builtin = fixture
    lesson = {"own": own, "builtin": builtin, "admin": foreign}[kind]
    role = "admin" if kind == "admin" else "teacher"
    with patch("backend.app.runtime.threading.Thread"):
        result = runtime.submit_assistant_message(a, "课堂", map_context=context(lesson), actor_role=role)
    assert runtime.store.get_job(result["job_id"]).project_id == a


def test_same_teacher_can_reuse_private_lesson_in_another_project(fixture):
    runtime, _, _, own, _, _ = fixture
    other = runtime.create_project("Same teacher", owner_user_id="teacher-A")["project_id"]
    assert require_project_lesson(runtime.store, other, own.lesson_id) is own


def test_historical_session_snapshot_does_not_require_current_lesson(fixture):
    runtime, a, _, _, foreign, _ = fixture
    session = runtime.store.create_class_session(foreign.lesson_id, a, "111111")
    session.status = "ended"
    runtime.store.delete_lesson(foreign.lesson_id)
    require_context_lesson(runtime.store, a, context(foreign, session_id=session.session_id))


def test_internal_engine_rejects_private_context_before_memory(fixture):
    runtime, a, _, _, foreign, _ = fixture
    before = runtime.config.state_file.read_bytes()
    with patch.object(runtime.session_engine.memory, "get_or_create") as memory:
        with pytest.raises(HarnessExecutionError):
            runtime.session_engine.handle("fixture", runtime.store.get_project(a), "课堂", "knowledge", "", [],
                                          context(foreign), "webgis", "text", Mock())
        memory.assert_not_called()
    assert runtime.config.state_file.read_bytes() == before


@pytest.mark.parametrize("frozen", [False, True])
@pytest.mark.parametrize("decision", ["approve", "reject"])
@pytest.mark.parametrize("reference", ["context", "action"])
def test_historical_confirmation_rechecks_lesson_without_resolving(fixture, frozen, decision, reference):
    runtime, a, _, _, foreign, _ = fixture
    plan = {"map_context": context(foreign)} if reference == "context" else {
        "actions": [{"tool_name": "start_class_session", "tool_params": {"lesson_id": foreign.lesson_id}}],
    }
    payload = {"frozen_plan": plan} if frozen else plan
    confirmation = runtime.store.create_confirmation(a, "", "", "interaction", "fixture", "fixture", payload=payload)
    before = runtime.config.state_file.read_bytes()
    with pytest.raises(KeyError):
        runtime.confirm_assistant_action(confirmation.confirmation_id, decision)
    with pytest.raises(HarnessExecutionError):
        if decision == "approve":
            runtime.session_engine.execute_confirmation(confirmation.confirmation_id, Mock())
        else:
            runtime.session_engine.reject_confirmation(confirmation.confirmation_id)
    assert confirmation.status == "pending"
    assert runtime.config.state_file.read_bytes() == before


@pytest.mark.parametrize("kind", ["own", "builtin", "admin"])
def test_authorized_start_class_executes_without_model(fixture, kind):
    runtime, a, _, own, foreign, builtin = fixture
    lesson = {"own": own, "builtin": builtin, "admin": foreign}[kind]
    action = {"tool_name": "start_class_session", "tool_params": {"lesson_id": lesson.lesson_id}}
    with assistant_actor_scope("admin" if kind == "admin" else "teacher"):
        result = runtime.session_engine.tool_executor.execute(a, "webgis", [action], {}, assistant_mode="interaction")
    session = result[0]["result"]["class_session"]
    assert session["project_id"] == a
    assert session["lesson_id"] == lesson.lesson_id


def test_foreign_explicit_start_rejected_even_without_project_state(fixture):
    runtime, a, _, _, foreign, _ = fixture
    action = {"tool_name": "start_class_session", "tool_params": {"lesson_id": foreign.lesson_id}}
    before = runtime.config.state_file.read_bytes()
    with pytest.raises(KeyError):
        runtime.session_engine.tool_executor.execute(a, "webgis", [action], {}, assistant_mode="interaction")
    with pytest.raises(KeyError):
        runtime._execute_assistant_action(a, action, {})
    assert runtime.config.state_file.read_bytes() == before


def test_all_lesson_references_are_checked_before_first_action(fixture):
    runtime, a, _, _, foreign, _ = fixture
    actions = [
        {"tool_name": "set_view", "tool_params": {"zoom": 9}},
        {"tool_name": "start_class_session", "tool_params": {"lesson_id": foreign.lesson_id}},
    ]
    before = runtime.config.state_file.read_bytes()
    with pytest.raises(KeyError):
        runtime.session_engine.tool_executor.execute(a, "webgis", actions, {}, assistant_mode="interaction")
    assert runtime.config.state_file.read_bytes() == before


@pytest.mark.parametrize("admin", [False, True])
def test_title_matching_filters_permission_and_uses_records(fixture, admin):
    runtime, a, _, _, foreign, _ = fixture
    action = {"tool_name": "start_class_session", "tool_params": {"lesson_title": foreign.title}}
    before = runtime.config.state_file.read_bytes()
    with assistant_actor_scope("admin" if admin else "teacher"):
        result = runtime._execute_assistant_action(a, action, {})
    if admin:
        assert result["class_session"]["lesson_id"] == foreign.lesson_id
    else:
        assert "class_session" not in result
        assert runtime.config.state_file.read_bytes() == before


def test_role_context_is_isolated_and_reset_after_failure(fixture):
    runtime, a, _, _, foreign, _ = fixture
    barrier = Barrier(2)
    def check(role):
        with assistant_actor_scope(role):
            barrier.wait(timeout=5)
            try:
                require_project_lesson(runtime.store, a, foreign.lesson_id)
                return True
            except KeyError:
                return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        admin = pool.submit(check, "admin")
        teacher = pool.submit(check, "teacher")
        assert admin.result() is True
        assert teacher.result() is False
    with pytest.raises(RuntimeError):
        with assistant_actor_scope("admin"):
            raise RuntimeError("fixture")
    with pytest.raises(KeyError):
        require_project_lesson(runtime.store, a, foreign.lesson_id)


def test_admin_role_is_carried_through_engine_callback_and_confirmation(fixture):
    runtime, a, _, _, foreign, _ = fixture
    action = {"tool_name": "start_class_session", "tool_params": {"lesson_id": foreign.lesson_id}}
    engine = runtime.session_engine
    def execute(**kwargs):
        result = engine.tool_executor.execute(a, "webgis", [action], {}, assistant_mode="interaction")
        return {"assistant_message": "fixture", "actions_executed": result}
    with patch.object(engine, "_handle_once", side_effect=execute):
        result = engine.handle("fixture", runtime.store.get_project(a), "开课", "interaction", "", [], {},
                               "webgis", "text", Mock(), actor_role="admin")
    assert result["actions_executed"][0]["result"]["class_session"]["lesson_id"] == foreign.lesson_id
    pending = runtime.store.create_confirmation(a, "", "", "tool", "fixture", "fixture", payload={"map_context": context(foreign)})
    result = engine.execute_confirmation(pending.confirmation_id, Mock(), actor_role="admin")
    assert pending.status == "approved"


@pytest.mark.parametrize("message", ["课堂问题", "生成教案"])
@pytest.mark.parametrize("path", ["top", "embedded"])
def test_http_private_lesson_rejection_has_no_job_or_design(fixture, monkeypatch, message, path):
    from backend.app import main
    runtime, a, _, _, foreign, _ = fixture
    monkeypatch.setattr(main, "config", runtime.config)
    monkeypatch.setattr(main, "runtime", runtime)
    monkeypatch.setattr(main, "auth_service", None)
    monkeypatch.setattr(main, "_local_user", lambda: {"user_id": "teacher-A", "role": "teacher"})
    payload = {"project_id": a, "message": message}
    payload["teaching_context" if path == "top" else "map_context"] = context(foreign)["teaching_context"] if path == "top" else context(foreign)
    before = runtime.config.state_file.read_bytes()
    with TestClient(main.app) as client:
        response = client.post("/assistant/messages", json=payload)
    assert response.status_code == 404
    assert runtime.config.state_file.read_bytes() == before


@pytest.mark.parametrize("role", ["teacher", "admin"])
def test_http_confirmation_uses_current_server_role_not_stored_role(fixture, monkeypatch, role):
    from backend.app import main
    runtime, a, _, _, foreign, _ = fixture
    pending = runtime.store.create_confirmation(a, "", "", "tool", "fixture", "fixture", payload={
        "actor_role": "admin", "frozen_plan": {"actor_role": "admin", "map_context": context(foreign)},
    })
    monkeypatch.setattr(main, "config", runtime.config)
    monkeypatch.setattr(main, "runtime", runtime)
    monkeypatch.setattr(main, "auth_service", None)
    monkeypatch.setattr(main, "_local_user", lambda: {"user_id": "teacher-A", "role": role})
    before = runtime.config.state_file.read_bytes()
    with patch("backend.app.runtime.threading.Thread") as worker, TestClient(main.app) as client:
        response = client.post("/assistant/confirm", json={"confirmation_id": pending.confirmation_id, "decision": "approve"})
        if role == "admin":
            assert response.status_code == 200
            assert worker.call_args.kwargs["args"][-1] == "admin"
        else:
            assert response.status_code == 404
            worker.assert_not_called()
            assert runtime.config.state_file.read_bytes() == before
    assert pending.status == "pending"
