"""SSE recovery/commit races use synthetic snapshots and a stub worker."""
import queue
import threading
from unittest.mock import Mock, patch

import pytest

from backend.app.config import AppConfig
from backend.app.models import WorkflowRecord
from backend.app.runtime import WebGISRuntime
from backend.app.services.workflow_executor import WorkflowExecutor, _Event
from backend.app.store import RuntimeStore


@pytest.fixture
def execution(tmp_path):
    config = AppConfig(root_dir=tmp_path)
    config.data_dir = tmp_path / "data"
    config.state_dir = config.data_dir / "state"
    config.state_file = config.state_dir / "runtime.json"
    config.uploads_dir = config.data_dir / "uploads"
    config.outputs_dir = config.data_dir / "outputs"
    config.workflows_dir = config.data_dir / "workflows"
    config.ensure_dirs()
    store = RuntimeStore(config.state_file)
    worker = Mock()
    executor = WorkflowExecutor(config, store, worker_manager=worker)
    record = WorkflowRecord.create("synthetic", workflow_json={"steps": []})
    record.status = "running"
    store.create_workflow(record)
    runtime = object.__new__(WebGISRuntime)
    runtime.store, runtime.workflow_executor = store, executor
    yield executor, store, record, runtime, worker
    store.close()


@pytest.mark.parametrize("status", ["success", "error", "cancelled"])
def test_persisted_terminal_without_history_returns_full_record_and_unsubscribes(execution, status):
    executor, store, record, _, worker = execution
    record.status = status
    record.steps = [{"id": "retained", "status": "success", "outputs": {"value": 42}}]
    record.artifacts = [{"artifact_id": "retained", "public_url": "/retained.geojson"}]
    record.error = {"code": "STEP_CANCELLED" if status == "cancelled" else "INTERNAL_ERROR"}
    store.save_workflow(record)
    assert executor.bus.history(record.workflow_id) == []
    with patch.object(executor.bus, "unsubscribe", wraps=executor.bus.unsubscribe) as unsubscribe:
        events = list(executor.stream(record.workflow_id))
    assert len(events) == 1
    assert events[0]["type"] == ("workflow_success" if status == "success" else "workflow_error")
    assert events[0]["payload"]["workflow"] == record.to_dict()
    assert events[0]["payload"].get("artifacts", record.artifacts) == record.artifacts
    unsubscribe.assert_called_once()
    worker.run_step.assert_not_called()
    worker.ensure_started.assert_not_called()


def test_unknown_workflow_does_not_subscribe_or_execute(execution):
    executor, _, _, runtime, worker = execution
    with patch.object(executor.bus, "subscribe") as subscribe:
        events = list(executor.stream("missing"))
    assert events[0]["type"] == "workflow_error"
    assert events[0]["payload"]["workflow_id"] == "missing"
    subscribe.assert_not_called()
    with pytest.raises(KeyError):
        runtime.get_workflow("missing")
    worker.run_step.assert_not_called()


def test_terminal_commit_between_lookup_and_subscription_is_not_lost(execution):
    executor, store, record, *_ = execution
    subscribe = executor.bus.subscribe

    def complete_before_subscribing(workflow_id):
        record.status = "success"
        store.save_workflow(record)
        return subscribe(workflow_id)

    with patch.object(executor.bus, "subscribe", side_effect=complete_before_subscribing):
        assert list(executor.stream(record.workflow_id))[0]["payload"]["workflow"]["status"] == "success"


def test_empty_queue_reconciles_terminal_even_when_event_publication_was_lost(execution):
    executor, store, record, *_ = execution
    events = Mock()

    def complete_without_event(**_kwargs):
        record.status = "cancelled"
        store.save_workflow(record)
        raise queue.Empty

    events.get.side_effect = complete_without_event
    with patch.object(executor.bus, "subscribe", return_value=events):
        recovered = list(executor.stream(record.workflow_id, idle_timeout=0))
    assert recovered[0]["payload"]["workflow"]["status"] == "cancelled"
    assert len(recovered) == 1


def test_transport_idle_does_not_change_or_restart_running_workflow(execution):
    executor, store, record, _, worker = execution
    before = store.state_file.read_bytes()
    events = Mock()
    events.get.side_effect = queue.Empty
    with patch.object(executor.bus, "subscribe", return_value=events), \
            patch("backend.app.services.workflow_executor.time.monotonic", side_effect=[0, 2]):
        recovered = list(executor.stream(record.workflow_id, idle_timeout=1))
    assert [event["type"] for event in recovered] == ["stream_idle_timeout"]
    assert record.status == "running"
    assert store.state_file.read_bytes() == before
    worker.run_step.assert_not_called()


def test_client_close_releases_subscription(execution):
    executor, _, record, *_ = execution
    executor.bus.publish(record.workflow_id, _Event("workflow_started", {"workflow_id": record.workflow_id}))
    with patch.object(executor.bus, "unsubscribe", wraps=executor.bus.unsubscribe) as unsubscribe:
        stream = executor.stream(record.workflow_id)
        assert next(stream)["type"] == "workflow_started"
        stream.close()
    unsubscribe.assert_called_once()


def test_existing_live_history_still_replays_in_order(execution):
    executor, _, record, *_ = execution
    executor.bus.publish(record.workflow_id, _Event("step_started", {"step": {"id": "s1"}}))
    executor.bus.publish(record.workflow_id, _Event("workflow_success", {"workflow": {"status": "success"}}))
    assert [event["type"] for event in executor.stream(record.workflow_id)] == ["step_started", "workflow_success"]


@pytest.mark.parametrize("fail_commit", [False, True])
def test_public_query_waits_for_actual_terminal_commit(execution, fail_commit):
    executor, store, record, runtime, _ = execution
    entered, release, querying, returned = (threading.Event() for _ in range(4))
    result = []
    update = store.save_workflow

    def blocked_commit(next_record):
        if next_record.status == "success":
            entered.set()
            assert release.wait(5)
            if fail_commit:
                raise OSError("synthetic terminal commit failure")
        return update(next_record)

    def read_public_query():
        querying.set()
        result.append(runtime.get_workflow(record.workflow_id))
        returned.set()

    writer = threading.Thread(target=executor._run_workflow, args=(record.workflow_id,))
    reader = threading.Thread(target=read_public_query)
    with patch.object(store, "save_workflow", side_effect=blocked_commit):
        try:
            writer.start()
            assert entered.wait(5)
            reader.start()
            assert querying.wait(5)
            assert not returned.wait(0.05)
        finally:
            release.set()
            writer.join(5)
            if reader.ident is not None:
                reader.join(5)
    assert not writer.is_alive() and not reader.is_alive()
    if fail_commit:
        assert result[0]["status"] in {"running", "error"}
        if result[0]["status"] == "running":
            assert not result[0]["finished_at"]
    else:
        assert result[0]["status"] == "success"
        assert result[0]["finished_at"]
    reader_store = RuntimeStore(store.state_file, read_only=True)
    try:
        assert reader_store.get_workflow(record.workflow_id).status == ("error" if fail_commit else "success")
    finally:
        reader_store.close()
