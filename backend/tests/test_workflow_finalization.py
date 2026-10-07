"""Synthetic snapshots and stub workers; no QGIS/model subprocesses."""
import json
import threading
from unittest.mock import patch

import pytest

from backend.app.config import AppConfig
from backend.app.models import WorkflowRecord
from backend.app.services.pyqgis_worker.errors import make_error
from backend.app.services.workflow_executor import WorkflowExecutor
from backend.app.store import RuntimeStore


class Worker:
    def __init__(self):
        self.outcome = "success"
        self.release_fails = False
        self.released = []
        self.steps = []

    def run_step(self, workflow_id, step):
        self.steps.append(step["id"])
        if self.outcome == "raise":
            raise RuntimeError("synthetic worker exception")
        if self.outcome == "none":
            return None
        if self.outcome == "list":
            return ["unexpected"]
        if self.outcome in {"cancelled", "error"}:
            return {"status": "error", "error": make_error(
                "STEP_CANCELLED" if self.outcome == "cancelled" else "PROCESSING_FAILED",
                "synthetic known error",
            )}
        return {"status": "success", "outputs": {}}

    def release_workflow(self, workflow_id):
        self.released.append(workflow_id)
        if self.release_fails:
            raise RuntimeError("synthetic release failure")


@pytest.fixture
def execution(tmp_path):
    config = AppConfig()
    config.data_dir = tmp_path / "data"
    config.state_dir = config.data_dir / "state"
    config.state_file = config.state_dir / "runtime.json"
    config.uploads_dir = config.data_dir / "uploads"
    config.outputs_dir = config.data_dir / "outputs"
    config.workflows_dir = config.data_dir / "workflows"
    config.workflow_queue_max = 1
    config.ensure_dirs()
    store = RuntimeStore(config.state_file)
    worker = Worker()
    executor = WorkflowExecutor(config, store, worker_manager=worker)
    record = WorkflowRecord.create(project_id="synthetic", workflow_json={
        "steps": [{"id": "s1", "op": "load_layer", "params": {}},
                  {"id": "s2", "op": "export_geojson", "params": {}, "depends_on": ["s1"]}],
    })
    store.create_workflow(record)
    executor._workers[record.workflow_id] = threading.current_thread()
    output = config.workflow_dir(record.workflow_id) / "outputs" / "retained.txt"
    output.write_text("retained synthetic output", encoding="utf-8")
    yield executor, store, worker, record, output
    store.close()


def assert_clean(execution, status, code=None, persisted=True):
    executor, store, worker, record, output = execution
    assert record.status == status
    assert record.finished_at
    assert worker.released == [record.workflow_id]
    assert record.workflow_id not in executor._workers
    assert output.read_text(encoding="utf-8") == "retained synthetic output"
    assert executor.qgis_gate.acquire(timeout=0)
    executor.qgis_gate.release()
    terminal = [event.to_dict() for event in executor.bus.history(record.workflow_id)
                if event.type in {"workflow_success", "workflow_error"}]
    assert len(terminal) == 1
    assert terminal[0]["type"] == ("workflow_success" if status == "success" else "workflow_error")
    assert terminal[0]["payload"]["workflow"]["status"] == status
    if code:
        assert record.error["code"] == code
        assert terminal[0]["payload"]["error"]["code"] == code
    if persisted:
        reader = RuntimeStore(store.state_file, read_only=True)
        assert reader.get_workflow(record.workflow_id).status == status
        disk = json.loads((output.parent.parent / "status.json").read_text(encoding="utf-8"))
        assert disk["status"] == status


@pytest.mark.parametrize("outcome", ["raise", "none", "list"])
def test_unexpected_worker_failure_terminates_and_releases(execution, outcome):
    executor, store, worker, record, output = execution
    worker.outcome = outcome
    executor._run_workflow(record.workflow_id)
    assert worker.steps == ["s1"]
    assert record.steps[0]["status"] == "error"
    assert record.steps[0]["finished_at"]
    step_errors = [event.to_dict() for event in executor.bus.history(record.workflow_id)
                   if event.type == "step_error"]
    assert len(step_errors) == 1
    assert step_errors[0]["payload"]["step"]["id"] == "s1"
    assert step_errors[0]["payload"]["step"]["status"] == "error"
    assert step_errors[0]["payload"]["error"]["code"] == "INTERNAL_ERROR"
    assert_clean(execution, "error", "INTERNAL_ERROR")


@pytest.mark.parametrize("phase", ["start_save", "step_save", "ordering", "artifact", "event", "terminal_save", "terminal_files"])
def test_failure_at_each_execution_phase_has_terminal_cleanup(execution, phase):
    executor, store, worker, record, output = execution
    if phase in {"start_save", "step_save", "terminal_save"}:
        original = store.save_workflow
        calls = 0
        def failing_save(value):
            nonlocal calls
            calls += 1
            trigger = value.status == "success" if phase == "terminal_save" else calls == (1 if phase == "start_save" else 3)
            if trigger:
                raise OSError("synthetic persistence failure")
            return original(value)
        target = patch.object(store, "save_workflow", side_effect=failing_save)
    elif phase == "ordering":
        target = patch.object(executor, "_topological_order", side_effect=ValueError("synthetic ordering failure"))
    elif phase == "artifact":
        target = patch.object(executor, "_register_artifacts", side_effect=RuntimeError("synthetic artifact failure"))
    elif phase == "event":
        original = executor.bus.publish
        def failing_event(workflow_id, event):
            if event.type == "workflow_started":
                raise RuntimeError("synthetic event failure")
            return original(workflow_id, event)
        target = patch.object(executor.bus, "publish", side_effect=failing_event)
    else:
        original = executor._write_workflow_files
        def failing_files(value):
            if value.status == "success":
                raise OSError("synthetic workflow-file failure")
            return original(value)
        target = patch.object(executor, "_write_workflow_files", side_effect=failing_files)
    with target:
        executor._run_workflow(record.workflow_id)
    assert_clean(execution, "error", "INTERNAL_ERROR")


@pytest.mark.parametrize("outcome", ["error", "cancelled"])
def test_known_terminal_error_retained_if_workflow_file_write_fails(execution, outcome):
    executor, store, worker, record, output = execution
    worker.outcome = outcome
    original = executor._write_workflow_files
    calls = 0
    def fail_once(value):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("synthetic terminal-file failure")
        return original(value)
    with patch.object(executor, "_write_workflow_files", side_effect=fail_once):
        executor._run_workflow(record.workflow_id)
    assert_clean(execution, outcome, "STEP_CANCELLED" if outcome == "cancelled" else "PROCESSING_FAILED")


def test_persistent_io_failure_still_publishes_and_releases(execution):
    executor, store, worker, record, output = execution
    before = store.state_file.read_bytes()
    with patch.object(store, "save_workflow", side_effect=OSError("synthetic full disk")):
        with patch.object(executor, "_write_workflow_files", side_effect=OSError("synthetic full disk")):
            executor._run_workflow(record.workflow_id)
    assert_clean(execution, "error", "INTERNAL_ERROR", persisted=False)
    assert store.state_file.read_bytes() == before
    reader = RuntimeStore(store.state_file, read_only=True)
    assert reader.get_workflow(record.workflow_id).status == "pending"


def test_worker_release_failure_does_not_erase_success_or_thread_cleanup(execution):
    executor, store, worker, record, output = execution
    worker.release_fails = True
    executor._run_workflow(record.workflow_id)
    assert_clean(execution, "success")


def test_missing_record_still_releases_thread_reference(execution):
    executor, store, worker, record, output = execution
    with patch.object(store, "get_workflow", return_value=None):
        executor._run_workflow(record.workflow_id)
    assert worker.released == [record.workflow_id]
    assert record.workflow_id not in executor._workers
    assert not executor.bus.history(record.workflow_id)


def test_store_lookup_failure_publishes_error_and_releases(execution):
    executor, store, worker, record, output = execution
    with patch.object(store, "get_workflow", side_effect=OSError("synthetic lookup failure")):
        executor._run_workflow(record.workflow_id)
    assert worker.released == [record.workflow_id]
    assert record.workflow_id not in executor._workers
    terminal = executor.bus.history(record.workflow_id)[-1].to_dict()
    assert terminal["type"] == "workflow_error"
    assert terminal["payload"]["workflow_id"] == record.workflow_id


def test_thread_start_failure_returns_terminal_record_and_cleans_reference(execution):
    executor, store, worker, old_record, output = execution
    record = WorkflowRecord.create(project_id="synthetic", workflow_json={"steps": []})
    with patch.object(threading.Thread, "start", side_effect=RuntimeError("synthetic thread start failure")):
        returned, _ = executor.submit(record, validate=False)
    assert returned is record
    assert record.status == "error"
    assert record.error["code"] == "INTERNAL_ERROR"
    assert record.workflow_id not in executor._workers
    assert worker.released == [record.workflow_id]
    assert RuntimeStore(store.state_file, read_only=True).get_workflow(record.workflow_id).status == "error"
    assert executor.bus.history(record.workflow_id)[-1].type == "workflow_error"


@pytest.mark.parametrize("phase", ["initial_save", "initial_files", "created_event", "thread_construct"])
def test_preparation_failure_never_leaves_a_registered_pending_execution(execution, phase):
    executor, store, worker, record, output = execution
    executor._workers.pop(record.workflow_id)  # No execution thread exists yet.
    if phase == "initial_save":
        original = store._write_state_file
        calls = 0
        def failing_initial_write():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("synthetic initial persistence failure")
            return original()
        target = patch.object(store, "_write_state_file", side_effect=failing_initial_write)
    elif phase == "initial_files":
        original = executor._write_workflow_files
        calls = 0
        def fail_once(value):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("synthetic initial file failure")
            return original(value)
        target = patch.object(executor, "_write_workflow_files", side_effect=fail_once)
    elif phase == "created_event":
        original = executor.bus.publish
        def fail_created(workflow_id, event):
            if event.type == "workflow_created":
                raise RuntimeError("synthetic creation event failure")
            return original(workflow_id, event)
        target = patch.object(executor.bus, "publish", side_effect=fail_created)
    else:
        target = patch.object(threading, "Thread", side_effect=RuntimeError("synthetic thread constructor failure"))
    with target:
        returned, _ = executor.submit(record, validate=False)
    assert returned is record
    assert worker.steps == []
    assert_clean(execution, "error", "INTERNAL_ERROR")


def test_real_execution_thread_releases_its_reference(execution):
    executor, store, worker, old_record, output = execution
    entered = threading.Event()
    finish = threading.Event()
    original = worker.run_step
    def blocking_step(workflow_id, step):
        entered.set()
        assert finish.wait(timeout=5)
        return original(workflow_id, step)
    record = WorkflowRecord.create(project_id="synthetic", workflow_json={
        "steps": [{"id": "s1", "op": "load_layer", "params": {}}],
    })
    with patch.object(worker, "run_step", side_effect=blocking_step):
        executor.submit(record, validate=False)
        assert entered.wait(timeout=5)
        thread = executor._workers[record.workflow_id]
        finish.set()
        thread.join(timeout=5)
    assert not thread.is_alive()
    assert record.status == "success"
    assert record.workflow_id not in executor._workers
    assert worker.released == [record.workflow_id]
