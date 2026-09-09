"""Request correlation: identical step ids must never cross results.

Reproduction of the pre-fix defect: ``run_step`` used to let every caller
read the single shared output queue and match messages by ``step_id`` only,
so two concurrent workflows with the same step names could steal or swallow
each other's results. The fix gives each request a unique id and a private
reply box; a single dispatcher thread owns the shared queue.
"""
from __future__ import annotations

import threading
import time
import unittest

from .helpers import (
    assert_success,
    configure,
    make_manager,
    make_tmp_dir,
    step,
)


class CorrelationTests(unittest.TestCase):
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

    # ------------------------------------------------------------------
    # The original defect, reproduced structurally: two workflows, SAME
    # step ids, running concurrently. Every response must belong to the
    # requesting workflow and carry that workflow's marker file content.
    # ------------------------------------------------------------------

    def test_same_step_ids_concurrent_no_crossing(self) -> None:
        manager = self._new_manager()
        configure(manager, {"default_delay": 0.03})
        errors = []

        def run_workflow(workflow_id: str) -> None:
            try:
                for round_no in range(6):
                    result = manager.run_step(workflow_id, step(f"shared_step_{round_no % 2}"))
                    assert_success(result, workflow_id, f"shared_step_{round_no % 2}")
                    marker_file = result["outputs"]["path"]
                    content = open(marker_file, encoding="utf-8").read()
                    expected = f"{workflow_id}|shared_step_{round_no % 2}"
                    if not content.startswith(expected):
                        errors.append(
                            f"{workflow_id} round {round_no}: crossed result {content!r}"
                        )
                    if result["outputs"]["marker"] != workflow_id:
                        errors.append(f"{workflow_id}: outputs belong to {result['outputs']['marker']}")
            except Exception as exc:  # pragma: no cover
                errors.append(f"{workflow_id} raised {exc!r}")

        threads = [
            threading.Thread(target=run_workflow, args=(f"wf_{i}",)) for i in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        self.assertEqual(errors, [])
        self.assertEqual(manager.stats["late_messages_dropped"], 0)
        self.assertEqual(manager.stats["duplicate_messages_dropped"], 0)

    # ------------------------------------------------------------------
    # 10 interleaved groups of two workflows with identical step names.
    # ------------------------------------------------------------------

    def test_ten_interleaved_groups_identical_step_names(self) -> None:
        manager = self._new_manager()
        configure(manager, {"default_delay": 0.01})
        failures = []

        def run_workflow(workflow_id: str, group: int) -> None:
            for s in ("s1", "s2", "s3"):
                result = manager.run_step(workflow_id, step(s))
                try:
                    assert_success(result, workflow_id, s)
                    content = open(result["outputs"]["path"], encoding="utf-8").read()
                    assert content.startswith(f"{workflow_id}|{s}"), content
                except AssertionError as exc:
                    failures.append(f"group {group} {workflow_id}/{s}: {exc}")

        for group in range(10):
            threads = [
                threading.Thread(target=run_workflow, args=(f"alpha_{group}", group)),
                threading.Thread(target=run_workflow, args=(f"beta_{group}", group)),
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(60)
        self.assertEqual(failures, [])
        self.assertEqual(manager.stats["late_messages_dropped"], 0)

    # ------------------------------------------------------------------
    # Orphan / forged messages (e.g. results of requests that no caller is
    # waiting for any more) must be dropped, never delivered.
    # ------------------------------------------------------------------

    def test_orphan_message_is_dropped_and_counted(self) -> None:
        manager = self._new_manager()
        configure(manager, {"orphan_after_op": "probe"})
        result = manager.run_step("wf_orphan", step("s1"))
        assert_success(result, "wf_orphan", "s1")
        # The fake emits a forged message right after the real result; wait
        # until the dispatcher has routed (and dropped) it.
        deadline = 5.0
        waited = 0.0
        while manager.stats["late_messages_dropped"] < 1 and waited < deadline:
            time.sleep(0.05)
            waited += 0.05
        self.assertGreaterEqual(manager.stats["late_messages_dropped"], 1)

        # The next request must be unaffected and get its own result.
        followup = manager.run_step("wf_orphan", step("s2"))
        assert_success(followup, "wf_orphan", "s2")

    # ------------------------------------------------------------------
    # Duplicate result messages collapse to a single delivery.
    # ------------------------------------------------------------------

    def test_duplicate_results_dropped(self) -> None:
        manager = self._new_manager()
        configure(manager, {"duplicate_result": True})
        result = manager.run_step("wf_dup", step("s1"))
        assert_success(result, "wf_dup", "s1")
        # The duplicate arrives right after the original; by then the request
        # is already settled, so it lands in the "late" bucket — either way
        # it must be dropped, never delivered a second time.
        deadline = time.time() + 5
        while time.time() < deadline and (
            manager.stats["late_messages_dropped"] + manager.stats["duplicate_messages_dropped"]
        ) < 1:
            time.sleep(0.05)
        dropped = (
            manager.stats["late_messages_dropped"]
            + manager.stats["duplicate_messages_dropped"]
        )
        self.assertGreaterEqual(dropped, 1)
        # A second, unrelated request still works.
        second = manager.run_step("wf_dup", step("s2"))
        assert_success(second, "wf_dup", "s2")


if __name__ == "__main__":
    unittest.main()
