"""S2 session references: synthetic data, no model, GIS or Office calls."""
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from backend.app.config import AppConfig
from backend.app.runtime import WebGISRuntime
from backend.app.services.classroom_binding import require_classroom_context
from backend.app.services.agent_harness import HarnessExecutionError


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    for name in ("WEBGIS_AI_DATA_DIR", "WEBGIS_AI_AUTH_DB",
                 "WEBGIS_AI_MINIMAX_API_KEY", "MINIMAX_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    config = AppConfig(root_dir=tmp_path, auth_mode="disabled")
    config.minimax_api_key = ""
    config.ensure_dirs()
    assert config.data_dir.resolve().is_relative_to(tmp_path.resolve())
    runtime = WebGISRuntime(config=config)
    a = runtime.create_project("A", owner_user_id="local")["project_id"]
    b = runtime.create_project("B", owner_user_id="local")["project_id"]
    sa = runtime.store.create_class_session("lesson-A", a, "111111")
    sb = runtime.store.create_class_session("lesson-B", b, "222222")
    return runtime, a, b, sa, sb


def context(session, **fields):
    return {"teaching_context": {"session_id": session.session_id, **fields}}


@pytest.mark.parametrize("path", ["embedded", "top", "both"])
def test_message_rejects_foreign_before_attachment_job_thread(fixture, path):
    runtime, a, _, _, foreign = fixture
    before = runtime.config.state_file.read_bytes()
    kwargs = {}
    if path in {"embedded", "both"}:
        kwargs["map_context"] = context(foreign)
    if path in {"top", "both"}:
        kwargs["teaching_context"] = context(foreign)["teaching_context"]
    with patch.object(runtime, "resolve_image_attachments") as attachments, patch("backend.app.runtime.threading.Thread") as thread:
        with pytest.raises(ValueError, match="requested project"):
            runtime.submit_assistant_message(a, "统计课堂", **kwargs)
        attachments.assert_not_called()
        thread.assert_not_called()
    assert runtime.config.state_file.read_bytes() == before


@pytest.mark.parametrize("fields,error", [
    ({"session_id": "missing"}, KeyError),
    ({"lesson_id": "wrong"}, ValueError),
    ({"project_id": "wrong"}, ValueError),
])
def test_inconsistent_reference_rejected_before_job(fixture, fields, error):
    runtime, a, _, session, _ = fixture
    before = runtime.config.state_file.read_bytes()
    with pytest.raises(error):
        runtime.submit_assistant_message(a, "课堂", map_context=context(session, **fields))
    assert runtime.config.state_file.read_bytes() == before


def test_internal_engine_rejects_before_memory_or_model(fixture):
    runtime, a, _, _, foreign = fixture
    before = runtime.config.state_file.read_bytes()
    with patch.object(runtime.session_engine.memory, "get_or_create") as memory:
        with pytest.raises(HarnessExecutionError):
            runtime.session_engine.handle(
                "fixture", runtime.store.get_project(a), "统计", "teaching", "", [],
                context(foreign), "webgis", "text", Mock(),
            )
        memory.assert_not_called()
    assert runtime.config.state_file.read_bytes() == before


@pytest.mark.parametrize("frozen", [False, True])
@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_confirmation_rejects_bad_context_without_resolution(fixture, frozen, decision):
    runtime, a, _, _, foreign = fixture
    payload = {"actions": [], "map_context": context(foreign)}
    if frozen:
        payload = {"map_context": {}, "frozen_plan": payload}
    confirmation = runtime.store.create_confirmation(a, "", "", "tool", "fixture", "fixture", payload=payload)
    before = runtime.config.state_file.read_bytes()
    with patch("backend.app.runtime.threading.Thread") as thread:
        with pytest.raises(ValueError):
            runtime.confirm_assistant_action(confirmation.confirmation_id, decision)
        thread.assert_not_called()
    with pytest.raises(HarnessExecutionError):
        if decision == "approve":
            runtime.session_engine.execute_confirmation(confirmation.confirmation_id, Mock())
        else:
            runtime.session_engine.reject_confirmation(confirmation.confirmation_id)
    assert confirmation.status == "pending"
    assert runtime.config.state_file.read_bytes() == before


@pytest.mark.parametrize("tool", ["record_observation", "launch_question", "enter_lesson_stage", "end_class_session"])
def test_direct_tool_cannot_write_foreign_class(fixture, tool):
    runtime, a, _, _, foreign = fixture
    before = runtime.config.state_file.read_bytes()
    params = {"verdict": "correct"} if tool == "record_observation" else (
        {"text": "fixture"} if tool == "launch_question" else {}
    )
    action = {"tool_name": tool, "tool_params": params}
    mode = "teaching_action" if tool in {"record_observation", "launch_question"} else "interaction"
    assessment = runtime.session_engine.tool_executor.assess(
        "webgis", [action], assistant_mode=mode,
        project_state={"project_id": a}, map_context=context(foreign),
    )
    assert assessment["risk_level"] == "blocked"
    assert "requested project" in assessment["actions_planned"][0]["validation_error"]
    with pytest.raises(ValueError):
        runtime.session_engine.tool_executor.execute(a, "webgis", [action], context(foreign), allow_high_risk=True)
    with pytest.raises(ValueError):
        runtime._execute_assistant_action(a, action, context(foreign))
    assert runtime.config.state_file.read_bytes() == before


def test_live_tool_validation_keeps_same_project_and_rejects_ended(fixture):
    runtime, a, _, session, _ = fixture
    validator = runtime.session_engine.tool_executor._require_active_session
    assert validator({}, {"project_id": a}, context(session)) == ""
    session.status = "ended"
    assert validator({}, {"project_id": a}, context(session))


def test_statistics_and_digest_require_project_before_reading(fixture):
    runtime, a, _, _, foreign = fixture
    with patch.object(runtime.classroom.report_service, "build_statistics") as statistics:
        with pytest.raises(ValueError):
            runtime._session_statistics_for_assistant(a, foreign.session_id)
        with pytest.raises(ValueError):
            runtime.session_engine._inject_session_digest(a, context(foreign, phase="post_class"), "teaching_reflect")
        statistics.assert_not_called()


def test_log_uses_job_project_and_preserves_foreign_session(fixture):
    runtime, a, _, session, foreign = fixture
    job = runtime.store.create_job(a, "assistant", "fixture")
    before = runtime.config.state_file.read_bytes()
    runtime._log_assistant_exchange(job.job_id, context(foreign), "fixture", {})
    assert runtime.config.state_file.read_bytes() == before
    runtime._log_assistant_exchange(job.job_id, context(session), "fixture", {})
    assert session.events[-1]["type"] == "assistant_exchange"
    assert not foreign.events


@pytest.mark.parametrize("ended", [False, True])
def test_own_session_with_historical_lesson_and_no_context_stays_valid(fixture, ended):
    runtime, a, _, session, _ = fixture
    if ended:
        session.status = "ended"
    assert require_classroom_context(runtime.store, a, context(session, lesson_id=session.lesson_id)) is session
    assert require_classroom_context(runtime.store, a, {}) is None
    provider = Mock(return_value={"participant_count": 3, "questions": []})
    runtime.session_engine.set_session_stats_provider(provider)
    result = runtime.session_engine._inject_session_digest(a, context(session, phase="post_class"), "teaching_reflect")
    assert '"participant_count": 3' in result["session_digest"]
    provider.assert_called_once_with(a, session.session_id)


def test_http_rejects_foreign_without_lesson_design(fixture, monkeypatch):
    from backend.app import main
    runtime, a, _, _, foreign = fixture
    monkeypatch.setattr(main, "config", runtime.config)
    monkeypatch.setattr(main, "runtime", runtime)
    monkeypatch.setattr(main, "auth_service", None)
    before = runtime.config.state_file.read_bytes()
    with TestClient(main.app) as client:
        response = client.post("/assistant/messages", json={
            "project_id": a, "message": "生成教案", "teaching_context": context(foreign)["teaching_context"],
        })
    assert response.status_code == 400
    assert runtime.config.state_file.read_bytes() == before
