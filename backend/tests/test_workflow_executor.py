"""Executor + worker manager tests using a stubbed PyQGIS worker.

These tests do NOT require a real QGIS install. We replace the worker
manager with a stub that returns canned step results.
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
from backend.app.services.workflow_templates import expand_template
from backend.app.services.pyqgis_worker.errors import make_error
from backend.app.store import RuntimeStore


class _StubWorkerManager:
    """Pretends to be PyQgisWorkerManager but never starts a subprocess."""

    def __init__(self, results: Dict[str, Dict[str, Any]] | None = None, fail_step: str = ""):
        self._results = results or {}
        self._fail_step = fail_step
        self._init_warning = None

    def init_warning(self):
        return self._init_warning

    def run_step(self, workflow_id: str, step: Dict[str, Any], timeout: float | None = None) -> Dict[str, Any]:
        step_id = str(step.get("id"))
        if step_id == self._fail_step:
            return {
                "type": "step_result",
                "workflow_id": workflow_id,
                "step_id": step_id,
                "status": "error",
                "outputs": {},
                "error": make_error(
                    "PROCESSING_FAILED",
                    "stub failure",
                    "测试用失败",
                    step_id=step_id,
                ),
            }
        outputs = self._results.get(step_id) or {"path": f"/fake/{step_id}.gpkg", "layer": f"alias_{step_id}"}
        return {
            "type": "step_result",
            "workflow_id": workflow_id,
            "step_id": step_id,
            "status": "success",
            "outputs": outputs,
            "error": None,
        }

    def release_workflow(self, workflow_id: str) -> None:
        return None

    def shutdown(self, timeout: float = 1.0) -> None:
        return None


def _make_config() -> AppConfig:
    tmp = Path(tempfile.mkdtemp(prefix="webgis_test_"))
    config = AppConfig()
    config.data_dir = tmp / "backend" / "data"
    config.state_dir = config.data_dir / "state"
    config.uploads_dir = config.data_dir / "uploads"
    config.outputs_dir = config.data_dir / "outputs"
    config.workflows_dir = config.data_dir / "workflows"
    config.state_file = config.state_dir / "runtime.json"
    config.ensure_dirs()
    return config


class WorkflowExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = _make_config()
        self.store = RuntimeStore(self.config.state_file)
        # Use a tiny workflow so we don't need real QGIS
        self.simple_workflow = {
            "version": "1.0",
            "intent": "demo",
            "steps": [
                {"id": "s1", "op": "load_layer", "params": {"source": "demo.geojson", "project_id": "p1"}},
                {
                    "id": "s2",
                    "op": "export_geojson",
                    "params": {"input": "${s1.layer}", "name": "demo"},
                    "depends_on": ["s1"],
                },
            ],
            "outputs": {"geojson": "${s2.geojson}"},
        }

    def _wait_for_status(self, executor: WorkflowExecutor, workflow_id: str, timeout: float = 5.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            record = self.store.get_workflow(workflow_id)
            if record and record.status in {"success", "error"}:
                return record
            time.sleep(0.05)
        return self.store.get_workflow(workflow_id)

    def test_success_path_emits_artifacts(self) -> None:
        # The stub returns geojson path under workflow dir, so we make sure to
        # resolve it correctly by writing a fake file.
        manager = _StubWorkerManager(results={
            "s1": {"layer": "alias_s1", "path": "/x/s1.gpkg"},
            "s2": {"geojson": "", "path": ""},
        })
        executor = WorkflowExecutor(self.config, self.store, worker_manager=manager)

        record = WorkflowRecord.create(
            project_id="p1",
            user_message="demo",
            intent="demo",
            template_id="custom",
            mode="freeform",
            workflow_json=self.simple_workflow,
        )
        # Pre-create the geojson file so executor's relative-path resolution
        # produces an artifact.
        wf_dir = self.config.workflow_dir(record.workflow_id)
        out_geojson = wf_dir / "outputs" / "demo.geojson"
        out_geojson.write_text("{}", encoding="utf-8")
        manager._results["s2"] = {
            "geojson": str(out_geojson),
            "path": str(out_geojson),
            "extent": [0, 0, 1, 1],
            "crs": "EPSG:4326",
        }

        executor.submit(record)
        final = self._wait_for_status(executor, record.workflow_id)
        self.assertIsNotNone(final)
        self.assertEqual(final.status, "success")
        self.assertEqual(len(final.steps), 2)
        kinds = {a["kind"] for a in final.artifacts}
        self.assertIn("geojson", kinds)

    def test_step_failure_marks_workflow_error(self) -> None:
        manager = _StubWorkerManager(fail_step="s1")
        executor = WorkflowExecutor(self.config, self.store, worker_manager=manager)
        record = WorkflowRecord.create(
            project_id="p1",
            user_message="demo",
            intent="demo",
            workflow_json=self.simple_workflow,
        )
        executor.submit(record)
        final = self._wait_for_status(executor, record.workflow_id)
        self.assertEqual(final.status, "error")
        self.assertIsNotNone(final.error)
        self.assertEqual(final.error["code"], "PROCESSING_FAILED")

    def test_invalid_workflow_short_circuits(self) -> None:
        manager = _StubWorkerManager()
        executor = WorkflowExecutor(self.config, self.store, worker_manager=manager)
        bad_workflow = {"steps": [{"id": "s1", "op": "no_such_op", "params": {}}]}
        record = WorkflowRecord.create(
            project_id="p1",
            workflow_json=bad_workflow,
        )
        executor.submit(record)
        final = self.store.get_workflow(record.workflow_id)
        self.assertEqual(final.status, "error")
        self.assertEqual(final.error["code"], "VALIDATION_FAILED")

    def test_template_round_trip(self) -> None:
        manager = _StubWorkerManager()
        executor = WorkflowExecutor(self.config, self.store, worker_manager=manager)
        match = expand_template("population_choropleth", "制作中国人口密度图", {"project_id": "p1"})
        record = WorkflowRecord.create(
            project_id="p1",
            user_message="制作中国人口密度图",
            intent=match.intent,
            template_id=match.template_id,
            mode="template",
            workflow_json=match.workflow,
        )
        executor.submit(record)
        final = self._wait_for_status(executor, record.workflow_id, timeout=10.0)
        self.assertEqual(final.status, "success")


if __name__ == "__main__":
    unittest.main()
