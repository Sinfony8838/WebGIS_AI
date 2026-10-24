"""Bounded background admission/replay using synthetic stores and blocked stubs."""
import threading
import time
from unittest.mock import Mock, patch

import pytest

from backend.app.config import AppConfig
from backend.app.models import WorkflowRecord
from backend.app.services.background_tasks import BackgroundBusy, BoundedTaskPool
from backend.app.services.classroom_workflow import ClassroomWorkflowRuntime
from backend.app.services.workflow_executor import WorkflowExecutor, _Event, _EventBus
from backend.app.store import RuntimeStore


def eventually(predicate):
    deadline = time.monotonic() + 3
    while not predicate() and time.monotonic() < deadline:
        threading.Event().wait(0.005)
    assert predicate()


def test_pool_bounds_running_queue_and_reserved_capacity():
    pool = BoundedTaskPool(max_workers=2, max_queued=2)
    started = [threading.Event(), threading.Event()]
    release = threading.Event()
    queued = Mock()

    def block(index):
        started[index].set()
        assert release.wait(5)

    try:
        for index in range(2):
            with pool.reserve() as token:
                token.submit(block, index)
        assert all(event.wait(2) for event in started)
        with pool.reserve() as token:
            token.submit(queued)
        held = pool.reserve()
        assert pool.outstanding == 4 and pool.queued == 1
        with pytest.raises(BackgroundBusy):
            pool.reserve()
        held.release()
        with pool.reserve() as token:
            token.submit(queued)
        assert pool.queued == 2 and len(pool._threads) == 2
        queued.assert_not_called()
    finally:
        release.set()
        pool.shutdown()
    assert queued.call_count == 2 and pool.outstanding == 0
    assert not pool._threads and pool._monitor is None


def test_queue_expires_on_wall_clock_while_all_workers_stay_blocked():
    pool = BoundedTaskPool(max_workers=1, max_queued=1, queue_timeout=0.08)
    entered, release, expired = (threading.Event() for _ in range(3))
    work = Mock()

    def block():
        entered.set()
        assert release.wait(5)

    try:
        with pool.reserve() as token:
            token.submit(block)
        assert entered.wait(2)
        with pool.reserve() as token:
            token.submit(work, on_expire=expired.set)
        with pytest.raises(BackgroundBusy):
            pool.reserve()
        assert expired.wait(2)
        eventually(lambda: pool.outstanding == 1)
        assert pool.queued == 0 and not release.is_set()
        with pool.reserve():
            assert pool.outstanding == 2
        work.assert_not_called()
    finally:
        release.set()
        pool.shutdown()
    assert pool.outstanding == 0


def test_queue_cancel_holds_capacity_until_cleanup_and_shutdown_waits():
    pool = BoundedTaskPool(max_workers=1, max_queued=1)
    entered, release, cleaning, finish_cleanup, stopped = (threading.Event() for _ in range(5))
    work = Mock()

    def block():
        entered.set()
        assert release.wait(5)

    def cleanup():
        cleaning.set()
        assert finish_cleanup.wait(5)

    def shutdown():
        pool.shutdown()
        stopped.set()

    with pool.reserve() as token:
        token.submit(block)
    assert entered.wait(2)
    queued = pool.reserve()
    queued.submit(work)
    canceller = threading.Thread(target=lambda: queued.cancel(cleanup))
    closer = threading.Thread(target=shutdown)
    try:
        canceller.start()
        assert cleaning.wait(2)
        assert pool.outstanding == 2 and pool.queued == 0
        with pytest.raises(BackgroundBusy):
            pool.reserve()
        assert not queued.cancel(Mock())
        closer.start()
        release.set()
        assert not stopped.wait(0.05)
    finally:
        release.set()
        finish_cleanup.set()
        canceller.join(5)
        closer.join(5)
        pool.shutdown()
    assert stopped.is_set() and pool.outstanding == 0
    work.assert_not_called()


def test_shutdown_revokes_unused_tokens_and_startup_never_revives_them():
    pool = BoundedTaskPool(max_workers=1, max_queued=0)
    token = pool.reserve()
    pool.shutdown()
    assert pool.outstanding == 0
    with pytest.raises(BackgroundBusy):
        token.submit(Mock())
    with pytest.raises(BackgroundBusy):
        pool.reserve()
    pool.startup()
    with pytest.raises(ValueError):
        token.submit(Mock())
    completed = threading.Event()
    with pool.reserve() as fresh:
        fresh.submit(completed.set)
    assert completed.wait(2)
    pool.shutdown()


def test_preparation_fences_persistence_and_enqueue_against_shutdown():
    pool = BoundedTaskPool(max_workers=1, max_queued=0)
    entered, release, attempted, finished = (threading.Event() for _ in range(4))
    work = Mock()
    token = pool.reserve()

    def prepare():
        with token, pool.preparing(token):
            entered.set()
            assert release.wait(5)
            token.submit(work)

    def shutdown():
        attempted.set()
        pool.shutdown()
        finished.set()

    submitter = threading.Thread(target=prepare)
    closer = threading.Thread(target=shutdown)
    submitter.start()
    try:
        assert entered.wait(2)
        closer.start()
        assert attempted.wait(2) and not finished.wait(0.05)
    finally:
        release.set()
        submitter.join(5)
        closer.join(5)
    assert finished.is_set() and pool.outstanding == 0
    work.assert_called_once()


def test_preparation_does_not_block_other_admission_or_queue_expiry():
    pool = BoundedTaskPool(max_workers=1, max_queued=2, queue_timeout=0.08)
    running, release, prepared, finish_preparing, expired = (threading.Event() for _ in range(5))
    work = Mock()

    def block():
        running.set()
        assert release.wait(5)

    def prepare():
        with pool.reserve() as token, pool.preparing(token):
            prepared.set()
            assert finish_preparing.wait(5)
            token.submit(work)

    with pool.reserve() as token:
        token.submit(block)
    assert running.wait(2)
    with pool.reserve() as token:
        token.submit(work, on_expire=expired.set)
    submitter = threading.Thread(target=prepare)
    try:
        submitter.start()
        assert prepared.wait(2)
        assert expired.wait(2)
        eventually(lambda: pool.outstanding == 2)
        # Slow persistence must not own the queue lock or prevent rejection.
        with pool.reserve():
            with pytest.raises(BackgroundBusy):
                pool.reserve()
        pool.shutdown(wait=False)
        with pytest.raises(BackgroundBusy):
            pool.reserve()
        with pytest.raises(RuntimeError):
            pool.startup()
    finally:
        release.set()
        finish_preparing.set()
        submitter.join(5)
        pool.shutdown()
    assert not submitter.is_alive() and pool.outstanding == 0
    work.assert_called_once()


def test_failed_preparation_releases_token_and_cannot_be_reused():
    pool = BoundedTaskPool(max_workers=1, max_queued=0)
    token = pool.reserve()
    with pytest.raises(OSError):
        with token, pool.preparing(token):
            raise OSError("synthetic persistence failure")
    assert pool.outstanding == 0
    with pytest.raises(ValueError):
        token.submit(Mock())
    pool.shutdown()


@pytest.fixture
def execution(tmp_path):
    config = AppConfig(root_dir=tmp_path)
    config.workflow_max_running = 1
    config.workflow_queue_max = 1
    config.workflow_queue_timeout_seconds = 30
    config.ensure_dirs()
    store = RuntimeStore(config.state_file)
    worker = Mock()
    worker.cancel_workflow.return_value = 0
    worker.run_step.return_value = {"status": "success", "outputs": {}}
    executor = WorkflowExecutor(config, store, worker_manager=worker)
    yield executor, store, worker
    executor.shutdown()
    store.close()


def workflow():
    return WorkflowRecord.create("synthetic", workflow_json={"steps": [
        {"id": "s1", "op": "load_layer", "params": {}},
        {"id": "s2", "op": "export_geojson", "params": {}, "depends_on": ["s1"]},
    ]})


def block_worker(worker):
    entered, release = threading.Event(), threading.Event()

    def run(*_args, **_kwargs):
        entered.set()
        assert release.wait(5)
        return {"status": "success", "outputs": {}}

    worker.run_step.side_effect = run
    return entered, release


def test_workflow_full_rejects_before_persistence_or_event_creation(execution):
    executor, store, worker = execution
    entered, release = block_worker(worker)
    first, queued, rejected = workflow(), workflow(), workflow()
    try:
        executor.submit(first, validate=False)
        assert entered.wait(2)
        executor.submit(queued, validate=False)
        before = set(store.workflows)
        with pytest.raises(BackgroundBusy):
            executor.submit(rejected, validate=False)
        assert set(store.workflows) == before == {first.workflow_id, queued.workflow_id}
        assert not (executor.config.workflows_dir / rejected.workflow_id).exists()
        assert not executor.bus.history(rejected.workflow_id)
        assert rejected.workflow_id not in executor._cancel_events
        assert executor.tasks.outstanding == 2
    finally:
        release.set()
        executor.tasks.shutdown()


def test_queued_workflow_cancel_releases_capacity_without_dispatch(execution):
    executor, store, worker = execution
    entered, release = block_worker(worker)
    first, queued = workflow(), workflow()
    try:
        executor.submit(first, validate=False)
        assert entered.wait(2)
        executor.submit(queued, validate=False)
        assert executor.cancel_workflow(queued.workflow_id) == 1
        assert executor.cancel_workflow(queued.workflow_id) == 0
        assert store.get_workflow(queued.workflow_id).status == "cancelled"
        assert executor.tasks.outstanding == 1 and executor.tasks.queued == 0
        assert queued.workflow_id not in executor._admissions
        assert queued.workflow_id not in executor._workers
        assert not any(call.args[0] == queued.workflow_id for call in worker.run_step.call_args_list)
        assert worker.release_workflow.call_args_list[-1].args == (queued.workflow_id,)
        assert len([event for event in executor.bus.history(queued.workflow_id) if event.type == "workflow_error"]) == 1
        with executor.reserve_submission():
            assert executor.tasks.outstanding == 2
    finally:
        release.set()
        executor.tasks.shutdown()


def test_workflow_queue_timeout_persists_failure_without_worker_dispatch(execution):
    executor, store, worker = execution
    executor.tasks.queue_timeout = 0.08
    entered, release = block_worker(worker)
    first, queued = workflow(), workflow()
    try:
        executor.submit(first, validate=False)
        assert entered.wait(2)
        executor.submit(queued, validate=False)
        eventually(lambda: executor.tasks.outstanding == 1)
        assert queued.status == "error" and queued.error["code"] == "QGIS_BUSY"
        assert queued.finished_at and queued.workflow_id not in executor._admissions
        assert not any(call.args[0] == queued.workflow_id for call in worker.run_step.call_args_list)
        assert executor.get_workflow_snapshot(queued.workflow_id)["status"] == "error"
        reader = RuntimeStore(store.state_file, read_only=True)
        try:
            assert reader.get_workflow(queued.workflow_id).error["code"] == "QGIS_BUSY"
        finally:
            reader.close()
    finally:
        release.set()
        executor.tasks.shutdown()


def test_running_workflow_cancel_fences_late_success_and_keeps_slot(execution):
    executor, _, worker = execution
    entered, release = block_worker(worker)
    record = workflow()
    try:
        executor.submit(record, validate=False)
        assert entered.wait(2)
        assert executor.cancel_workflow(record.workflow_id) == 1
        assert executor.tasks.outstanding == 1
        assert record.status == "running"
    finally:
        release.set()
        executor.tasks.shutdown()
    assert record.status == "cancelled" and worker.run_step.call_count == 1
    assert not record.artifacts and executor.tasks.outstanding == 0
    assert not any(event.type == "workflow_success" for event in executor.bus.history(record.workflow_id))


def classroom(store):
    instance = object.__new__(ClassroomWorkflowRuntime)
    instance.store = store
    instance.background_tasks = BoundedTaskPool(max_workers=1, max_queued=1)
    instance.question_bank_tasks = BoundedTaskPool(max_workers=1, max_queued=0)
    instance._run_lesson_import_job = Mock()
    instance._run_question_bank_import_job = Mock()
    return instance


def test_classroom_and_question_bank_reject_before_job_creation_and_isolate_budgets(execution):
    _, store, _ = execution
    instance = classroom(store)
    project = store.create_project()
    reserved = [instance.background_tasks.reserve() for _ in range(2)]
    import_token = instance.reserve_question_bank_import()
    try:
        with pytest.raises(BackgroundBusy):
            instance.submit_lesson_import(project.project_id, "synthetic")
        with pytest.raises(BackgroundBusy):
            instance.submit_question_bank_import(project.project_id, [{"filename": "x.docx", "raw": b"test"}])
        assert not store.jobs
        # Existing upload admission is consumed once even though the pool is full.
        result = instance.submit_question_bank_import(
            project.project_id, [{"filename": "x.docx", "raw": b"test"}], reservation=import_token)
        assert result["job_id"] in store.jobs and len(store.jobs) == 1
        with pytest.raises(ValueError):
            instance.submit_question_bank_import(project.project_id, [], reservation=import_token)
        assert len(store.jobs) == 1
    finally:
        for token in reserved:
            token.release()
        import_token.release()
        instance.shutdown()
    instance._run_lesson_import_job.assert_not_called()
    instance._run_question_bank_import_job.assert_called_once()


def test_classroom_queue_timeout_marks_job_failed_and_never_calls_import(execution):
    _, store, _ = execution
    instance = classroom(store)
    instance.background_tasks.queue_timeout = 0.08
    project = store.create_project()
    entered, release = threading.Event(), threading.Event()

    def blocked(*_args):
        entered.set()
        assert release.wait(5)

    instance._run_lesson_import_job.side_effect = blocked
    try:
        instance.submit_lesson_import(project.project_id, "first")
        assert entered.wait(2)
        queued = instance.submit_lesson_import(project.project_id, "second")
        eventually(lambda: instance.background_tasks.outstanding == 1)
        job = store.get_job(queued["job_id"])
        assert job.status == "failed" and "排队超时" in job.error
        assert instance._run_lesson_import_job.call_count == 1
    finally:
        release.set()
        instance.shutdown()
    instance.startup()
    try:
        instance.submit_lesson_import(project.project_id, "after restart")
    finally:
        instance.shutdown()
    assert instance._run_lesson_import_job.call_count == 2


def test_event_history_and_payload_are_bounded_immutable_snapshots():
    bus = _EventBus(history_limit=2)
    payload = {"workflow": {"status": "pending"}}
    bus.publish("wf", _Event("workflow_created", payload))
    payload["workflow"]["status"] = "success"
    assert bus.history("wf")[0].payload["workflow"]["status"] == "pending"
    for index in range(5):
        bus.publish("wf", _Event("step_started", {"index": index}))
    assert [event.payload["index"] for event in bus.history("wf")] == [3, 4]
    subscription = bus.subscribe("wf")
    assert subscription.requires_snapshot and subscription.empty()
    bus.unsubscribe("wf", subscription)
    assert not bus._subscribers


def test_evicted_history_that_receives_new_delta_still_requires_snapshot():
    bus = _EventBus(history_workflows=1)
    bus.publish("first", _Event("workflow_created", {}))
    bus.publish("second", _Event("workflow_created", {}))
    assert len(bus._history) == 1 and not bus.history("first")
    bus.publish("first", _Event("step_success", {}))
    subscription = bus.subscribe("first")
    assert subscription.requires_snapshot and subscription.empty()
    bus.unsubscribe("first", subscription)


def test_history_ttl_uses_monotonic_clock_without_unbounded_tombstones():
    bus = _EventBus(retention_seconds=10)
    with patch("backend.app.services.workflow_executor.time.monotonic", return_value=100):
        bus.publish("wf", _Event("workflow_created", {}))
    with patch("backend.app.services.workflow_executor.time.monotonic", return_value=111):
        assert bus.history("wf") == [] and not bus._history
        bus.publish("wf", _Event("step_started", {}))
        subscription = bus.subscribe("wf")
        assert subscription.requires_snapshot
        bus.unsubscribe("wf", subscription)


def test_slow_consumer_and_subscriber_limit_close_only_transport(execution):
    executor, store, worker = execution
    executor.bus = _EventBus(subscriber_limit=1, subscriber_queue=2)
    record = workflow()
    record.status = "running"
    store.create_workflow(record)
    before = store.state_file.read_bytes()
    executor.bus.publish(record.workflow_id, _Event("workflow_created", {"workflow": record.to_dict()}))
    stream = executor.stream(record.workflow_id)
    assert next(stream)["type"] == "workflow_created"
    limited = executor.bus.subscribe(record.workflow_id)
    assert limited.get_nowait().payload["reason"] == "subscriber_capacity"
    for index in range(3):
        executor.bus.publish(record.workflow_id, _Event("step_started", {"index": index}))
    event = next(stream)
    assert event["type"] == "stream_idle_timeout"
    assert event["payload"]["reason"] == "slow_consumer"
    assert event["payload"]["recovery"] == "get_workflow_snapshot_then_reconnect"
    with pytest.raises(StopIteration):
        next(stream)
    assert not executor.bus._subscribers
    assert store.state_file.read_bytes() == before and record.status == "running"
    worker.run_step.assert_not_called()


def test_truncated_running_history_streams_current_snapshot_then_live_events(execution):
    executor, store, worker = execution
    executor.bus = _EventBus(history_limit=1)
    record = workflow()
    record.status = "running"
    record.steps = [{"id": "retained", "status": "success"}]
    store.create_workflow(record)
    executor.bus.publish(record.workflow_id, _Event("workflow_created", {"workflow": {"status": "pending"}}))
    executor.bus.publish(record.workflow_id, _Event("step_started", {"step": {"id": "stale"}}))
    stream = executor.stream(record.workflow_id)
    recovered = next(stream)
    assert recovered["type"] == "workflow_created"
    assert recovered["payload"]["workflow"] == record.to_dict()
    assert recovered["payload"]["recovery_reason"] == "history_unavailable"
    executor.bus.publish(record.workflow_id, _Event("workflow_success", {"workflow": {"status": "success"}}))
    assert [event["type"] for event in stream] == ["workflow_success"]
    assert not executor.bus._subscribers
    worker.run_step.assert_not_called()
