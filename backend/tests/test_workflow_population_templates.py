"""Population workflow coverage tests.

Matrix required by the population-workflow QA task:

* population_choropleth / hu_line_compare / classify_field each get a
  success, a missing-parameter and an execution-failure case;
* the preflight layer (dataset / field / CRS / reserved-op) is exercised
  directly, including "filled parameters survive a rejected run";
* a cancellation case asserts the dedicated ``cancelled`` status;
* a real-QGIS suite (skipped unless ``QGIS_ROOT``/``WEBGIS_AI_QGIS_ROOT``
  points at a local install) actually runs the three population workflows
  through the PyQGIS worker.

The structural tests use a stubbed worker manager, so they run in every
environment. The coverage report distinguishes those levels explicitly.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any, Dict

from backend.app.config import AppConfig
from backend.app.models import WorkflowRecord
from backend.app.services.pyqgis_worker.errors import make_error
from backend.app.services.workflow_executor import WorkflowExecutor
from backend.app.services.workflow_templates import (
    TEMPLATES,
    detect_template,
    expand_template,
    list_templates,
)
from backend.app.services.workflow_validator import validate_workflow
from backend.app.store import RuntimeStore


REPO_ROOT = Path(__file__).resolve().parents[2]

_DEMO_GEOJSON = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"name": "demo", "value": 1},
            "geometry": {"type": "Point", "coordinates": [116.4, 39.9]},
        }
    ],
}
BUILTIN_DIR = REPO_ROOT / "backend" / "app" / "data" / "builtin"

PROVINCES = "builtin:one_map/population/china_province_population_density.geojson"

POPULATION_CORE_TEMPLATES = ("population_choropleth", "hu_line_compare", "classify_field")


class _StubWorkerManager:
    """Never spawns a subprocess; returns canned step results."""

    def __init__(self, results: Dict[str, Dict[str, Any]] | None = None, fail_step: str = ""):
        self._results = results or {}
        self._fail_step = fail_step
        self.run_step_calls: list[tuple[str, str]] = []

    def init_warning(self):
        return None

    def run_step(self, workflow_id: str, step: Dict[str, Any], timeout: float | None = None) -> Dict[str, Any]:
        step_id = str(step.get("id"))
        self.run_step_calls.append((workflow_id, step_id))
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
                    "测试用失败：字段分级计算出错。",
                    step_id=step_id,
                ),
            }
        outputs = self._results.get(step_id) or {"layer": f"alias_{step_id}", "path": f"/fake/{step_id}.gpkg"}
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


class _CancellableStubManager(_StubWorkerManager):
    """run_step blocks until cancel_workflow() is called, then reports cancel."""

    def __init__(self) -> None:
        super().__init__()
        self._cancel_requested = threading.Event()

    def run_step(self, workflow_id: str, step: Dict[str, Any], timeout: float | None = None) -> Dict[str, Any]:
        self.run_step_calls.append((workflow_id, str(step.get("id"))))
        self._cancel_requested.wait(timeout=30.0)
        return {
            "type": "step_result",
            "workflow_id": workflow_id,
            "step_id": str(step.get("id")),
            "status": "error",
            "outputs": {},
            "error": make_error(
                "STEP_CANCELLED",
                "step cancelled during execution",
                "步骤已取消。",
                step_id=str(step.get("id")),
            ),
        }

    def cancel_workflow(self, workflow_id: str) -> int:
        self._cancel_requested.set()
        return 1


def _make_config() -> AppConfig:
    tmp = Path(tempfile.mkdtemp(prefix="webgis_wf_pop_"))
    config = AppConfig()
    config.data_dir = tmp / "backend" / "data"
    config.state_dir = config.data_dir / "state"
    config.uploads_dir = config.data_dir / "uploads"
    config.outputs_dir = config.data_dir / "outputs"
    config.workflows_dir = config.data_dir / "workflows"
    config.state_file = config.state_dir / "runtime.json"
    # Point the builtin dataset root at the repo so template defaults resolve.
    config.builtin_dir = BUILTIN_DIR
    config.ensure_dirs()
    return config


def _wait_for_status(store: RuntimeStore, workflow_id: str, timeout: float = 8.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        record = store.get_workflow(workflow_id)
        if record and record.status in {"success", "error", "cancelled"}:
            return record
        time.sleep(0.05)
    return store.get_workflow(workflow_id)


class PopulationWorkflowMatrixTests(unittest.TestCase):
    """Success / missing-param / failure for the three core population flows."""

    def setUp(self) -> None:
        self.config = _make_config()
        self.store = RuntimeStore(self.config.state_file)

    def _wait_for_status(self, executor: WorkflowExecutor, workflow_id: str, timeout: float = 8.0):
        return _wait_for_status(self.store, workflow_id, timeout)

    def _submit_template(self, template_id: str, parameters: Dict[str, Any], manager):
        match = expand_template(template_id, "课堂人口分析", {"project_id": "p1", **parameters})
        record = WorkflowRecord.create(
            project_id="p1",
            user_message="课堂人口分析",
            intent=match.intent,
            template_id=match.template_id,
            mode="template",
            workflow_json=match.workflow,
        )
        executor = WorkflowExecutor(self.config, self.store, worker_manager=manager)
        executor.submit(record)
        return record, executor

    # -- success -------------------------------------------------------

    def test_population_choropleth_success_registers_geojson_artifact(self) -> None:
        manager = _StubWorkerManager()
        match = expand_template(
            "population_choropleth", "课堂人口分析", {"project_id": "p1", "dataset": PROVINCES}
        )
        record = WorkflowRecord.create(
            project_id="p1",
            user_message="课堂人口分析",
            intent=match.intent,
            template_id=match.template_id,
            mode="template",
            workflow_json=match.workflow,
        )
        # Give the choropleth step a real output file so the artifact can be
        # registered (mirrors what the real handler does).
        out_geojson = self.config.workflow_dir(record.workflow_id) / "outputs" / "choropleth.geojson"
        out_geojson.parent.mkdir(parents=True, exist_ok=True)
        out_geojson.write_text(json.dumps(_DEMO_GEOJSON), encoding="utf-8")
        manager._results["s4"] = {"geojson": str(out_geojson), "path": str(out_geojson)}
        executor = WorkflowExecutor(self.config, self.store, worker_manager=manager)
        executor.submit(record)
        final = self._wait_for_status(executor, record.workflow_id)
        self.assertEqual(final.status, "success")
        kinds = {a["kind"] for a in final.artifacts}
        self.assertIn("geojson", kinds)
        self.assertTrue(manager.run_step_calls)

    def test_hu_line_compare_success_runs_all_steps(self) -> None:
        manager = _StubWorkerManager()
        record, executor = self._submit_template(
            "hu_line_compare", {"province_dataset": PROVINCES}, manager
        )
        final = self._wait_for_status(executor, record.workflow_id)
        self.assertEqual(final.status, "success")
        self.assertEqual(len(manager.run_step_calls), len(final.steps))

    def test_classify_field_success(self) -> None:
        manager = _StubWorkerManager()
        record, executor = self._submit_template(
            "classify_field", {"dataset": PROVINCES, "field": "population", "classes": 5}, manager
        )
        final = self._wait_for_status(executor, record.workflow_id)
        self.assertEqual(final.status, "success")

    # -- missing parameter ----------------------------------------------

    def test_choropleth_missing_field_is_rejected_before_worker(self) -> None:
        manager = _StubWorkerManager()
        workflow = expand_template("population_choropleth", "人口密度图", {"project_id": "p1", "dataset": PROVINCES})
        for step in workflow.workflow["steps"]:
            if step["op"] == "choropleth":
                step["params"].pop("field")
        record = WorkflowRecord.create(project_id="p1", workflow_json=workflow.workflow)
        executor = WorkflowExecutor(self.config, self.store, worker_manager=manager)
        executor.submit(record)
        final = self.store.get_workflow(record.workflow_id)
        self.assertEqual(final.status, "error")
        self.assertEqual(final.error["code"], "VALIDATION_FAILED")
        codes = {e["code"] for e in final.error["details"]["errors"]}
        self.assertIn("STEP_PARAM_MISSING", codes)
        self.assertEqual(manager.run_step_calls, [])

    def test_classify_missing_field_is_rejected_before_worker(self) -> None:
        manager = _StubWorkerManager()
        workflow = expand_template(
            "classify_field", "字段分级", {"project_id": "p1", "dataset": PROVINCES, "field": "population"}
        )
        for step in workflow.workflow["steps"]:
            if step["op"] == "classify":
                step["params"].pop("field")
        record = WorkflowRecord.create(project_id="p1", workflow_json=workflow.workflow)
        executor = WorkflowExecutor(self.config, self.store, worker_manager=manager)
        executor.submit(record)
        final = self.store.get_workflow(record.workflow_id)
        self.assertEqual(final.status, "error")
        self.assertEqual(manager.run_step_calls, [])

    def test_hu_line_missing_source_is_rejected_before_worker(self) -> None:
        manager = _StubWorkerManager()
        workflow = expand_template("hu_line_compare", "胡焕庸线", {"project_id": "p1"})
        for step in workflow.workflow["steps"]:
            if step["op"] == "load_layer":
                step["params"].pop("source")
        record = WorkflowRecord.create(project_id="p1", workflow_json=workflow.workflow)
        executor = WorkflowExecutor(self.config, self.store, worker_manager=manager)
        executor.submit(record)
        final = self.store.get_workflow(record.workflow_id)
        self.assertEqual(final.status, "error")
        self.assertEqual(final.error["code"], "VALIDATION_FAILED")
        self.assertEqual(manager.run_step_calls, [])

    # -- execution failure ----------------------------------------------

    def test_population_choropleth_step_failure_marks_workflow_error(self) -> None:
        manager = _StubWorkerManager(fail_step="s4")
        record, executor = self._submit_template("population_choropleth", {"dataset": PROVINCES}, manager)
        final = self._wait_for_status(executor, record.workflow_id)
        self.assertEqual(final.status, "error")
        self.assertEqual(final.error["code"], "PROCESSING_FAILED")
        failed_steps = [s for s in final.steps if s["status"] == "error"]
        self.assertTrue(failed_steps)
        self.assertEqual(failed_steps[0]["error"]["code"], "PROCESSING_FAILED")
        # The teacher-facing message is the stub's plain-language text.
        self.assertIn("测试用失败", failed_steps[0]["error"]["user_friendly"])

    def test_hu_line_step_failure_marks_workflow_error(self) -> None:
        manager = _StubWorkerManager(fail_step="s6")
        record, executor = self._submit_template("hu_line_compare", {"province_dataset": PROVINCES}, manager)
        final = self._wait_for_status(executor, record.workflow_id)
        self.assertEqual(final.status, "error")
        self.assertEqual(final.error["code"], "PROCESSING_FAILED")

    def test_classify_step_failure_marks_workflow_error(self) -> None:
        manager = _StubWorkerManager(fail_step="s3")
        record, executor = self._submit_template(
            "classify_field", {"dataset": PROVINCES, "field": "population"}, manager
        )
        final = self._wait_for_status(executor, record.workflow_id)
        self.assertEqual(final.status, "error")
        self.assertEqual(final.error["code"], "PROCESSING_FAILED")


class WorkflowPreflightTests(unittest.TestCase):
    """Dataset / field / CRS preflight and reserved-op rejection."""

    def setUp(self) -> None:
        self.config = _make_config()
        self.store = RuntimeStore(self.config.state_file)

    def _executor_with(self, manager) -> WorkflowExecutor:
        return WorkflowExecutor(self.config, self.store, worker_manager=manager)

    def test_missing_dataset_is_caught_before_run(self) -> None:
        manager = _StubWorkerManager()
        match = expand_template(
            "population_choropleth", "人口密度图",
            {"project_id": "p1", "dataset": "builtin:one_map/population/does_not_exist.geojson"},
        )
        record = WorkflowRecord.create(
            project_id="p1", template_id="population_choropleth", workflow_json=match.workflow
        )
        self._executor_with(manager).submit(record)
        final = self.store.get_workflow(record.workflow_id)
        self.assertEqual(final.status, "error")
        self.assertEqual(final.error["code"], "VALIDATION_FAILED")
        issues = final.error["details"]["errors"]
        self.assertTrue(any(i["code"] == "DATASET_NOT_FOUND" for i in issues))
        # The teacher-readable message names the missing dataset.
        self.assertIn("does_not_exist.geojson", final.error["user_friendly"])
        # No doomed background task was started.
        self.assertEqual(manager.run_step_calls, [])
        # The submitted parameters stay inspectable so the teacher can fix
        # them and rerun instead of retyping.
        self.assertEqual(final.template_id, "population_choropleth")
        self.assertEqual(final.workflow_json["context"]["project_id"], "p1")

    def test_missing_field_names_available_fields(self) -> None:
        manager = _StubWorkerManager()
        match = expand_template(
            "population_choropleth", "人口密度图",
            {"project_id": "p1", "dataset": PROVINCES},
        )
        for step in match.workflow["steps"]:
            if step["op"] == "choropleth":
                step["params"]["field"] = "no_such_field"
        record = WorkflowRecord.create(project_id="p1", workflow_json=match.workflow)
        self._executor_with(manager).submit(record)
        final = self.store.get_workflow(record.workflow_id)
        self.assertEqual(final.status, "error")
        issues = final.error["details"]["errors"]
        field_issues = [i for i in issues if i["code"] == "FIELD_NOT_FOUND"]
        self.assertTrue(field_issues)
        self.assertIn("可用字段", final.error["user_friendly"])
        self.assertIn("population", final.error["user_friendly"])
        self.assertEqual(manager.run_step_calls, [])

    def test_expression_field_typo_is_caught(self) -> None:
        manager = _StubWorkerManager()
        match = expand_template(
            "population_choropleth", "人口密度图",
            {"project_id": "p1", "dataset": PROVINCES, "area_field": "no_area_here"},
        )
        record = WorkflowRecord.create(project_id="p1", workflow_json=match.workflow)
        self._executor_with(manager).submit(record)
        final = self.store.get_workflow(record.workflow_id)
        self.assertEqual(final.status, "error")
        issues = final.error["details"]["errors"]
        self.assertTrue(any(i["code"] == "FIELD_NOT_FOUND" for i in issues))
        self.assertEqual(manager.run_step_calls, [])

    def test_nonblocking_crs_warning_does_not_stop_submission(self) -> None:
        manager = _StubWorkerManager()
        # Build a tiny dataset declaring a projected CRS; preflight must warn
        # but still let the workflow run.
        dataset_path = self.config.data_dir / "builtin" / "preflight" / "projected.geojson"
        dataset_path.parent.mkdir(parents=True, exist_ok=True)
        dataset_path.write_text(json.dumps({
            "type": "FeatureCollection",
            "crs": {"type": "name", "properties": {"name": "EPSG:3857"}},
            "features": [{
                "type": "Feature",
                "properties": {"name": "a", "population": 100, "density": 12.5},
                "geometry": {"type": "Point", "coordinates": [1, 1]},
            }],
        }), encoding="utf-8")
        match = expand_template(
            "population_choropleth", "人口密度图",
            {"project_id": "p1", "dataset": "builtin:preflight/projected.geojson"},
        )
        record = WorkflowRecord.create(project_id="p1", workflow_json=match.workflow)
        executor = self._executor_with(manager)
        executor.submit(record)
        final = _wait_for_status(self.store, record.workflow_id)
        self.assertEqual(final.status, "success")
        self.assertTrue(manager.run_step_calls)

    def test_reserved_op_rejected_before_submission(self) -> None:
        manager = _StubWorkerManager()
        workflow = {
            "version": "1.0",
            "intent": "热力图",
            "steps": [
                {"id": "s1", "op": "load_layer", "params": {"source": PROVINCES}},
                {"id": "s2", "op": "heatmap", "params": {"input": "${s1.layer}"}, "depends_on": ["s1"]},
            ],
        }
        record = WorkflowRecord.create(project_id="p1", workflow_json=workflow)
        self._executor_with(manager).submit(record)
        final = self.store.get_workflow(record.workflow_id)
        self.assertEqual(final.status, "error")
        self.assertEqual(final.error["code"], "VALIDATION_FAILED")
        codes = {e["code"] for e in final.error["details"]["errors"]}
        self.assertIn("STEP_OP_NOT_IMPLEMENTED", codes)
        self.assertIn("尚未实现", final.error["user_friendly"])
        self.assertEqual(manager.run_step_calls, [])

    def test_preflight_passes_valid_builtin_dataset(self) -> None:
        from backend.app.services.workflow_executor import run_preflight

        match = expand_template(
            "population_choropleth", "人口密度图", {"project_id": "p1", "dataset": PROVINCES}
        )
        errors, warnings = run_preflight(self.config, match.workflow)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])


class WorkflowCancelStatusTests(unittest.TestCase):
    """A cancelled run ends in the dedicated ``cancelled`` status."""

    def setUp(self) -> None:
        self.config = _make_config()
        self.store = RuntimeStore(self.config.state_file)

    def test_cancelled_step_marks_workflow_cancelled(self) -> None:
        manager = _CancellableStubManager()
        match = expand_template(
            "population_choropleth", "人口密度图", {"project_id": "p1", "dataset": PROVINCES}
        )
        record = WorkflowRecord.create(project_id="p1", workflow_json=match.workflow)
        executor = WorkflowExecutor(self.config, self.store, worker_manager=manager)
        executor.submit(record)
        deadline = time.time() + 15.0
        while time.time() < deadline and not manager.run_step_calls:
            time.sleep(0.05)
        cancelled = executor.cancel_workflow(record.workflow_id)
        self.assertEqual(cancelled, 1)
        final = None
        deadline = time.time() + 15.0
        while time.time() < deadline:
            current = self.store.get_workflow(record.workflow_id)
            if current and current.status in {"success", "error", "cancelled"}:
                final = current
                break
            time.sleep(0.05)
        self.assertIsNotNone(final)
        self.assertEqual(final.status, "cancelled")
        self.assertEqual(final.error["code"], "STEP_CANCELLED")
        self.assertIn("已取消", final.error["user_friendly"])
        # The terminal event carries the record so the UI can show 已取消.
        terminal = [e for e in executor.bus.history(record.workflow_id) if e.type == "workflow_error"]
        self.assertTrue(terminal)
        self.assertEqual(terminal[-1].payload["workflow"]["status"], "cancelled")


class TemplateCoverageTests(unittest.TestCase):
    """All seven templates exist, expand and validate; hu_line really splits."""

    def test_seven_templates_listed(self) -> None:
        listed = {item["id"] for item in list_templates()}
        self.assertEqual(listed, set(TEMPLATES.keys()))
        self.assertEqual(
            listed,
            {
                "population_choropleth",
                "facility_buffer",
                "hu_line_compare",
                "clip_to_region",
                "overlay_intersection",
                "spatial_join_attributes",
                "classify_field",
            },
        )

    def test_every_template_expands_and_validates(self) -> None:
        for template_id in TEMPLATES:
            with self.subTest(template=template_id):
                match = expand_template(template_id, "人口课堂分析", {"project_id": "p1"})
                result = validate_workflow(match.workflow)
                self.assertTrue(
                    result.valid,
                    msg=[e.to_dict() for e in result.errors],
                )

    def test_detect_template_keywords(self) -> None:
        self.assertEqual(detect_template("制作人口密度分级设色图"), "population_choropleth")
        self.assertEqual(detect_template("对比胡焕庸线两侧"), "hu_line_compare")
        self.assertEqual(detect_template("对学校做缓冲区"), "facility_buffer")
        self.assertEqual(detect_template("把人口裁剪到长三角"), "clip_to_region")
        self.assertEqual(detect_template("求两个图层的交集"), "overlay_intersection")
        self.assertEqual(detect_template("空间连接行政区属性"), "spatial_join_attributes")
        self.assertEqual(detect_template("对人口字段做分级"), "classify_field")
        self.assertIsNone(detect_template("今天天气怎么样"))

    def test_hu_line_compare_contains_real_east_west_split(self) -> None:
        match = expand_template(
            "hu_line_compare", "胡焕庸线对比", {"project_id": "p1", "province_dataset": PROVINCES}
        )
        ops = [step["op"] for step in match.workflow["steps"]]
        # The comparison must be computed in the workflow, not just claimed
        # in the stats title.
        self.assertIn("calculate_field", ops)  # hu_side derivation
        self.assertEqual(ops.count("filter_features"), 2)
        self.assertEqual(ops.count("export_geojson"), 2)
        side_steps = [s for s in match.workflow["steps"] if s["op"] == "calculate_field"]
        side_fields = {s["params"]["field"] for s in side_steps}
        self.assertIn("hu_side", side_fields)
        expressions = [s["params"]["expression"] for s in side_steps if s["params"]["field"] == "hu_side"]
        self.assertTrue(expressions)
        self.assertIn("centroid", expressions[0])
        stats_step = next(s for s in match.workflow["steps"] if s["op"] == "aggregate_stats")
        self.assertEqual(stats_step["params"]["label_field"], "hu_side")
        self.assertGreaterEqual(stats_step["params"]["top"], 34)
        filter_steps = [s for s in match.workflow["steps"] if s["op"] == "filter_features"]
        expressions = [s["params"]["expression"] for s in filter_steps]
        self.assertIn("\"hu_side\" = 'east'", expressions)
        self.assertIn("\"hu_side\" = 'west'", expressions)


class RealQgisPopulationRunTests(unittest.TestCase):
    """Actually run the three population workflows on a local QGIS install.

    Skipped unless ``QGIS_ROOT`` (or ``WEBGIS_AI_QGIS_ROOT``) points at a
    QGIS install with ``bin/python.exe`` — CI environments without QGIS stay
    green while running the full matrix locally.
    """

    @classmethod
    def _qgis_available(cls) -> bool:
        root = os.environ.get("WEBGIS_AI_QGIS_ROOT") or os.environ.get("QGIS_ROOT") or ""
        if not root or not Path(root).exists():
            return False
        return (Path(root) / "bin" / "python.exe").exists()

    def setUp(self) -> None:
        if not self._qgis_available():
            self.skipTest(
                "QGIS_ROOT not configured; real-worker population runs are covered by scratch/ coverage report"
            )
        self.config = _make_config()
        root = os.environ.get("WEBGIS_AI_QGIS_ROOT") or os.environ.get("QGIS_ROOT")
        self.config.qgis_root = root
        python = os.environ.get("WEBGIS_AI_QGIS_PYTHON")
        self.config.qgis_python = python or str(Path(root) / "bin" / "python.exe")
        # The worker resolves builtin: datasets relative to WEBGIS_AI_DATA_DIR
        # (<data>/../app/data/builtin), so point it at the repo's real data
        # dir — same layout as production. Workflow outputs still land in the
        # per-test tmp dir via config.workflows_dir.
        self._previous_data_dir = os.environ.get("WEBGIS_AI_DATA_DIR")
        os.environ["WEBGIS_AI_DATA_DIR"] = str(REPO_ROOT / "backend" / "data")
        self.store = RuntimeStore(self.config.state_file)

    def tearDown(self) -> None:
        if self._previous_data_dir is None:
            os.environ.pop("WEBGIS_AI_DATA_DIR", None)
        else:
            os.environ["WEBGIS_AI_DATA_DIR"] = self._previous_data_dir

    def _run_template(self, template_id: str, parameters: Dict[str, Any], timeout: float = 300.0) -> WorkflowRecord:
        match = expand_template(template_id, "人口课堂真实运行", {"project_id": "p1", **parameters})
        record = WorkflowRecord.create(
            project_id="p1",
            user_message="人口课堂真实运行",
            intent=match.intent,
            template_id=match.template_id,
            mode="template",
            workflow_json=match.workflow,
        )
        executor = WorkflowExecutor(self.config, self.store)
        try:
            executor.submit(record)
            deadline = time.time() + timeout
            final = None
            while time.time() < deadline:
                current = self.store.get_workflow(record.workflow_id)
                if current and current.status in {"success", "error", "cancelled"}:
                    final = current
                    break
                time.sleep(0.25)
            self.assertIsNotNone(final, "workflow did not reach a terminal status")
            self.assertEqual(
                final.status, "success",
                msg=json.dumps(final.error, ensure_ascii=False) + json.dumps(
                    [
                        {"id": s.get("id"), "op": s.get("op"), "status": s.get("status"),
                         "error": (s.get("error") or {}).get("user_friendly")}
                        for s in (final.steps or [])
                    ],
                    ensure_ascii=False,
                ),
            )
            kinds = {a["kind"] for a in final.artifacts}
            self.assertIn("geojson", kinds)
            # The geojson artifact must be a real, parseable file on disk.
            geojson_artifact = next(a for a in final.artifacts if a["kind"] == "geojson")
            path = self.config.workflow_dir(record.workflow_id) / geojson_artifact["relative_path"]
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertGreater(len(payload.get("features", [])), 0)
            return final
        finally:
            executor.shutdown()

    def test_population_choropleth_real_run(self) -> None:
        final = self._run_template("population_choropleth", {"dataset": PROVINCES})
        kinds = {a["kind"] for a in final.artifacts}
        self.assertIn("stats", kinds)
        self.assertIn("png", kinds)

    def test_hu_line_compare_real_run_splits_sides(self) -> None:
        final = self._run_template("hu_line_compare", {"province_dataset": PROVINCES})
        # The east/west exports must exist as separate real files.
        relative = sorted(a["relative_path"] for a in final.artifacts if a["kind"] == "geojson")
        self.assertIn("outputs/hu_east_side.geojson", relative)
        self.assertIn("outputs/hu_west_side.geojson", relative)
        east = json.loads(
            (self.config.workflow_dir(final.workflow_id) / "outputs" / "hu_east_side.geojson").read_text(encoding="utf-8")
        )
        west = json.loads(
            (self.config.workflow_dir(final.workflow_id) / "outputs" / "hu_west_side.geojson").read_text(encoding="utf-8")
        )
        east_names = {f["properties"]["name"] for f in east["features"]}
        west_names = {f["properties"]["name"] for f in west["features"]}
        # The split must be non-trivial: both sides populated, no province on
        # both sides, and every province accounted for.
        self.assertGreater(len(east_names), 0)
        self.assertGreater(len(west_names), 0)
        self.assertFalse(east_names & west_names)
        self.assertEqual(len(east_names) + len(west_names), 34)
        # Sanity against the classic Hu Line story: the populous east holds
        # the overwhelming majority of provinces.
        self.assertGreater(len(east_names), len(west_names))
        self.assertIn("上海市", east_names)
        self.assertIn("新疆维吾尔自治区", west_names)

    def test_classify_field_real_run(self) -> None:
        final = self._run_template(
            "classify_field", {"dataset": PROVINCES, "field": "population", "classes": 5}
        )
        geojson_artifact = next(a for a in final.artifacts if a["kind"] == "geojson")
        path = self.config.workflow_dir(final.workflow_id) / geojson_artifact["relative_path"]
        payload = json.loads(path.read_text(encoding="utf-8"))
        properties = payload["features"][0]["properties"]
        self.assertIn("population_class", properties)
        class_values = {int(f["properties"]["population_class"]) for f in payload["features"]}
        self.assertLessEqual(max(class_values), 4)
        self.assertGreaterEqual(min(class_values), 0)


if __name__ == "__main__":
    unittest.main()
