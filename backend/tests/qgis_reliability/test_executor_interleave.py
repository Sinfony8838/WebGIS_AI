"""Executor-level interleaving with the real worker manager + fake worker.

Two workflows with IDENTICAL step ids run concurrently through the full
``WorkflowExecutor`` pipeline (store + event bus + worker manager). After
the fix each workflow's steps carry that workflow's outputs; artifact
registration, status persistence and event streams stay consistent, and no
request's results leak into the other workflow.
"""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Dict

from backend.app.config import AppConfig
from backend.app.models import WorkflowRecord
from backend.app.services.workflow_executor import WorkflowExecutor
from backend.app.store import RuntimeStore

from .fake_worker import run_fake_worker
from backend.app.services.pyqgis_worker import PyQgisWorkerManager


def _make_config(tmp: Path) -> AppConfig:
    config = AppConfig()
    config.data_dir = tmp / "backend" / "data"
    config.state_dir = config.data_dir / "state"
    config.uploads_dir = config.data_dir / "uploads"
    config.outputs_dir = config.data_dir / "outputs"
    config.workflows_dir = config.data_dir / "workflows"
    config.state_file = config.state_dir / "runtime.json"
    config.ensure_dirs()
    return config


class ExecutorInterleaveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="qgis_executor_"))
        self.config = _make_config(self.tmp)
        self.store = RuntimeStore(self.config.state_file)
        self.manager = PyQgisWorkerManager(
            workflows_root=self.config.workflows_dir,
            worker_target=run_fake_worker,
            startup_timeout=20.0,
            step_timeout=30.0,
            queue_timeout=30.0,
        )
        self.executors = []

    def tearDown(self) -> None:
        for executor in self.executors:
            executor.shutdown()

    def _make_executor(self) -> WorkflowExecutor:
        executor = WorkflowExecutor(self.config, self.store, worker_manager=self.manager)
        self.executors.append(executor)
        return executor

    def _workflow_json(self, group: int) -> Dict[str, Any]:
        # Deliberately identical step ids across workflows.
        return {
            "version": "1.0",
            "intent": "reliability",
            "steps": [
                {"id": "load", "op": "load_layer", "params": {"source": f"g{group}.geojson"}},
                {"id": "buffer", "op": "buffer", "params": {"distance": group}, "depends_on": ["load"]},
                {"id": "export", "op": "export_geojson", "params": {"name": f"g{group}"}, "depends_on": ["buffer"]},
            ],
            "outputs": {},
        }

    def _wait_terminal(self, store: RuntimeStore, workflow_id: str, timeout: float = 60.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            record = store.get_workflow(workflow_id)
            if record and record.status in {"success", "error"}:
                return record
            time.sleep(0.05)
        return store.get_workflow(workflow_id)

    def test_five_groups_same_step_ids_across_workflows(self) -> None:
        executor = self._make_executor()
        records = []
        for group in range(5):
            for name in (f"alpha_{group}", f"beta_{group}"):
                record = WorkflowRecord.create(
                    project_id=f"proj_{name}",
                    user_message="reliability",
                    intent="reliability",
                    workflow_json=self._workflow_json(group),
                )
                records.append(record)
                executor.submit(record, validate=False)

        finals = []
        for record in records:
            final = self._wait_terminal(self.store, record.workflow_id)
            self.assertIsNotNone(final)
            self.assertEqual(final.status, "success", final.error)
            finals.append(final)

        # Per-workflow output ownership: every step's recorded outputs must
        # carry that workflow's marker and its path must live inside the
        # workflow's own directory. Content is asserted from the returned
        # payload because a completed workflow's per-step temp dirs are
        # purged on release (that cleanup is itself part of the contract).
        for final in finals:
            wf_dir = self.config.workflow_dir(final.workflow_id)
            for state in final.steps:
                outputs = state.get("outputs") or {}
                self.assertEqual(outputs.get("marker"), final.workflow_id)
                marker_file = Path(outputs["path"])
                self.assertTrue(
                    str(marker_file).startswith(str(wf_dir)),
                    f"{marker_file} outside {wf_dir}",
                )
                content = outputs["content"]
                self.assertTrue(
                    content.startswith(f"{final.workflow_id}|{state['id']}"),
                    f"crossed content: {content!r} for {final.workflow_id}/{state['id']}",
                )

        # Zero duplicate published marker paths across ALL workflows.
        seen: Dict[str, str] = {}
        for final in finals:
            for state in final.steps:
                path = state["outputs"]["path"]
                owner = seen.setdefault(path, final.workflow_id)
                self.assertEqual(owner, final.workflow_id, f"duplicate artifact {path}")

        self.assertEqual(self.manager.stats["late_messages_dropped"], 0)
        self.assertEqual(self.manager.stats["duplicate_messages_dropped"], 0)

    def test_executor_cancel_workflow(self) -> None:
        executor = self._make_executor()
        # One slow step occupies the worker; cancel the queued workflow.
        record = WorkflowRecord.create(
            project_id="proj_cancel",
            user_message="cancel me",
            workflow_json={
                "version": "1.0",
                "steps": [
                    {"id": "s1", "op": "slow", "params": {}},
                ],
                "outputs": {},
            },
        )
        # Patch the manager timeout so the queued request is cancelled before
        # the slow blocker finishes.
        record2 = WorkflowRecord.create(
            project_id="proj_cancel2",
            user_message="blocker",
            workflow_json={
                "version": "1.0",
                "steps": [{"id": "s1", "op": "slow", "params": {}}],
                "outputs": {},
            },
        )
        # Push fake-worker fault rules via the protocol config message.
        from .helpers import configure

        configure(self.manager, {"delay_by_op": {"slow": 3.0}})
        executor.submit(record2, validate=False)
        time.sleep(0.3)
        executor.submit(record, validate=False)
        time.sleep(0.3)
        cancelled = executor.cancel_workflow(record.workflow_id)
        self.assertEqual(cancelled, 1)
        final = self._wait_terminal(self.store, record.workflow_id)
        # Cancels surface as the dedicated "cancelled" status (not a failure).
        self.assertEqual(final.status, "cancelled")
        self.assertIsNotNone(final.error)
        self.assertEqual(final.error["code"], "STEP_CANCELLED")
        # The blocker workflow still completes successfully.
        final2 = self._wait_terminal(self.store, record2.workflow_id)
        self.assertEqual(final2.status, "success")


if __name__ == "__main__":
    unittest.main()
