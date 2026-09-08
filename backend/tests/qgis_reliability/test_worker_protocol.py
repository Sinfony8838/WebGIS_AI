"""Worker-side protocol tests, run in-process with a stubbed QGIS.

``worker_main.worker_loop`` is driven directly on thread queues; the QGIS
bootstrap and the task dispatcher are patched so no QGIS install is needed.
These tests pin the wire protocol the manager relies on:

* every ack/result echoes the request's unique ``request_id``;
* a queued request whose cancel arrives first is skipped with
  ``step_cancelled`` (defense-in-depth; the manager-side cancel is primary);
* successful steps pass artifact validation (files exist, re-openable);
  legitimate empty results (feature_count=0) stay successful;
* broken artifacts fail with ``OUTPUT_INVALID``;
* ``release_workflow`` frees memory and purges per-step temp dirs while
  keeping published outputs.
"""
from __future__ import annotations

import json
import queue as queue_module
import threading
import time
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest import mock

from backend.app.services.pyqgis_worker import worker_main


class WorkerHarness:
    """Runs worker_loop on background threads with scripted dispatch."""

    def __init__(self, workflows_root: Path, dispatch_fn=None) -> None:
        self.input_q: "queue_module.Queue[Dict[str, Any]]" = queue_module.Queue()
        self.output_q: "queue_module.Queue[Dict[str, Any]]" = queue_module.Queue()
        self.workflows_root = workflows_root
        self.messages: List[Dict[str, Any]] = []
        self._release = threading.Event()
        self._release.set()
        self._dispatch_fn = dispatch_fn or (lambda op, params, workspace: {"ok": 1})
        self._patchers = [
            mock.patch(
                "backend.app.services.pyqgis_worker.bootstrap.start_qgis",
                lambda *_a, **_k: object(),
            ),
            mock.patch(
                "backend.app.services.pyqgis_worker.task_router.dispatch",
                self._gated_dispatch,
            ),
        ]
        for p in self._patchers:
            p.start()
        self._thread = threading.Thread(
            target=worker_main.worker_loop,
            args=(self.input_q, self.output_q, "", str(workflows_root)),
            daemon=True,
        )
        self._thread.start()
        ready = self.output_q.get(timeout=10)
        assert ready.get("type") == "worker_ready", ready

    def _gated_dispatch(self, op: str, params: Dict[str, Any], workspace: Any) -> Dict[str, Any]:
        self._release.wait(10)
        return self._dispatch_fn(op, params, workspace)

    def send(self, msg: Dict[str, Any]) -> None:
        self.input_q.put(msg)

    def next_message(self, timeout: float = 10.0) -> Optional[Dict[str, Any]]:
        try:
            return self.output_q.get(timeout=timeout)
        except queue_module.Empty:
            return None

    def wait_for(self, predicate, timeout: float = 10.0) -> Optional[Dict[str, Any]]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = self.next_message(timeout=max(0.05, deadline - time.time()))
            if msg is None:
                return None
            self.messages.append(msg)
            if predicate(msg):
                return msg
        return None

    def stop(self) -> None:
        self._release.set()
        self.send({"type": "shutdown"})
        self._thread.join(5)
        for p in getattr(self, "_patchers", []):
            p.stop()


class WorkerProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self.tmp = Path(tempfile.mkdtemp(prefix="qgis_protocol_"))
        self.harnesses: List[WorkerHarness] = []

    def tearDown(self) -> None:
        for h in self.harnesses:
            h.stop()

    def start(self, dispatch_fn=None) -> WorkerHarness:
        h = WorkerHarness(self.tmp, dispatch_fn)
        self.harnesses.append(h)
        return h

    # ------------------------------------------------------------------

    def test_run_step_acks_and_echoes_request_id(self) -> None:
        h = self.start()
        h.send({
            "type": "run_step",
            "request_id": "req-1",
            "workflow_id": "wf",
            "step": {"id": "s1", "op": "probe", "params": {}},
        })
        ack = h.next_message()
        self.assertEqual(ack["type"], "step_started")
        self.assertEqual(ack["request_id"], "req-1")
        self.assertEqual(ack["workflow_id"], "wf")
        self.assertEqual(ack["step_id"], "s1")
        result = h.next_message()
        self.assertEqual(result["type"], "step_result")
        self.assertEqual(result["request_id"], "req-1")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["outputs"], {"ok": 1})

    def test_unknown_op_reports_error_with_request_id(self) -> None:
        def fail_dispatch(op, params, workspace):
            from backend.app.services.pyqgis_worker.errors import WorkflowExecutionError

            raise WorkflowExecutionError(
                code="UNKNOWN_OP", message="no handler", user_friendly="不支持的操作"
            )

        h = self.start(fail_dispatch)
        h.send({
            "type": "run_step",
            "request_id": "req-2",
            "workflow_id": "wf",
            "step": {"id": "s1", "op": "nope", "params": {}},
        })
        result = h.wait_for(lambda m: m.get("type") == "step_result")
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], "UNKNOWN_OP")
        self.assertEqual(result["request_id"], "req-2")

    def test_cancelled_before_start_is_skipped(self) -> None:
        h = self.start()
        # Cancel the request BEFORE its run_step is dequeued (artificial
        # ordering, but pins the defensive worker-side branch).
        h.send({"type": "cancel_step", "request_id": "req-x"})
        h.send({
            "type": "run_step",
            "request_id": "req-x",
            "workflow_id": "wf",
            "step": {"id": "s1", "op": "probe", "params": {}},
        })
        msg = h.wait_for(
            lambda m: m.get("type") in ("step_cancelled", "step_result")
        )
        self.assertIsNotNone(msg)
        self.assertEqual(msg["type"], "step_cancelled")
        self.assertEqual(msg["request_id"], "req-x")

    def test_successful_output_passes_validation(self) -> None:
        wf_dir = self.tmp / "wf_ok"
        out = wf_dir / "outputs" / "result.geojson"
        out.parent.mkdir(parents=True, exist_ok=True)
        fc = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 2]},
             "properties": {"n": 1}},
        ]}
        out.write_text(json.dumps(fc), encoding="utf-8")

        def dispatch_fn(op, params, workspace):
            return {"geojson": str(out), "feature_count": 1}

        h = self.start(dispatch_fn)
        h.send({
            "type": "run_step",
            "request_id": "req-v",
            "workflow_id": "wf_ok",
            "step": {"id": "s1", "op": "export_geojson", "params": {}},
        })
        result = h.wait_for(lambda m: m.get("type") == "step_result")
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "success", result)
        self.assertEqual(result["outputs"]["feature_count"], 1)

    def test_legal_empty_result_is_success_not_error(self) -> None:
        wf_dir = self.tmp / "wf_empty"
        out = wf_dir / "outputs" / "empty.geojson"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps({"type": "FeatureCollection", "features": []}), encoding="utf-8"
        )

        h = self.start(lambda op, params, workspace: {
            "geojson": str(out), "feature_count": 0,
        })
        h.send({
            "type": "run_step",
            "request_id": "req-e",
            "workflow_id": "wf_empty",
            "step": {"id": "s1", "op": "filter_features", "params": {}},
        })
        result = h.wait_for(lambda m: m.get("type") == "step_result")
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["outputs"]["feature_count"], 0)

    def test_missing_artifact_fails_with_output_invalid(self) -> None:
        missing = self.tmp / "wf_bad" / "outputs" / "ghost.geojson"
        h = self.start(lambda op, params, workspace: {"geojson": str(missing)})
        h.send({
            "type": "run_step",
            "request_id": "req-b",
            "workflow_id": "wf_bad",
            "step": {"id": "s1", "op": "export_geojson", "params": {}},
        })
        result = h.wait_for(lambda m: m.get("type") == "step_result")
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], "OUTPUT_INVALID")
        self.assertEqual(result["request_id"], "req-b")

    def test_truncated_geojson_fails_validation(self) -> None:
        wf_dir = self.tmp / "wf_trunc"
        out = wf_dir / "outputs" / "trunc.geojson"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text('{"type": "FeatureCollection", "featur', encoding="utf-8")
        h = self.start(lambda op, params, workspace: {"geojson": str(out)})
        h.send({
            "type": "run_step",
            "request_id": "req-t",
            "workflow_id": "wf_trunc",
            "step": {"id": "s1", "op": "export_geojson", "params": {}},
        })
        result = h.wait_for(lambda m: m.get("type") == "step_result")
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], "OUTPUT_INVALID")

    def test_release_purges_temp_but_keeps_outputs(self) -> None:
        h = self.start()
        wf_dir = self.tmp / "wf_rel"
        steps_dir = wf_dir / "steps" / "s1"
        outputs_dir = wf_dir / "outputs"
        steps_dir.mkdir(parents=True, exist_ok=True)
        outputs_dir.mkdir(parents=True, exist_ok=True)
        (steps_dir / "intermediate.gpkg").write_bytes(b"tmp")
        (outputs_dir / "final.geojson").write_text("{}", encoding="utf-8")

        # Run one step so the worker creates the workspace for wf_rel.
        h.send({
            "type": "run_step",
            "request_id": "req-r",
            "workflow_id": "wf_rel",
            "step": {"id": "s0", "op": "probe", "params": {}},
        })
        ack = h.wait_for(lambda m: m.get("type") == "step_result")
        self.assertIsNotNone(ack)

        h.send({"type": "release_workflow", "workflow_id": "wf_rel"})
        msg = h.wait_for(lambda m: m.get("type") == "workflow_released")
        self.assertIsNotNone(msg)
        self.assertFalse(steps_dir.exists(), "per-step temp dir must be purged")
        self.assertTrue((outputs_dir / "final.geojson").exists(), "published output kept")


if __name__ == "__main__":
    unittest.main()
