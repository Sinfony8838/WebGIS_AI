"""S3: registered synthetic images only; provider calls are mocked."""
import os
import copy
import subprocess
import time
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from backend.app.config import AppConfig
from backend.app.runtime import TRANSPARENT_PNG, WebGISRuntime
from backend.app.services.agent_harness import HarnessExecutionError
from backend.app.services.image_references import resolve_project_image
from backend.app.services.vision import MapVisionService


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    for name in ("WEBGIS_AI_DATA_DIR", "WEBGIS_AI_AUTH_DB", "WEBGIS_AI_MINIMAX_API_KEY", "MINIMAX_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    config = AppConfig(root_dir=tmp_path, auth_mode="disabled")
    config.minimax_api_key = ""
    config.ensure_dirs()
    assert config.data_dir.resolve().is_relative_to(tmp_path.resolve())
    runtime = WebGISRuntime(config=config)
    a = runtime.create_project("A", owner_user_id="local")["project_id"]
    b = runtime.create_project("B", owner_user_id="local")["project_id"]
    own = runtime.upload_image_asset(a, "own.png", TRANSPARENT_PNG)["artifact"]
    foreign = runtime.upload_image_asset(b, "foreign.png", TRANSPARENT_PNG)["artifact"]
    config.vision_enabled = True
    config.vision_provider = "minimax_mcp"
    config.minimax_token_plan_key = "synthetic-test-key"
    client = Mock()
    client.understand_image.return_value = {"text": "合成图片显示曲流河道。", "raw": {}}
    runtime.vision_service.mcp_client = client
    runtime.session_engine.knowledge.minimax_client = None
    return runtime, a, b, own, foreign, client


def context(reference, plural=False):
    return {"image_attachments": [reference]} if plural else {"image_attachment": reference}


def wait_job(runtime, job_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = runtime.get_job(job_id)
        if job["status"] in {"completed", "failed"}:
            return job
        time.sleep(0.01)
    pytest.fail("Synthetic assistant job did not finish")


@pytest.mark.parametrize("path", ["top", "single", "plural"])
def test_foreign_image_rejected_without_open_job_thread_or_provider(fixture, path):
    runtime, a, _, _, foreign, client = fixture
    reference = {"artifact_id": foreign["artifact_id"], "path": foreign["path"]}
    kwargs = {"image_attachments": [reference]} if path == "top" else {"map_context": context(reference, path == "plural")}
    before = runtime.config.state_file.read_bytes()
    with patch.object(Path, "open", side_effect=AssertionError("No file reads")), patch("backend.app.runtime.threading.Thread") as worker:
        with pytest.raises(ValueError, match="其他项目"):
            runtime.submit_assistant_message(a, "识图", **kwargs)
        worker.assert_not_called()
    assert runtime.config.state_file.read_bytes() == before
    client.understand_image.assert_not_called()


@pytest.mark.parametrize("plural", [False, True])
def test_raw_path_rejected_without_resolving_or_opening_it(fixture, plural):
    runtime, a, _, _, _, client = fixture
    before = runtime.config.state_file.read_bytes()
    raw = {"path": "Z:/synthetic-private-fixture.png"}
    with patch.object(Path, "resolve", side_effect=AssertionError("No raw path resolution")):
        with pytest.raises(ValueError, match="artifact_id"):
            runtime.submit_assistant_message(a, "识图", map_context=context(raw, plural))
    assert runtime.config.state_file.read_bytes() == before
    client.understand_image.assert_not_called()


@pytest.mark.parametrize("path", ["top", "single", "plural"])
def test_own_reference_ignores_client_path_and_uses_registry(fixture, path):
    runtime, a, _, own, _, client = fixture
    ref = {"artifact_id": own["artifact_id"], "path": "Z:/ignored-fixture.png", "mime_type": "wrong"}
    ctx = context(ref, path == "plural") if path != "top" else {}
    ctx["vision_summary"] = "stale fabricated result"
    kwargs = {"image_attachments": [ref]} if path == "top" else {}
    accepted = runtime.submit_assistant_message(a, "这张图是什么地貌？", map_context=ctx, assistant_mode="knowledge", **kwargs)
    job = wait_job(runtime, accepted["job_id"])
    assert job["status"] == "completed", job
    assert "曲流" in job["result"]["assistant_message"]
    assert "fabricated" not in job["result"]["assistant_message"]
    client.understand_image.assert_called_once()
    assert Path(client.understand_image.call_args.kwargs["image_url"]) == Path(own["path"])


@pytest.mark.parametrize("artifact_type", ["uploaded_image", "generated_image", "map_snapshot"])
def test_all_supported_project_image_types_remain_valid(fixture, artifact_type):
    runtime, a, _, own, _, _ = fixture
    record = runtime.store.get_artifact(own["artifact_id"])
    record.artifact_type = artifact_type
    resolved = runtime.resolve_image_attachments(a, [{"artifact_id": record.artifact_id}])
    assert resolved[0]["path"] == own["path"]
    assert resolved[0]["mime_type"] == "image/png"


@pytest.mark.parametrize("failure", ["missing_id", "wrong_type", "wrong_project_path", "outside_path", "wrong_mime", "missing_file"])
def test_invalid_registry_reference_rejected_without_new_state(fixture, failure, tmp_path):
    runtime, a, _, own, foreign, client = fixture
    record = runtime.store.get_artifact(own["artifact_id"])
    ref = {"artifact_id": own["artifact_id"]}
    if failure == "missing_id":
        ref["artifact_id"] = "missing"
    elif failure == "wrong_type":
        record.artifact_type = "assistant_note"
    elif failure == "wrong_project_path":
        record.path = foreign["path"]
    elif failure == "outside_path":
        outside = tmp_path / "outside.png"
        outside.write_bytes(TRANSPARENT_PNG)
        record.path = str(outside)
    elif failure == "wrong_mime":
        bad = Path(own["path"]).with_suffix(".jpg")
        bad.write_bytes(TRANSPARENT_PNG)
        record.path = str(bad)
    else:
        Path(own["path"]).rename(Path(own["path"]).with_suffix(".retained"))
    before = runtime.config.state_file.read_bytes()
    with pytest.raises((KeyError, ValueError)):
        runtime.submit_assistant_message(a, "识图", map_context=context(ref))
    assert runtime.config.state_file.read_bytes() == before
    client.understand_image.assert_not_called()


def test_symlink_cannot_redirect_owned_image_to_another_project(fixture):
    runtime, a, _, own, foreign, _ = fixture
    link = Path(own["path"]).parent / "linked.png"
    try:
        os.symlink(foreign["path"], link)
    except OSError as exc:
        pytest.skip(f"Synthetic symlink creation unavailable: {type(exc).__name__}")
    runtime.store.get_artifact(own["artifact_id"]).path = str(link)
    with pytest.raises(ValueError, match="项目目录"):
        resolve_project_image(runtime.config, runtime.store, a, {"artifact_id": own["artifact_id"]})


@pytest.mark.skipif(os.name != "nt", reason="Windows Junction acceptance")
@pytest.mark.parametrize("kind", ["data_root", "project_redirect"])
def test_windows_synthetic_junction_boundary(fixture, tmp_path, kind):
    runtime, a, b, own, foreign, _ = fixture
    if kind == "data_root":
        link = tmp_path / "synthetic-data-link"
        target = runtime.config.data_dir
    else:
        project = runtime.store.create_project("synthetic linked project")
        link = runtime.config.uploads_dir / project.project_id
        target = runtime.config.uploads_dir / b
    assert link.absolute().is_relative_to(tmp_path.absolute())
    assert target.resolve().is_relative_to(tmp_path.resolve())
    assert not link.exists()
    script = tmp_path / "synthetic-junction.ps1"
    script.write_text(
        "param([string]$LinkPath,[string]$TargetPath)\n"
        "$ErrorActionPreference='Stop'\n"
        "New-Item -ItemType Junction -Path $LinkPath -Value $TargetPath | Out-Null\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(script), "-LinkPath", str(link), "-TargetPath", str(target)],
        check=True, capture_output=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if kind == "data_root":
        config = copy.copy(runtime.config)
        config.uploads_dir = link / "uploads"
        config.outputs_dir = link / "outputs"
        assert resolve_project_image(config, runtime.store, a, {"artifact_id": own["artifact_id"]})["path"] == own["path"]
    else:
        redirected = link / "image_library" / Path(foreign["path"]).name
        artifact = runtime.store.register_artifact(project.project_id, "", "uploaded_image", "fixture", str(redirected))
        with pytest.raises(ValueError, match="项目目录"):
            resolve_project_image(runtime.config, runtime.store, project.project_id, {"artifact_id": artifact.artifact_id})


@pytest.mark.parametrize("reference", ["foreign", "raw"])
def test_history_revalidated_before_job_and_memory(fixture, reference):
    runtime, a, _, _, foreign, client = fixture
    conversation = runtime.store.create_conversation(a, "knowledge")
    remembered = {"artifact_id": foreign["artifact_id"]} if reference == "foreign" else {"path": "Z:/fixture.png"}
    conversation.pinned_state["last_image_attachment"] = remembered
    runtime.store._save()
    before = runtime.config.state_file.read_bytes()
    with pytest.raises(ValueError):
        runtime.submit_assistant_message(a, "刚才的图片为什么会这样？", conversation_id=conversation.conversation_id)
    with pytest.raises(HarnessExecutionError):
        runtime.session_engine.handle("fixture", runtime.store.get_project(a), "刚才的图片为什么会这样？", "knowledge",
                                      conversation.conversation_id, [], {}, "webgis", "text", Mock())
    assert runtime.config.state_file.read_bytes() == before
    client.understand_image.assert_not_called()


@pytest.mark.parametrize("frozen", [False, True])
@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_confirmation_rechecks_images_before_resolution(fixture, frozen, decision):
    runtime, a, _, _, foreign, client = fixture
    plan = {"map_context": context({"artifact_id": foreign["artifact_id"]}), "actions": []}
    payload = {"frozen_plan": plan} if frozen else plan
    pending = runtime.store.create_confirmation(a, "", "", "tool", "fixture", "fixture", payload=payload)
    before = runtime.config.state_file.read_bytes()
    with pytest.raises(ValueError):
        runtime.confirm_assistant_action(pending.confirmation_id, decision)
    with pytest.raises(HarnessExecutionError):
        if decision == "approve":
            runtime.session_engine.execute_confirmation(pending.confirmation_id, Mock())
        else:
            runtime.session_engine.reject_confirmation(pending.confirmation_id)
    assert pending.status == "pending"
    assert runtime.config.state_file.read_bytes() == before
    client.understand_image.assert_not_called()


def test_direct_knowledge_and_tool_paths_reject_foreign_before_effect(fixture):
    runtime, a, _, _, foreign, client = fixture
    conversation = runtime.store.create_conversation(a, "knowledge")
    ctx = context({"artifact_id": foreign["artifact_id"], "path": foreign["path"]})
    before = runtime.config.state_file.read_bytes()
    with pytest.raises(ValueError):
        runtime.session_engine._handle_knowledge(runtime.store.get_project(a), conversation, "识图", ctx, Mock())
    action = {"tool_name": "set_view", "tool_params": {"zoom": 9}}
    with pytest.raises(ValueError):
        runtime.session_engine.tool_executor.execute(a, "webgis", [action], ctx)
    with pytest.raises(ValueError):
        runtime._execute_assistant_action(a, action, ctx)
    assert runtime.config.state_file.read_bytes() == before
    client.understand_image.assert_not_called()


@pytest.mark.parametrize("unbound", [False, True])
def test_vision_boundary_refuses_raw_path_without_any_file_probe(fixture, unbound):
    runtime, a, _, _, _, client = fixture
    service = MapVisionService(runtime.config, mcp_client=client) if unbound else runtime.vision_service
    with patch.object(Path, "resolve", side_effect=AssertionError("No raw path resolution")), patch.object(Path, "open", side_effect=AssertionError("No reads")):
        result = service.understand_image("Z:/fixture-private.png", "识图", project_id=a)
    assert result["used_vision"] is False
    assert result["snapshot_path"] == ""
    client.understand_image.assert_not_called()


def test_vision_revalidates_foreign_and_canonicalizes_owned_reference(fixture):
    runtime, a, _, own, foreign, client = fixture
    result = runtime.vision_service.understand_image(foreign["path"], "识图", project_id=a, artifact_id=foreign["artifact_id"])
    assert result["used_vision"] is False
    client.understand_image.assert_not_called()
    result = runtime.vision_service.understand_image("Z:/ignored.png", "识图", project_id=a, artifact_id=own["artifact_id"])
    assert result["used_vision"] is True
    assert client.understand_image.call_args.kwargs["image_url"] == own["path"]


def test_http_embedded_image_rejected_before_job_or_lesson_design(fixture, monkeypatch):
    from backend.app import main
    runtime, a, _, _, foreign, _ = fixture
    monkeypatch.setattr(main, "config", runtime.config)
    monkeypatch.setattr(main, "runtime", runtime)
    monkeypatch.setattr(main, "auth_service", None)
    before = runtime.config.state_file.read_bytes()
    with TestClient(main.app) as client:
        response = client.post("/assistant/messages", json={
            "project_id": a, "message": "生成教案", "map_context": context({"artifact_id": foreign["artifact_id"]}),
        })
    assert response.status_code == 400
    assert runtime.config.state_file.read_bytes() == before
