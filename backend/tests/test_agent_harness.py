from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from backend.app.config import AppConfig
from backend.app.runtime import WebGISRuntime
from backend.app.services.agent_harness import AgentRun, HarnessPolicy, validate_json_contract
from backend.app.services.assistant import ASSISTANT_TOOL_INPUT_SCHEMAS
from backend.app.store import RuntimeStore


class AgentHarnessUnitTest(unittest.TestCase):
    def test_tool_contract_rejects_wrong_types_and_extra_fields(self) -> None:
        schema = ASSISTANT_TOOL_INPUT_SCHEMAS["toggle_layer"]

        self.assertEqual(validate_json_contract({"layer_id": "roads", "visible": True}, schema), "")
        self.assertIn("boolean", validate_json_contract({"layer_id": "roads", "visible": "true"}, schema))
        self.assertIn("未声明字段", validate_json_contract({"layer_id": "roads", "visible": True, "force": True}, schema))
        self.assertIn("必填字段", validate_json_contract({"layer_id": "roads"}, schema))
        self.assertIn("类型错误", validate_json_contract("x", {"type": "unsupported"}))

    def test_tool_contract_checks_any_of_and_nested_arrays(self) -> None:
        self.assertIn(
            "至少需要一组字段",
            validate_json_contract({}, ASSISTANT_TOOL_INPUT_SCHEMAS["open_material"]),
        )
        self.assertIn(
            "至少需要 2 项",
            validate_json_contract({"center": [104]}, ASSISTANT_TOOL_INPUT_SCHEMAS["set_view"]),
        )
        self.assertIn(
            "number",
            validate_json_contract({"center": [104, True]}, ASSISTANT_TOOL_INPUT_SCHEMAS["set_view"]),
        )

    def test_action_budget_and_repeat_guard_are_fail_closed(self) -> None:
        over_budget = AgentRun(
            HarnessPolicy(max_actions_per_run=1),
            job_id="job_budget",
            input_payload={"message": "private"},
        )
        actions = [
            {"tool_name": "switch_basemap", "tool_params": {"basemap_id": "a"}},
            {"tool_name": "switch_basemap", "tool_params": {"basemap_id": "b"}},
        ]
        self.assertIn("超过上限", over_budget.inspect_plan(actions))

        repeated = AgentRun(
            HarnessPolicy(max_actions_per_run=4, max_identical_actions=1),
            job_id="job_repeat",
            input_payload={},
        )
        duplicate = {"tool_name": "switch_basemap", "tool_params": {"basemap_id": "amap_light"}}
        self.assertIn("重复工具调用", repeated.inspect_plan([duplicate, duplicate]))

    def test_trace_is_privacy_safe_and_verify_on_stop_is_recorded(self) -> None:
        secret = "student-name-and-private-prompt"
        run = AgentRun(
            HarnessPolicy(),
            job_id="job_trace",
            input_payload={"message": secret, "api_key": "sk-private"},
        )
        result = {
            "assistant_message": "done",
            "actions_planned": [],
            "actions_executed": [],
            "requires_confirmation": False,
            "planner": "test",
        }
        verification = run.verify_result(result)
        report = run.finish("completed", "completed", verification=verification)
        serialized = json.dumps(report, ensure_ascii=False)

        self.assertTrue(report["verification"]["valid"])
        self.assertEqual(report["input_fingerprint"], report["input_fingerprint"][:16])
        self.assertNotIn(secret, serialized)
        self.assertNotIn("sk-private", serialized)
        self.assertTrue(any(event["type"] == "verification" for event in report["events"]))


class AgentHarnessRuntimeTest(unittest.TestCase):
    def build_runtime(self) -> tuple[WebGISRuntime, str]:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root_dir = Path(__file__).resolve().parents[2]
        config = AppConfig(root_dir=root_dir)
        config.data_dir = Path(temp_dir.name) / "backend" / "data"
        config.state_dir = config.data_dir / "state"
        config.uploads_dir = config.data_dir / "uploads"
        config.outputs_dir = config.data_dir / "outputs"
        config.state_file = config.state_dir / "runtime.json"
        config.assistant_v2_enabled = True
        config.ensure_dirs()
        runtime = WebGISRuntime(config=config, store=RuntimeStore(config.state_file))
        project = runtime.create_project()
        return runtime, project["project_id"]

    def wait_for_job(self, runtime: WebGISRuntime, job_id: str) -> dict:
        for _ in range(200):
            payload = runtime.get_job(job_id)
            if payload["status"] in {"completed", "failed"}:
                return payload
            time.sleep(0.05)
        self.fail(f"Job did not finish in time: {job_id}")

    def test_completed_job_exposes_trace_without_raw_prompt(self) -> None:
        runtime, project_id = self.build_runtime()
        private_prompt = "切换到底图，课堂口令 private-room-8172"
        runtime.session_engine.tool_planner.plan = lambda *args, **kwargs: {
            "assistant_message": "切换浅色底图。",
            "target": "webgis",
            "actions": [{"tool_name": "switch_basemap", "tool_params": {"basemap_id": "amap_light"}}],
            "planner": "test_stub",
        }

        accepted = runtime.submit_assistant_message(project_id, private_prompt, assistant_mode="tool")
        job = self.wait_for_job(runtime, accepted["job_id"])
        harness = job["result"]["harness"]

        self.assertEqual(job["status"], "completed")
        self.assertEqual(harness["status"], "completed")
        self.assertEqual(harness["stop_reason"], "completed")
        self.assertTrue(harness["verification"]["valid"])
        self.assertEqual(harness["usage"]["tool_calls"], 1)
        self.assertNotIn(private_prompt, json.dumps(harness, ensure_ascii=False))
        self.assertTrue(any(event["type"] == "tool" and event["status"] == "success" for event in harness["events"]))

    def test_invalid_tool_arguments_are_blocked_before_execution(self) -> None:
        runtime, project_id = self.build_runtime()
        runtime.session_engine.tool_planner.plan = lambda *args, **kwargs: {
            "assistant_message": "隐藏图层。",
            "target": "webgis",
            "actions": [{"tool_name": "toggle_layer", "tool_params": {"layer_id": "missing", "visible": "false"}}],
            "planner": "test_stub",
        }

        accepted = runtime.submit_assistant_message(project_id, "隐藏图层", assistant_mode="tool")
        job = self.wait_for_job(runtime, accepted["job_id"])
        result = job["result"]

        self.assertEqual(job["status"], "completed")
        self.assertEqual(result["planner"], "blocked")
        self.assertEqual(result["actions_executed"], [])
        self.assertIn("boolean", result["assistant_message"])
        self.assertEqual(result["harness"]["stop_reason"], "policy_blocked")
        self.assertTrue(
            any(
                event["type"] == "guardrail" and event["name"] == "tool_input_contract"
                for event in result["harness"]["events"]
            )
        )

    def test_failed_job_keeps_sanitized_failure_trace(self) -> None:
        runtime, project_id = self.build_runtime()
        runtime.session_engine.tool_planner.plan = lambda *args, **kwargs: {
            "assistant_message": "切换浅色底图。",
            "target": "webgis",
            "actions": [{"tool_name": "switch_basemap", "tool_params": {"basemap_id": "amap_light"}}],
            "planner": "test_stub",
        }
        runtime.session_engine.tool_executor.execute_webgis = lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("private tool failure detail")
        )

        accepted = runtime.submit_assistant_message(project_id, "切换底图", assistant_mode="tool")
        job = self.wait_for_job(runtime, accepted["job_id"])
        harness = job["result"]["harness"]

        self.assertEqual(job["status"], "failed")
        self.assertEqual(harness["status"], "failed")
        self.assertEqual(harness["usage"]["tool_failures"], 1)
        self.assertNotIn("private tool failure detail", json.dumps(harness, ensure_ascii=False))
        self.assertTrue(harness["error"]["fingerprint"])


if __name__ == "__main__":
    unittest.main()
