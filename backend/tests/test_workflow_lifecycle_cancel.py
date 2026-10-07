"""Deterministic cancellation boundaries with synthetic data and no providers."""
import queue
import threading
import time
from unittest.mock import patch

import pytest

from backend.app.config import AppConfig
from backend.app.models import WorkflowRecord
from backend.app.services.pyqgis_worker import PyQgisWorkerManager
from backend.app.services.request_limits import AdmissionGate
from backend.app.services.workflow_executor import WorkflowExecutor
from backend.app.store import RuntimeStore


class Worker:
    def __init__(self):
        self.calls = []
        self.released = []
        self.cancelled = []
        self.hook = lambda workflow_id, step, cancel_event: {"status": "success", "outputs": {}}

    def run_step(self, workflow_id, step, cancel_event=None):
        self.calls.append((workflow_id, step["id"]))
        return self.hook(workflow_id, step, cancel_event)

    def cancel_workflow(self, workflow_id):
        self.cancelled.append(workflow_id)
        return 0

    def release_workflow(self, workflow_id):
        self.released.append(workflow_id)


@pytest.fixture
def execution(tmp_path):
    config = AppConfig(root_dir=tmp_path)
    config.workflow_queue_max = 1
    config.workflow_queue_timeout_seconds = 30
    config.ensure_dirs()
    store = RuntimeStore(config.state_file)
    worker = Worker()
    executor = WorkflowExecutor(config, store, worker_manager=worker)
    yield executor, store, worker
    store.close()


def seed(execution, *, skip=False):
    executor, store, worker = execution
    record = WorkflowRecord.create(project_id="synthetic", workflow_json={"steps": [
        {"id": "s1", "op": "load_layer", "params": {}, "on_error": "skip" if skip else "abort"},
        {"id": "s2", "op": "export_geojson", "params": {}, "depends_on": ["s1"]},
    ]})
    store.create_workflow(record)
    executor._workers[record.workflow_id] = threading.current_thread()
    executor._cancel_events[record.workflow_id] = threading.Event()
    return record


def cancelled(execution, record):
    executor, store, worker = execution
    assert record.status == "cancelled"
    assert record.error["code"] == "STEP_CANCELLED"
    assert record.finished_at
    assert record.workflow_id not in executor._workers
    assert record.workflow_id not in executor._cancel_events
    assert worker.released.count(record.workflow_id) == 1
    events = executor.bus.history(record.workflow_id)
    terminal = [event for event in events if event.type in {"workflow_success", "workflow_error"}]
    assert len(terminal) == 1 and terminal[0].type == "workflow_error"
    assert terminal[0].payload["workflow"]["status"] == "cancelled"
    reader = RuntimeStore(store.state_file, read_only=True)
    assert reader.get_workflow(record.workflow_id).status == "cancelled"
    assert executor.cancel_workflow(record.workflow_id) == 0


def wait_until(predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert predicate()


def test_cancel_before_execution_dispatches_nothing(execution):
    executor, store, worker = execution
    record = seed(execution)
    assert executor.cancel_workflow(record.workflow_id) == 1
    assert executor.cancel_workflow(record.workflow_id) == 0
    executor._run_workflow(record.workflow_id)
    assert not worker.calls
    cancelled(execution, record)


def test_cancel_during_submit_creation_is_not_lost(execution):
    executor, store, worker = execution
    record = WorkflowRecord.create(project_id="synthetic", workflow_json={"steps": []})
    publish = executor.bus.publish
    threads = []
    constructor = threading.Thread
    def make_thread(*args, **kwargs):
        thread = constructor(*args, **kwargs)
        threads.append(thread)
        return thread
    def created(workflow_id, event):
        publish(workflow_id, event)
        if event.type == "workflow_created":
            assert executor.cancel_workflow(workflow_id) == 1
    with patch.object(executor.bus, "publish", side_effect=created), patch.object(threading, "Thread", side_effect=make_thread):
        executor.submit(record, validate=False)
        threads[0].join(5)
    assert not threads[0].is_alive() and not worker.calls
    cancelled(execution, record)


def test_cancel_while_gate_is_occupied_returns_promptly_without_releasing_other_slot(execution):
    executor, store, worker = execution
    record = seed(execution)
    assert executor.qgis_gate.acquire(timeout=0)
    thread = threading.Thread(target=executor._run_workflow, args=(record.workflow_id,))
    executor._workers[record.workflow_id] = thread
    thread.start()
    try:
        wait_until(lambda: executor.qgis_gate.waiting == 1)
        assert executor.cancel_workflow(record.workflow_id) == 1
        thread.join(2)
        assert not thread.is_alive()
        assert not worker.calls and executor.qgis_gate.waiting == 0
        assert not executor.qgis_gate.acquire(timeout=0)
        cancelled(execution, record)
    finally:
        executor.qgis_gate.release()
        thread.join(5)


@pytest.mark.parametrize("skip", [False, True])
@pytest.mark.parametrize("outcome", ["late_success", "raise"])
def test_accepted_cancel_discards_late_result_and_never_starts_next_step(execution, skip, outcome):
    executor, store, worker = execution
    record = seed(execution, skip=skip)
    path = executor.config.workflow_dir(record.workflow_id) / "outputs" / "late.geojson"
    def finish_late(workflow_id, step, cancel_event):
        assert executor.cancel_workflow(workflow_id) == 1
        assert cancel_event.is_set()
        path.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
        if outcome == "raise":
            raise RuntimeError("synthetic exception after cancellation")
        return {"status": "success", "outputs": {"geojson": str(path)}}
    worker.hook = finish_late
    executor._run_workflow(record.workflow_id)
    assert [step for _, step in worker.calls] == ["s1"]
    assert path.exists() and not record.artifacts
    assert not any(event.type == "artifact_ready" for event in executor.bus.history(record.workflow_id))
    assert record.steps[0]["status"] == "error"
    assert record.steps[1]["status"] == "pending"
    assert executor.qgis_gate.acquire(timeout=0)
    executor.qgis_gate.release()
    cancelled(execution, record)


@pytest.mark.parametrize("phase", ["between_steps", "before_summary"])
def test_cancel_between_completed_work_and_next_operation_retains_completed_artifact(execution, phase):
    executor, store, worker = execution
    record = seed(execution)
    summaries = []
    executor.summary_callback = lambda *args: summaries.append(True) or "summary"
    path = executor.config.workflow_dir(record.workflow_id) / "outputs" / "completed.geojson"
    path.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
    worker.hook = lambda *_: {"status": "success", "outputs": {"geojson": str(path)}}
    publish = executor.bus.publish
    def after_step(workflow_id, event):
        publish(workflow_id, event)
        expected = "s1" if phase == "between_steps" else "s2"
        if event.type == "step_success" and event.payload["step"]["id"] == expected:
            assert executor.cancel_workflow(workflow_id) == 1
    with patch.object(executor.bus, "publish", side_effect=after_step):
        executor._run_workflow(record.workflow_id)
    assert len(worker.calls) == (1 if phase == "between_steps" else 2)
    assert not summaries and record.artifacts and path.exists()
    assert record.steps[0]["status"] == "success"
    cancelled(execution, record)


@pytest.mark.parametrize("summary_raises", [False, True])
def test_cancel_during_summary_overrides_provisional_success_and_drops_late_summary(execution, summary_raises):
    executor, store, worker = execution
    record = seed(execution)
    entered, finish = threading.Event(), threading.Event()
    def summary(summary_record, outputs):
        assert summary_record.status == "success" and summary_record is not record
        entered.set()
        assert finish.wait(5)
        if summary_raises:
            raise RuntimeError("synthetic summary failure")
        return "late summary"
    executor.summary_callback = summary
    thread = threading.Thread(target=executor._run_workflow, args=(record.workflow_id,))
    executor._workers[record.workflow_id] = thread
    thread.start()
    try:
        assert entered.wait(5)
        assert store.get_workflow(record.workflow_id).status == "running"
        assert not record.finished_at
        assert executor.cancel_workflow(record.workflow_id) == 1
    finally:
        finish.set()
        thread.join(5)
    assert not thread.is_alive()
    assert not (executor.config.workflow_dir(record.workflow_id) / "outputs" / "summary.md").exists()
    assert not any(artifact["kind"] == "summary" for artifact in record.artifacts)
    cancelled(execution, record)


def test_summary_keeps_queries_nonterminal_until_success_is_committed(execution):
    executor, store, worker = execution
    record = seed(execution)
    entered, finish = threading.Event(), threading.Event()
    def summary(summary_record, outputs):
        assert summary_record.status == "success" and summary_record.finished_at
        entered.set()
        assert finish.wait(5)
        return "completed summary"
    executor.summary_callback = summary
    thread = threading.Thread(target=executor._run_workflow, args=(record.workflow_id,))
    executor._workers[record.workflow_id] = thread
    thread.start()
    try:
        assert entered.wait(5)
        assert store.get_workflow(record.workflow_id).status == "running"
        assert not record.finished_at
        reader = RuntimeStore(store.state_file, read_only=True)
        assert reader.get_workflow(record.workflow_id).status == "running"
        assert not any(event.type == "workflow_success" for event in executor.bus.history(record.workflow_id))
    finally:
        finish.set()
        thread.join(5)
    assert not thread.is_alive() and record.status == "success" and record.finished_at
    assert record.workflow_id not in executor._workers and record.workflow_id not in executor._cancel_events
    assert any(artifact["kind"] == "summary" for artifact in record.artifacts)
    assert executor.cancel_workflow(record.workflow_id) == 0


def test_terminal_commit_wins_race_and_cancel_does_not_reopen_success(execution):
    executor, store, worker = execution
    record = seed(execution)
    entered, finish, attempted = threading.Event(), threading.Event(), threading.Event()
    outcomes = []
    save = store.save_workflow
    def terminal_save(value):
        if value.status == "success":
            entered.set()
            assert finish.wait(5)
        return save(value)
    def cancel():
        attempted.set()
        outcomes.append(executor.cancel_workflow(record.workflow_id))
    thread = threading.Thread(target=executor._run_workflow, args=(record.workflow_id,))
    executor._workers[record.workflow_id] = thread
    canceller = threading.Thread(target=cancel)
    with patch.object(store, "save_workflow", side_effect=terminal_save):
        thread.start()
        try:
            assert entered.wait(5)
            canceller.start()
            assert attempted.wait(5)
        finally:
            finish.set()
            thread.join(5)
            if canceller.ident is not None:
                canceller.join(5)
    assert not thread.is_alive() and not canceller.is_alive()
    assert outcomes == [0] and record.status == "success"
    assert record.workflow_id not in executor._cancel_events


def test_cancel_is_scoped_to_one_workflow(execution):
    executor, store, worker = execution
    first, second = seed(execution), seed(execution)
    executor.cancel_workflow(first.workflow_id)
    executor._run_workflow(first.workflow_id)
    executor._run_workflow(second.workflow_id)
    cancelled(execution, first)
    assert second.status == "success"
    assert all(workflow_id == second.workflow_id for workflow_id, _ in worker.calls)


def test_gate_precancel_and_acquisition_race_do_not_leak_capacity():
    gate, event = AdmissionGate(1, timeout=30), threading.Event()
    event.set()
    assert not gate.acquire(cancel_event=event)
    event.clear()
    acquire = gate._semaphore.acquire
    def acquired_then_cancelled(**kwargs):
        value = acquire(**kwargs)
        event.set()
        return value
    with patch.object(gate._semaphore, "acquire", side_effect=acquired_then_cancelled):
        assert not gate.acquire(cancel_event=event)
    assert gate.waiting == 0 and gate.acquire(timeout=0)
    gate.release()


def test_cancel_after_gate_admission_does_not_dispatch_and_releases_slot(execution):
    executor, store, worker = execution
    record = seed(execution)
    acquire = executor.qgis_gate.acquire
    def admitted_then_cancelled(**kwargs):
        value = acquire(**kwargs)
        assert value and executor.cancel_workflow(record.workflow_id) == 1
        return value
    with patch.object(executor.qgis_gate, "acquire", side_effect=admitted_then_cancelled):
        executor._run_workflow(record.workflow_id)
    assert not worker.calls and executor.qgis_gate.acquire(timeout=0)
    executor.qgis_gate.release()
    cancelled(execution, record)


@pytest.mark.parametrize("phase", ["lifecycle_lock", "shared_startup"])
def test_manager_cancel_while_startup_waits_does_not_stop_shared_worker(tmp_path, phase):
    manager, event = PyQgisWorkerManager(tmp_path, startup_timeout=30), threading.Event()
    entered, finish = threading.Event(), threading.Event()
    results = []
    class SharedProcess:
        def is_alive(self):
            return True
    manager._process = SharedProcess()
    manager._input_queue = queue.Queue()
    def holder():
        with manager._lifecycle_lock:
            entered.set()
            assert finish.wait(5)
    holder_thread = threading.Thread(target=holder)
    if phase == "lifecycle_lock":
        holder_thread.start()
        assert entered.wait(5)
    original_wait = manager._wait_ready
    def wait_ready(cancel_event=None):
        entered.set()
        return original_wait(cancel_event)
    with patch.object(manager, "_ensure_dispatcher_locked"), patch.object(manager, "_wait_ready", side_effect=wait_ready), patch.object(manager, "_start_worker_locked") as spawn:
        thread = threading.Thread(target=lambda: results.append(manager.run_step("wf", {"id": "s1"}, cancel_event=event)))
        thread.start()
        try:
            assert entered.wait(5)
            event.set()
            thread.join(2)
            assert not thread.is_alive()
        finally:
            finish.set()
            thread.join(5)
            if holder_thread.ident is not None:
                holder_thread.join(5)
    assert results[0]["error"]["code"] == "STEP_CANCELLED"
    assert not spawn.called and manager._process.is_alive()
    assert not manager._restart_needed and manager._input_queue.empty() and not manager._pending


@pytest.mark.parametrize("phase", ["before_start", "during_start", "before_enqueue"])
def test_manager_cancel_before_dispatch_has_no_worker_request(tmp_path, phase):
    manager = PyQgisWorkerManager(tmp_path)
    event = threading.Event()
    manager._input_queue = queue.Queue()
    if phase == "before_start":
        event.set()
    def startup(cancel_event=None):
        if phase == "during_start":
            event.set()
    class Id:
        @property
        def hex(self):
            event.set()
            return "synthetic-request"
    with patch.object(manager, "ensure_started", side_effect=startup) as started, patch(
        "backend.app.services.pyqgis_worker.worker_manager.uuid.uuid4", return_value=Id()
    ):
        result = manager.run_step("wf", {"id": "s1"}, cancel_event=event)
    assert result["error"]["code"] == "STEP_CANCELLED"
    assert started.call_count == (0 if phase == "before_start" else 1)
    assert manager._input_queue.empty() and not manager._pending


def test_manager_cancel_after_crash_suppresses_auto_retry(tmp_path):
    manager, event = PyQgisWorkerManager(tmp_path), threading.Event()
    def crash(*args):
        event.set()
        return {"status": "error", "error": {"code": "WORKER_CRASHED"}}, {"failure": "crash"}
    with patch.object(manager, "_dispatch_once", side_effect=crash) as dispatch:
        result = manager.run_step("wf", {"id": "s1", "params": {}}, cancel_event=event)
    assert dispatch.call_count == 1 and manager.stats["auto_retries"] == 0
    assert result["error"]["code"] == "STEP_CANCELLED" and result["attempt"] == 1


def test_manager_cancel_during_wait_orphans_late_reply(tmp_path):
    manager, event = PyQgisWorkerManager(tmp_path), threading.Event()
    manager._input_queue, manager._cancel_queue = queue.Queue(), queue.Queue()
    results = []
    with patch.object(manager, "ensure_started"):
        thread = threading.Thread(target=lambda: results.append(manager.run_step("wf", {"id": "s1"}, cancel_event=event)))
        thread.start()
        try:
            request = manager._input_queue.get(timeout=5)
            event.set()
            assert manager.cancel_workflow("wf") == 1
        finally:
            thread.join(5)
    assert not thread.is_alive() and not manager._pending
    assert results[0]["error"]["code"] == "STEP_CANCELLED"
    manager._route(dict(request, type="step_result", status="success", outputs={}))
    assert manager.stats["late_messages_dropped"] == 1
