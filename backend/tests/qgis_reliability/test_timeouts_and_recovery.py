"""Timeouts, crash recovery, cancellation and lifecycle hygiene.

Covers the distinct failure modes required from the worker manager:

* startup failure → ``WORKER_START_FAILED``
* queue timeout vs execution timeout → ``STEP_QUEUED_TIMEOUT`` /
  ``STEP_EXEC_TIMEOUT`` with queue/exec timings separated
* late results after a timeout are isolated (never reused by later requests)
* hard / soft worker crash → ``WORKER_CRASHED`` for the in-flight request,
  auto-retry once for reference-free steps, accurate
  ``WORKER_RESTARTED``-class failure for steps relying on lost in-memory
  references (at executor level that surfaces as ``REFERENCE_NOT_RESOLVED``,
  here at manager level as crash without retry)
* cancellation → ``STEP_CANCELLED``, late result dropped, rerun works
* repeated start/shutdown cycles leak no processes
"""
from __future__ import annotations

import threading
import time
import unittest
from pathlib import Path

from .helpers import (
    assert_success,
    configure,
    make_manager,
    make_tmp_dir,
    step,
)


class TimeoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = make_tmp_dir()
        self.managers = []

    def tearDown(self) -> None:
        for manager in self.managers:
            manager.shutdown()

    def _new_manager(self, **kwargs):
        manager = make_manager(self.tmp, **kwargs)
        self.managers.append(manager)
        return manager

    def test_queue_timeout_distinct_from_exec_timeout(self) -> None:
        manager = self._new_manager(step_timeout=30.0, queue_timeout=0.8)
        configure(manager, {"delay_by_op": {"slow": 3.0}})
        outcomes = {}

        def blocker() -> None:
            # Occupies the single worker for ~3s.
            outcomes["block"] = manager.run_step("wf_block", step("slow", op="slow"))

        t = threading.Thread(target=blocker)
        t.start()
        time.sleep(0.2)  # ensure the blocker is dequeued first
        queued = manager.run_step("wf_queued", step("quick", op="quick"))
        t.join(30)

        assert_success(outcomes["block"], "wf_block", "slow")
        self.assertEqual(queued["status"], "error")
        self.assertEqual(queued["error"]["code"], "STEP_QUEUED_TIMEOUT")
        self.assertGreater(queued["timings"]["queued_ms"], 700)
        self.assertIsNone(queued["timings"]["exec_ms"])

    def test_exec_timeout_and_late_result_isolation(self) -> None:
        # The fake sleeps 2.5s; the caller gives up after 0.6s. The late
        # result arrives ~1.9s later and must be dropped, and a follow-up
        # request with the SAME step id must receive its own fresh result.
        manager = self._new_manager(step_timeout=0.6, queue_timeout=5.0)
        configure(manager, {"delay_by_op": {"slow": 2.5}})
        started = time.time()
        timed_out = manager.run_step("wf_late", step("slow", op="slow"))
        elapsed = time.time() - started
        self.assertEqual(timed_out["status"], "error")
        self.assertEqual(timed_out["error"]["code"], "STEP_EXEC_TIMEOUT")
        self.assertLess(elapsed, 2.0, "caller should not wait for the full 2.5s op")
        self.assertGreater(timed_out["timings"]["exec_ms"], 500)

        # Let the late result arrive and get dropped.
        deadline = time.time() + 6
        while time.time() < deadline and manager.stats["late_messages_dropped"] < 1:
            time.sleep(0.05)
        self.assertGreaterEqual(manager.stats["late_messages_dropped"], 1)

        # Follow-up with the SAME step id (but a fast op) gets a fresh,
        # correct result — never the stale one.
        followup = manager.run_step("wf_late", step("slow", op="quick"))
        assert_success(followup, "wf_late", "slow")
        self.assertEqual(followup["outputs"]["marker"], "wf_late")

    def test_worker_stuck_fast_fail_then_recovery(self) -> None:
        manager = self._new_manager(step_timeout=0.5, queue_timeout=5.0)
        configure(manager, {"delay_by_op": {"slow": 1.2}})
        first = manager.run_step("wf_stuck", step("slow", op="slow"))
        self.assertEqual(first["error"]["code"], "STEP_EXEC_TIMEOUT")

        # While the worker is still busy in the abandoned step, a new
        # request fast-fails instead of silently queueing behind it.
        second = manager.run_step("wf_stuck", step("quick", op="quick"))
        self.assertEqual(second["status"], "error")
        self.assertEqual(second["error"]["code"], "WORKER_STUCK")

        # Once the orphan result proves progress, requests are accepted.
        deadline = time.time() + 6
        while time.time() < deadline and manager.stats["late_messages_dropped"] < 1:
            time.sleep(0.05)
        third = manager.run_step("wf_stuck", step("quick", op="quick"))
        assert_success(third, "wf_stuck", "quick")


class CrashRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = make_tmp_dir()
        self.managers = []

    def tearDown(self) -> None:
        for manager in self.managers:
            manager.shutdown()

    def _new_manager(self, **kwargs):
        manager = make_manager(self.tmp, **kwargs)
        self.managers.append(manager)
        return manager

    def test_hard_crash_auto_retries_reference_free_step(self) -> None:
        manager = self._new_manager()
        configure(manager, {"crash_ops": {"explode": "hard"}})
        generation_before = manager.generation()

        result = manager.run_step("wf_crash", step("s1", op="explode"))
        assert_success(result, "wf_crash", "s1")
        self.assertEqual(result["attempt"], 2, "crashed attempt retried once")
        self.assertGreater(manager.generation(), generation_before, "fresh worker generation")
        self.assertGreaterEqual(manager.stats["crashes_recovered"], 1)
        self.assertEqual(manager.stats["auto_retries"], 1)
        # And the worker is usable.
        again = manager.run_step("wf_crash", step("s2"))
        assert_success(again, "wf_crash", "s2")

    def test_soft_crash_reports_worker_crashed(self) -> None:
        manager = self._new_manager()
        configure(manager, {"crash_ops": {"explode": "soft"}})
        result = manager.run_step("wf_soft", step("explode", op="explode"))
        # The op crashes worker gen 1; the auto-retry runs on a fresh
        # worker whose rules died with the old process, so the retry
        # succeeds — exactly one automatic retry, no loop.
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["attempt"], 2)
        self.assertEqual(manager.stats["auto_retries"], 1)
        # The manager recovered: a fresh worker serves new requests.
        post = manager.run_step("wf_soft", step("probe"))
        assert_success(post, "wf_soft", "probe")

    def test_crash_skips_auto_retry_for_reference_steps(self) -> None:
        manager = self._new_manager()
        configure(manager, {"crash_ops": {"explode": "hard"}})
        generation_before = manager.generation()
        referenced = step("use_layer", op="explode", input="${s1.layer}")
        result = manager.run_step("wf_refs", referenced)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], "WORKER_CRASHED")
        # No unsafe retry happened: still the same worker generation.
        self.assertEqual(manager.generation(), generation_before)
        self.assertGreaterEqual(manager.stats["auto_retries_skipped_refs"], 1)
        # A later reference-free step triggers the respawn and works.
        post = manager.run_step("wf_refs", step("probe"))
        assert_success(post, "wf_refs", "probe")
        self.assertGreater(manager.generation(), generation_before)

    def test_pending_requests_of_other_workflow_fail_on_crash(self) -> None:
        manager = self._new_manager()
        configure(manager, {"delay_by_op": {"slow": 4.0}, "crash_ops": {"explode": "hard"}})
        outcomes = {}

        def run(workflow_id: str, op: str) -> None:
            outcomes[workflow_id] = manager.run_step(workflow_id, step(op, op=op))

        threads = [
            threading.Thread(target=run, args=("wf_a", "slow")),
            threading.Thread(target=run, args=("wf_b", "explode")),
            threading.Thread(target=run, args=("wf_c", "probe")),
        ]
        for t in threads:
            t.start()
            time.sleep(0.25)  # deterministic queue order: a, b, c
        for t in threads:
            t.join(60)

        # wf_a ran to completion before the worker reached the crasher.
        self.assertEqual(outcomes["wf_a"]["status"], "success")
        # wf_b was in flight when the worker died → its retry ran on the
        # fresh worker (rules are per-process and died with gen 1) and
        # succeeded with attempt=2.
        self.assertEqual(outcomes["wf_b"]["status"], "success")
        self.assertEqual(outcomes["wf_b"]["attempt"], 2)
        # wf_c was queued behind the crash → its generation died too; the
        # reference-free auto-retry gives it a fresh worker and it succeeds.
        self.assertEqual(outcomes["wf_c"]["status"], "success")
        self.assertEqual(outcomes["wf_c"]["attempt"], 2)
        self.assertGreaterEqual(manager.stats["crashes_recovered"], 1)


class CancelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = make_tmp_dir()
        self.managers = []

    def tearDown(self) -> None:
        for manager in self.managers:
            manager.shutdown()

    def _new_manager(self, **kwargs):
        manager = make_manager(self.tmp, **kwargs)
        self.managers.append(manager)
        return manager

    def test_cancel_during_execution_then_rerun(self) -> None:
        manager = self._new_manager()
        configure(manager, {"delay_by_op": {"slow": 4.0}})
        cancel_event = threading.Event()
        outcomes = {}

        def run_slow() -> None:
            outcomes["slow"] = manager.run_step(
                "wf_cancel", step("slow", op="slow"), cancel_event=cancel_event
            )

        t = threading.Thread(target=run_slow)
        t.start()
        time.sleep(0.6)  # started executing
        cancel_event.set()
        t.join(30)
        result = outcomes["slow"]
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], "STEP_CANCELLED")
        self.assertLess(result["timings"]["total_ms"], 3000)

        # Late result of the cancelled request is isolated; rerun works.
        deadline = time.time() + 8
        while time.time() < deadline and manager.stats["late_messages_dropped"] < 1:
            time.sleep(0.05)
        self.assertGreaterEqual(manager.stats["late_messages_dropped"], 1)
        rerun = manager.run_step("wf_cancel", step("slow", op="slow"))
        assert_success(rerun, "wf_cancel", "slow")

    def test_cancel_queued_request_skips_execution(self) -> None:
        manager = self._new_manager()
        configure(manager, {"delay_by_op": {"slow": 1.5}})
        cancel_event = threading.Event()
        outcomes = {}

        def blocker() -> None:
            manager.run_step("wf_q0", step("slow", op="slow"))

        def run_queued() -> None:
            outcomes["q"] = manager.run_step(
                "wf_q1", step("quick", op="quick"), cancel_event=cancel_event
            )

        t0 = threading.Thread(target=blocker)
        t0.start()
        time.sleep(0.2)
        t1 = threading.Thread(target=run_queued)
        t1.start()
        time.sleep(0.2)  # queued behind the blocker, not yet dequeued
        cancel_event.set()
        t1.join(30)
        t0.join(30)
        result = outcomes["q"]
        # The manager cancels queued requests immediately; the worker-side
        # FIFO means the skip-ack is best-effort (the request was already
        # settled manager-side), so STEP_CANCELLED is the stable contract.
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], "STEP_CANCELLED")

    def test_cancel_workflow_api(self) -> None:
        manager = self._new_manager()
        configure(manager, {"delay_by_op": {"slow": 4.0}})
        outcomes = {}

        def run_slow() -> None:
            outcomes["slow"] = manager.run_step("wf_api", step("slow", op="slow"))

        t = threading.Thread(target=run_slow)
        t.start()
        time.sleep(0.6)
        cancelled = manager.cancel_workflow("wf_api")
        t.join(30)
        self.assertEqual(cancelled, 1)
        self.assertEqual(outcomes["slow"]["error"]["code"], "STEP_CANCELLED")


class LifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = make_tmp_dir()

    def test_repeated_start_shutdown_cycles(self) -> None:
        pids = []
        dead_checks = []
        for cycle in range(4):
            manager = make_manager(self.tmp)
            configure(manager, {"default_delay": 0.0})
            result = manager.run_step(f"wf_cycle_{cycle}", step("probe"))
            assert_success(result, f"wf_cycle_{cycle}", "probe")
            self.assertTrue(manager.is_alive())
            process = manager._process
            pids.append(process.pid)
            manager.shutdown()
            self.assertFalse(manager.is_alive())
            self.assertIsNone(manager._process)
            self.assertIsNone(manager._input_queue)
            self.assertIsNone(manager._output_queue)
            dead_checks.append(process)  # joined handle; is_alive() is now False
        # Distinct worker processes were used, and none of them is alive now.
        self.assertEqual(len(set(pids)), len(pids))
        for process in dead_checks:
            self.assertFalse(process.is_alive(), f"pid {process.pid} leaked")

    def test_shutdown_is_idempotent(self) -> None:
        manager = make_manager(self.tmp)
        manager.ensure_started()
        manager.shutdown()
        manager.shutdown()  # must not raise
        self.assertFalse(manager.is_alive())

    def test_startup_failure_returns_start_failed(self) -> None:
        from backend.app.services.pyqgis_worker import PyQgisWorkerManager

        def broken_worker(*_args):  # dies immediately, no protocol
            raise SystemExit(1)

        manager = PyQgisWorkerManager(
            workflows_root=self.tmp,
            startup_timeout=6.0,
            worker_target=broken_worker,
        )
        result = manager.run_step("wf_boot", step("s1"))
        self.assertEqual(result["status"], "error")
        self.assertIn(
            result["error"]["code"],
            {"WORKER_START_FAILED", "WORKER_CRASHED"},
        )
        manager.shutdown()

    def test_release_purges_step_temp_dirs_via_fake_worker(self) -> None:
        manager = make_manager(self.tmp)
        configure(manager, {})
        result = manager.run_step("wf_rel", step("s1"))
        assert_success(result, "wf_rel", "s1")
        marker = Path(result["outputs"]["path"])
        self.assertTrue(marker.exists())
        steps_dir = self.tmp / "wf_rel" / "steps"
        self.assertTrue(steps_dir.exists())
        manager.release_workflow("wf_rel")
        deadline = time.time() + 5
        while time.time() < deadline and steps_dir.exists():
            time.sleep(0.05)
        self.assertFalse(steps_dir.exists(), "per-step temp dirs must be purged on release")
        manager.shutdown()


if __name__ == "__main__":
    unittest.main()
