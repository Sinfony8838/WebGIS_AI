"""Restart recovery uses only synthetic snapshots and stub services."""
import json
from contextlib import ExitStack
from copy import deepcopy
from unittest.mock import Mock, patch

import pytest

from backend.app import runtime as runtime_module
from backend.app.config import AppConfig
from backend.app.models import ClassSessionRecord, WorkflowRecord
from backend.app.store import RuntimeStore


def config_for(tmp_path):
    config = AppConfig(root_dir=tmp_path)
    config.data_dir = tmp_path / "data"
    config.state_dir = config.data_dir / "state"
    config.state_file = config.state_dir / "runtime.json"
    config.uploads_dir = config.data_dir / "uploads"
    config.outputs_dir = config.data_dir / "outputs"
    config.workflows_dir = config.data_dir / "workflows"
    config.ensure_dirs()
    return config


@pytest.fixture
def snapshot(tmp_path):
    config = config_for(tmp_path)
    store = RuntimeStore(config.state_file)
    project = store.create_project("synthetic restart classroom")
    job = store.create_job(project.project_id, "export", "synthetic export")
    job.status = "running"
    job.stages["artifacts"] = {"status": "running", "message": "working"}
    job.artifact_ids = ["retained-artifact"]
    job.result = {"retained": True}
    workflow = WorkflowRecord.create(project.project_id)
    workflow.status = "running"
    workflow.steps = [{"id": "done", "status": "success", "outputs": {"value": 42}},
                      {"id": "active", "status": "running"},
                      {"id": "next", "status": "pending"}]
    workflow.artifacts = [{"artifact_id": "retained-wf-artifact", "public_url": "/synthetic"}]
    store.create_workflow(workflow)
    session = ClassSessionRecord.create("synthetic-lesson", project.project_id, "synthetic")
    session.responses = {"q": [{"answer": "retained"}]}
    store.class_sessions[session.session_id] = session
    confirmation = store.create_confirmation(project.project_id, "synthetic-conversation", job.job_id,
                                             "teaching", "synthetic", "retained")
    store._save()
    yield config, store, job, workflow, session, confirmation
    store.close()


def test_restart_finalizes_once_preserving_classroom_artifacts_and_ids(snapshot):
    config, store, job, workflow, session, confirmation = snapshot
    before = json.loads(config.state_file.read_text(encoding="utf-8"))
    with patch.object(store, "_save", wraps=store._save) as save:
        result = store.reconcile_interrupted_tasks()
    assert result == {"jobs": [job.job_id], "workflows": [workflow.workflow_id]}
    assert save.call_count == 1
    restored_job = store.get_job(job.job_id)
    restored_workflow = store.get_workflow(workflow.workflow_id)
    assert restored_job.status == "failed"
    assert restored_job.stages["artifacts"]["status"] == "error"
    assert restored_job.artifact_ids == job.artifact_ids
    assert restored_job.result == job.result
    assert restored_workflow.status == "error"
    assert restored_workflow.error["code"] == "INTERNAL_ERROR"
    assert restored_workflow.error["details"]["reason"] == "service_restart"
    assert restored_workflow.finished_at
    assert restored_workflow.steps[0] == workflow.steps[0]
    assert restored_workflow.steps[1]["status"] == "error"
    assert restored_workflow.steps[1]["error"]["step_id"] == "active"
    assert restored_workflow.steps[2] == workflow.steps[2]
    assert restored_workflow.artifacts == workflow.artifacts
    after = json.loads(config.state_file.read_text(encoding="utf-8"))
    for collection in set(before) - {"jobs", "workflows"}:
        assert after[collection] == before[collection]
    assert store.get_confirmation(confirmation.confirmation_id).status == "pending"
    assert store.class_sessions[session.session_id].status == "running"
    terminal_bytes = config.state_file.read_bytes()
    # A second call in this process must not classify newly started work.
    active = store.create_job(job.project_id, "export", "current process")
    with patch.object(store, "_save", wraps=store._save) as save:
        assert store.reconcile_interrupted_tasks() == {"jobs": [], "workflows": []}
        save.assert_not_called()
    assert active.status == "queued"
    store.close()
    reloaded = RuntimeStore(config.state_file)
    try:
        assert reloaded.reconcile_interrupted_tasks()["jobs"] == [active.job_id]
        reloaded.close()
        again = RuntimeStore(config.state_file)
        try:
            final_bytes = config.state_file.read_bytes()
            assert again.reconcile_interrupted_tasks() == {"jobs": [], "workflows": []}
            assert config.state_file.read_bytes() == final_bytes
            assert again.get_workflow(workflow.workflow_id).to_dict() == restored_workflow.to_dict()
        finally:
            again.close()
    finally:
        reloaded.close()
    assert terminal_bytes


@pytest.mark.parametrize("status", ["pending", "waiting_for_approval", "completed", "failed", "cancelled"])
def test_human_waits_and_terminal_jobs_unchanged(snapshot, status):
    config, store, job, workflow, *_ = snapshot
    job.status = status
    workflow.status = "success"
    store._save()
    before = config.state_file.read_bytes()
    assert store.reconcile_interrupted_tasks() == {"jobs": [], "workflows": []}
    assert config.state_file.read_bytes() == before


@pytest.mark.parametrize("status", ["queued", "running", "pending"])
def test_legacy_in_process_practice_export_message_preserved(snapshot, status):
    _, store, job, workflow, *_ = snapshot
    job.job_type, job.status = "practice_export", status
    job.request = {"execution_mode": "in_process", "worker_run_id": "old-run"}
    workflow.status = "cancelled"
    result = store.reconcile_interrupted_tasks()
    assert result["jobs"] == [job.job_id]
    assert store.get_job(job.job_id).error == "服务重启中断了练习卷生成，请重新导出。"


@pytest.mark.parametrize("status", ["success", "error", "cancelled"])
def test_terminal_workflows_preserved(snapshot, status):
    config, store, job, workflow, *_ = snapshot
    job.status = "completed"
    workflow.status = status
    workflow.error = {"code": "retained"}
    store._save()
    before = config.state_file.read_bytes()
    assert store.reconcile_interrupted_tasks() == {"jobs": [], "workflows": []}
    assert config.state_file.read_bytes() == before


def test_pending_workflow_terminates_without_starting_steps(snapshot):
    _, store, _, workflow, *_ = snapshot
    workflow.status = "pending"
    workflow.steps = [{"id": "waiting", "status": "pending"}]
    store.reconcile_interrupted_tasks()
    assert store.get_workflow(workflow.workflow_id).status == "error"
    assert store.get_workflow(workflow.workflow_id).steps == workflow.steps


@pytest.mark.parametrize("operation", ["write_text", "replace"])
def test_commit_failure_preserves_original_bytes_and_active_objects(snapshot, operation):
    config, store, job, workflow, *_ = snapshot
    before = config.state_file.read_bytes()
    job_before, workflow_before = deepcopy(job.to_dict()), deepcopy(workflow.to_dict())
    old_jobs, old_workflows = store.jobs, store.workflows
    with patch.object(type(config.state_file), operation, side_effect=PermissionError("synthetic I/O denial")):
        with pytest.raises(PermissionError):
            store.reconcile_interrupted_tasks()
    assert config.state_file.read_bytes() == before
    assert store.jobs is old_jobs and store.workflows is old_workflows
    assert store.get_job(job.job_id) is job
    assert job.to_dict() == job_before and workflow.to_dict() == workflow_before
    assert not store._startup_reconciled
    assert not list(config.state_dir.glob("*.tmp"))
    assert store.reconcile_interrupted_tasks()["jobs"] == [job.job_id]


def test_read_only_snapshot_cannot_reconcile(snapshot):
    config, _, job, workflow, *_ = snapshot
    before = config.state_file.read_bytes()
    reader = RuntimeStore(config.state_file, read_only=True)
    try:
        with pytest.raises(RuntimeError, match="read-only"):
            reader.reconcile_interrupted_tasks()
        assert reader.get_job(job.job_id).status == "running"
        assert reader.get_workflow(workflow.workflow_id).status == "running"
        assert config.state_file.read_bytes() == before
    finally:
        reader.close()


def test_startup_reconciliation_refuses_deferred_batch(snapshot):
    config, store, *_ = snapshot
    before = config.state_file.read_bytes()
    with store.batch():
        with pytest.raises(RuntimeError, match="batch"):
            store.reconcile_interrupted_tasks()
    assert config.state_file.read_bytes() == before


@pytest.mark.parametrize("injected", [False, True])
def test_runtime_reconciles_before_first_service_only_for_fresh_store(snapshot, injected):
    config, store, job, workflow, *_ = snapshot
    loaded = []
    if not injected:
        store.close()

    def load_store(*args, **kwargs):
        instance = RuntimeStore(*args, **kwargs)
        loaded.append(instance)
        return instance

    def first_service(_config, instance):
        expected = "running" if injected else "failed"
        assert instance.get_job(job.job_id).status == expected
        assert instance.get_workflow(workflow.workflow_id).status == ("running" if injected else "error")
        raise LookupError("synthetic first-service boundary")

    try:
        with patch.object(runtime_module, "RuntimeStore", side_effect=load_store) as factory, \
                patch.object(runtime_module, "DatasetService", side_effect=first_service), \
                patch.object(runtime_module, "build_llm_client") as provider:
            with pytest.raises(LookupError, match="first-service"):
                runtime_module.WebGISRuntime(config, store=store if injected else None)
            assert factory.call_count == (0 if injected else 1)
            provider.assert_not_called()
    finally:
        for instance in loaded:
            instance.close()


def test_boot_commit_failure_aborts_services_and_releases_writer(snapshot):
    config, store, *_ = snapshot
    before = config.state_file.read_bytes()
    store.close()
    with patch.object(RuntimeStore, "_write_state_file", side_effect=OSError("synthetic disk failure")), \
            patch.object(runtime_module, "DatasetService") as service:
        with pytest.raises(OSError):
            runtime_module.WebGISRuntime(config)
        service.assert_not_called()
    assert config.state_file.read_bytes() == before
    reopened = RuntimeStore(config.state_file)
    reopened.close()


def test_runtime_updates_status_mirror_without_replaying_worker_or_provider(snapshot):
    config, store, job, workflow, *_ = snapshot
    directory = config.workflow_dir(workflow.workflow_id)
    retained = directory / "outputs" / "retained.txt"
    retained.write_text("retained synthetic file", encoding="utf-8")
    store.close()
    factories = ["DatasetService", "TemplateService", "AssistantService", "KnowledgeService",
                 "KnowledgeBaseService", "OneMapCatalogService", "PopulationSourceRegistryService",
                 "ResourceSearchService", "PoiService", "MapVisionService", "build_llm_client",
                 "MiniMaxImageClient", "TeachingMapService", "LLMPlanner", "AssistantSessionEngine",
                 "TimelineService", "VoiceAsrEngine", "ClassroomWorkflowRuntime"]
    with ExitStack() as stack:
        for name in factories:
            stack.enter_context(patch.object(runtime_module, name))
        stack.enter_context(patch.object(runtime_module.WebGISRuntime, "_normalize_loaded_projects"))
        worker = Mock()
        stack.enter_context(patch("backend.app.services.workflow_executor.PyQgisWorkerManager", return_value=worker))
        runtime = runtime_module.WebGISRuntime(config)
        try:
            mirror = json.loads((directory / "status.json").read_text(encoding="utf-8"))
            assert mirror["status"] == "error" and mirror["finished_at"]
            assert mirror["steps"] == runtime.store.get_workflow(workflow.workflow_id).steps
            assert retained.read_text(encoding="utf-8") == "retained synthetic file"
            assert runtime.store.get_job(job.job_id).status == "failed"
            assert not runtime.workflow_executor._workers
            assert not runtime.workflow_executor._cancel_events
            worker.ensure_started.assert_not_called()
            worker.run_step.assert_not_called()
        finally:
            runtime.store.close()
