"""S1: project-bound assistant references, using synthetic isolated state only."""
from __future__ import annotations

from unittest.mock import Mock, patch
import time

import pytest
from fastapi.testclient import TestClient

from backend.app.config import AppConfig
from backend.app.runtime import WebGISRuntime
from backend.app.services.agent_harness import HarnessExecutionError
from backend.app.services.session_engine import ConversationMemory


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    for name in ("WEBGIS_AI_DATA_DIR", "WEBGIS_AI_AUTH_DB",
                 "WEBGIS_AI_MINIMAX_API_KEY", "MINIMAX_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    config = AppConfig(root_dir=tmp_path, auth_mode="disabled")
    config.minimax_api_key = ""
    config.ensure_dirs()
    assert config.data_dir.resolve().is_relative_to(tmp_path.resolve())
    instance = WebGISRuntime(config=config)
    return instance


def projects(runtime):
    a = runtime.create_project("A", owner_user_id="local")["project_id"]
    b = runtime.create_project("B", owner_user_id="local")["project_id"]
    return a, b


def state_bytes(runtime):
    return runtime.config.state_file.read_bytes()


def confirmation(runtime, project_id, conversation_id, expires_at=""):
    return runtime.store.create_confirmation(
        project_id, conversation_id, "", "tool", "fixture", "fixture",
        payload={"actions": [], "map_context": {}}, expires_at=expires_at,
    )


def test_memory_rejects_foreign_before_grounding_or_compression(runtime):
    a, b = projects(runtime)
    conversation = runtime.store.create_conversation(b, "teaching")
    for index in range(18):
        runtime.store.append_conversation_message(conversation.conversation_id, "user", f"fixture {index}")
    before = state_bytes(runtime)
    with pytest.raises(ValueError, match="requested project"):
        ConversationMemory(runtime.store).get_or_create(
            a, "teaching", conversation.conversation_id,
            history=[{"role": "user", "text": "foreign seed"}],
            map_context={"zoom": 99},
        )
    assert state_bytes(runtime) == before
    assert len(conversation.raw_messages) == 18


def test_missing_explicit_reference_does_not_create_replacement(runtime):
    a, _ = projects(runtime)
    before = state_bytes(runtime)
    with pytest.raises(KeyError, match="Unknown conversation"):
        runtime.session_engine.memory.get_or_create(a, "knowledge", "missing")
    assert state_bytes(runtime) == before


def test_same_project_memory_retains_history_and_accepts_new_grounding(runtime):
    a, _ = projects(runtime)
    memory = runtime.session_engine.memory
    conversation = memory.get_or_create(
        a, "knowledge", history=[{"role": "user", "text": "original"}],
    )
    resumed = memory.get_or_create(
        a, "teaching", conversation.conversation_id,
        history=[{"role": "user", "text": "do not seed twice"}],
        map_context={"zoom": 5},
    )
    assert resumed is conversation
    assert [item["text"] for item in resumed.raw_messages] == ["original"]
    assert resumed.last_map_grounding == {"zoom": 5}
    assert resumed.project_id == a


@pytest.mark.parametrize("reuse", [False, True])
def test_legal_message_finishes_with_new_or_same_project_conversation(runtime, reuse):
    a, _ = projects(runtime)
    conversation = runtime.store.create_conversation(a, "knowledge") if reuse else None
    with patch.object(runtime.minimax_client, "chat_completion", side_effect=AssertionError("No model calls")):
        accepted = runtime.submit_assistant_message(
            a, "你是谁", assistant_mode="knowledge",
            conversation_id=conversation.conversation_id if conversation else "",
        )
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            job = runtime.get_job(accepted["job_id"])
            if job["status"] in {"completed", "failed"}:
                break
            time.sleep(0.01)
        assert job["status"] == "completed", job
        result_conversation = runtime.store.get_conversation(job["result"]["conversation_id"])
        assert result_conversation.project_id == a
        if conversation:
            assert result_conversation.conversation_id == conversation.conversation_id


@pytest.mark.parametrize("reference", ["foreign", "missing"])
def test_runtime_rejects_before_job_thread_or_attachment_resolution(runtime, reference):
    a, b = projects(runtime)
    foreign = runtime.store.create_conversation(b, "knowledge")
    reference_id = foreign.conversation_id if reference == "foreign" else "missing"
    before = state_bytes(runtime)
    with patch.object(runtime.store, "create_job") as create_job, \
         patch.object(runtime, "resolve_image_attachments") as resolve, \
         patch("backend.app.runtime.threading.Thread") as thread:
        with pytest.raises((ValueError, KeyError)):
            runtime.submit_assistant_message(
                a, "fixture", conversation_id=reference_id,
                image_attachments=[{"path": "never-read"}],
            )
        create_job.assert_not_called()
        resolve.assert_not_called()
        thread.assert_not_called()
    assert state_bytes(runtime) == before


def test_direct_engine_rejects_foreign_without_memory_or_provider_calls(runtime):
    a, b = projects(runtime)
    foreign = runtime.store.create_conversation(b, "knowledge")
    before = state_bytes(runtime)
    callback = Mock()
    with patch.object(runtime.session_engine.knowledge, "answer") as answer, \
         patch.object(runtime.session_engine.tool_planner, "plan") as plan:
        with pytest.raises(HarnessExecutionError, match="requested project"):
            runtime.session_engine.handle(
                job_id="fixture", project=runtime.store.get_project(a),
                message="fixture", assistant_mode="knowledge",
                conversation_id=foreign.conversation_id, history=[],
                map_context={"zoom": 10}, target="webgis", input_mode="text",
                stage_callback=callback,
            )
        answer.assert_not_called()
        plan.assert_not_called()
    callback.assert_not_called()
    assert state_bytes(runtime) == before


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_runtime_confirmation_rejects_foreign_before_job(runtime, decision):
    a, b = projects(runtime)
    foreign = runtime.store.create_conversation(b, "tool")
    pending = confirmation(runtime, a, foreign.conversation_id)
    before = state_bytes(runtime)
    with patch.object(runtime.store, "create_job") as create_job, \
         patch("backend.app.runtime.threading.Thread") as thread:
        with pytest.raises(ValueError, match="requested project"):
            runtime.confirm_assistant_action(pending.confirmation_id, decision)
        create_job.assert_not_called()
        thread.assert_not_called()
    assert pending.status == "pending"
    assert state_bytes(runtime) == before


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_direct_confirmation_rejects_before_expiry_tools_or_mutation(runtime, decision):
    a, b = projects(runtime)
    foreign = runtime.store.create_conversation(b, "tool")
    pending = confirmation(runtime, a, foreign.conversation_id, "2000-01-01T00:00:00Z")
    before = state_bytes(runtime)
    callback = Mock()
    with patch.object(runtime.session_engine.tool_executor, "assess") as assess, \
         patch.object(runtime.session_engine.tool_executor, "execute") as execute:
        with pytest.raises(HarnessExecutionError, match="requested project"):
            if decision == "approve":
                runtime.session_engine.execute_confirmation(pending.confirmation_id, callback)
            else:
                runtime.session_engine.reject_confirmation(pending.confirmation_id)
        assess.assert_not_called()
        execute.assert_not_called()
    callback.assert_not_called()
    assert pending.status == "pending"
    assert state_bytes(runtime) == before


@pytest.mark.parametrize("missing_reference", [False, True])
def test_explicit_missing_confirmation_reference_has_no_side_effects(runtime, missing_reference):
    a, b = projects(runtime)
    conversation = runtime.store.create_conversation(a, "tool")
    pending = confirmation(runtime, a, conversation.conversation_id if not missing_reference else "missing")
    if not missing_reference:
        # Removing a conversation models a reference that becomes stale after admission.
        runtime.store.conversations.pop(conversation.conversation_id)
    before = state_bytes(runtime)
    with pytest.raises(KeyError, match="Unknown conversation"):
        runtime.confirm_assistant_action(pending.confirmation_id)
    assert pending.status == "pending"
    assert state_bytes(runtime) == before


@pytest.mark.parametrize("with_conversation", [False, True])
def test_legal_confirmation_rejection_keeps_legacy_blank_reference(runtime, with_conversation):
    a, _ = projects(runtime)
    conversation = runtime.store.create_conversation(a, "tool") if with_conversation else None
    pending = confirmation(runtime, a, conversation.conversation_id if conversation else "")
    result = runtime.session_engine.reject_confirmation(pending.confirmation_id)
    assert result["planner"] == "confirmation_rejected"
    assert result["actions_executed"] == []
    assert pending.status == "rejected"
    if conversation:
        assert runtime.store.list_conversation_messages(conversation.conversation_id)


@pytest.fixture
def client(runtime, monkeypatch):
    from backend.app import main as app_main
    monkeypatch.setattr(app_main, "config", runtime.config)
    monkeypatch.setattr(app_main, "runtime", runtime)
    monkeypatch.setattr(app_main, "auth_service", None)
    with TestClient(app_main.app) as instance:
        yield instance


@pytest.mark.parametrize("reference,status", [("foreign", 400), ("missing", 404)])
def test_http_message_rejects_binding_without_job_or_lesson_design(runtime, client, reference, status):
    a, b = projects(runtime)
    foreign = runtime.store.create_conversation(b, "teaching")
    before = state_bytes(runtime)
    with patch.object(runtime.classroom, "create_lesson_design") as design:
        response = client.post("/assistant/messages", json={
            "project_id": a, "message": "共创教案", "assistant_mode": "teaching",
            "conversation_id": foreign.conversation_id if reference == "foreign" else "missing",
        })
        assert response.status_code == status, response.text
        design.assert_not_called()
    assert state_bytes(runtime) == before


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_http_confirmation_rejects_binding_without_resolving_pending(runtime, client, decision):
    a, b = projects(runtime)
    foreign = runtime.store.create_conversation(b, "tool")
    pending = confirmation(runtime, a, foreign.conversation_id)
    before = state_bytes(runtime)
    response = client.post("/assistant/confirm", json={
        "confirmation_id": pending.confirmation_id, "decision": decision,
    })
    assert response.status_code == 400, response.text
    assert pending.status == "pending"
    assert state_bytes(runtime) == before
