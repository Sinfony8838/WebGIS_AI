from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from backend.app.config import AppConfig
from backend.app.models import ProjectRecord
from backend.app.runtime import WebGISRuntime
from backend.app.services.assistant import AssistantService
from backend.app.services.llm_planner import LLMPlanner
from backend.app.services.qgis_bridge import QgisBridgeClient
from backend.app.store import RuntimeStore


class _FailingMiniMaxClient:
    def chat_completion(self, messages, temperature=0.2):  # noqa: ANN001, ANN201
        raise RuntimeError("minimax unavailable")


class _SuccessMiniMaxClient:
    def __init__(self, payload: str):
        self.payload = payload

    def chat_completion(self, messages, temperature=0.2):  # noqa: ANN001, ANN201
        return self.payload


class _StubQgisBridge:
    def fallback_plan(self, message: str):  # noqa: ANN001, ANN201
        return {
            "assistant_message": "qgis fallback",
            "target": "qgis",
            "actions": [{"tool_name": "get_layers", "tool_params": {}}],
        }


class LlmAndQgisIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = AppConfig()
        self.rule_planner = AssistantService(self.config)
        self.project = ProjectRecord.create(base_map=self.config.default_basemap())

    def test_llm_failure_falls_back_to_rule_planner(self) -> None:
        planner = LLMPlanner(_FailingMiniMaxClient(), self.rule_planner, _StubQgisBridge())
        plan = planner.plan_actions(
            "解释当前地图",
            self.project,
            map_context={"center": [104, 35], "extent": [78, 18, 132, 50]},
            target="webgis",
        )
        self.assertEqual(plan["planner"], "rule_fallback")
        self.assertEqual(plan["target"], "webgis")
        self.assertTrue(plan["actions"])

    def test_voice_mode_uses_voice_rule_before_llm(self) -> None:
        planner = LLMPlanner(_FailingMiniMaxClient(), self.rule_planner, _StubQgisBridge())
        plan = planner.plan_actions(
            "我们把目光转向上海区域",
            self.project,
            map_context={"center": [104, 35], "extent": [78, 18, 132, 50]},
            target="webgis",
            input_mode="voice",
        )
        self.assertEqual(plan["planner"], "voice_rule")
        self.assertEqual(plan["target"], "webgis")
        self.assertEqual(plan["actions"][0]["tool_name"], "set_view")

    def test_deterministic_webgis_text_action_uses_rule_preflight(self) -> None:
        payload = (
            '{"assistant_message":"讲解当前地图","target":"webgis",'
            '"actions":[{"tool_name":"explain_current_view","tool_params":{"focus":"地图"}}]}'
        )
        planner = LLMPlanner(_SuccessMiniMaxClient(payload), self.rule_planner, _StubQgisBridge())
        plan = planner.plan_actions(
            "切换到高德影像底图",
            self.project,
            map_context={"center": [104, 35], "extent": [78, 18, 132, 50]},
            target="webgis",
        )
        self.assertEqual(plan["planner"], "rule_preflight")
        self.assertEqual(plan["target"], "webgis")
        self.assertEqual(plan["actions"][0]["tool_name"], "switch_basemap")
        self.assertEqual(plan["actions"][0]["tool_params"]["basemap_id"], "amap_imagery")

    def test_llm_valid_json_for_qgis_is_accepted(self) -> None:
        payload = '{"assistant_message":"执行 QGIS 检查","target":"qgis","actions":[{"tool_name":"get_layers","tool_params":{}}]}'
        planner = LLMPlanner(_SuccessMiniMaxClient(payload), self.rule_planner, _StubQgisBridge())
        plan = planner.plan_actions("读取 QGIS 图层", self.project, target="qgis")
        self.assertEqual(plan["planner"], "minimax")
        self.assertEqual(plan["target"], "qgis")
        self.assertEqual(plan["actions"][0]["tool_name"], "get_layers")

    def test_llm_json_embedded_in_text_is_extracted(self) -> None:
        payload = (
            "Execution plan:\n"
            "```json\n"
            '{"assistant_message":"执行 QGIS 检查","target":"qgis","actions":[{"tool_name":"get_layers","tool_params":{}}]}\n'
            "```\n"
            "End."
        )
        planner = LLMPlanner(_SuccessMiniMaxClient(payload), self.rule_planner, _StubQgisBridge())
        plan = planner.plan_actions("读取 QGIS 图层", self.project, target="qgis")
        self.assertEqual(plan["planner"], "minimax")
        self.assertEqual(plan["target"], "qgis")
        self.assertEqual(plan["actions"][0]["tool_name"], "get_layers")

    def test_llm_action_count_is_capped(self) -> None:
        actions = ",".join(['{"tool_name":"get_layers","tool_params":{}}' for _ in range(25)])
        payload = '{"assistant_message":"批量动作","target":"qgis","actions":[' + actions + "]}"
        planner = LLMPlanner(_SuccessMiniMaxClient(payload), self.rule_planner, _StubQgisBridge())
        plan = planner.plan_actions("读取 QGIS 图层", self.project, target="qgis")
        self.assertEqual(plan["planner"], "minimax")
        self.assertEqual(len(plan["actions"]), 12)

    def test_llm_unknown_tool_is_blocked_and_fallback_used(self) -> None:
        payload = (
            '{"assistant_message":"危险动作","target":"qgis","actions":'
            '[{"tool_name":"run_python_code","tool_params":{"code":"print(1)"}}]}'
        )
        planner = LLMPlanner(_SuccessMiniMaxClient(payload), self.rule_planner, _StubQgisBridge())
        plan = planner.plan_actions("执行未知工具", self.project, target="qgis")
        self.assertEqual(plan["planner"], "rule_fallback")
        self.assertEqual(plan["target"], "qgis")
        self.assertEqual(plan["actions"][0]["tool_name"], "get_layers")

    def test_qgis_bridge_blocks_run_python_code(self) -> None:
        bridge = QgisBridgeClient(self.config)
        with self.assertRaises(ValueError):
            bridge.call("run_python_code")

    def test_runtime_accepts_assistant_target(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root_dir = Path(__file__).resolve().parents[2]
        config = AppConfig(root_dir=root_dir)
        config.data_dir = Path(temp_dir.name) / "backend" / "data"
        config.state_dir = config.data_dir / "state"
        config.uploads_dir = config.data_dir / "uploads"
        config.outputs_dir = config.data_dir / "outputs"
        config.state_file = config.state_dir / "runtime.json"
        config.ensure_dirs()
        runtime = WebGISRuntime(config=config, store=RuntimeStore(config.state_file))
        project = runtime.create_project()

        response = runtime.submit_assistant_message(project["project_id"], "读取图层", target="qgis")
        job = runtime.store.get_job(response["job_id"])
        self.assertIsNotNone(job)
        self.assertEqual(job.request.get("target"), "qgis")
        for _ in range(20):
            current = runtime.store.get_job(response["job_id"])
            if current and current.status in {"completed", "failed"}:
                break
            time.sleep(0.05)

    def test_runtime_records_voice_input_mode(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root_dir = Path(__file__).resolve().parents[2]
        config = AppConfig(root_dir=root_dir)
        config.data_dir = Path(temp_dir.name) / "backend" / "data"
        config.state_dir = config.data_dir / "state"
        config.uploads_dir = config.data_dir / "uploads"
        config.outputs_dir = config.data_dir / "outputs"
        config.state_file = config.state_dir / "runtime.json"
        config.ensure_dirs()
        runtime = WebGISRuntime(config=config, store=RuntimeStore(config.state_file))
        project = runtime.create_project()

        response = runtime.submit_assistant_message(
            project["project_id"],
            "我们把目光转向上海区域",
            target="webgis",
            input_mode="voice",
        )
        job = runtime.store.get_job(response["job_id"])
        self.assertIsNotNone(job)
        self.assertEqual(job.request.get("input_mode"), "voice")
        for _ in range(20):
            current = runtime.store.get_job(response["job_id"])
            if current and current.status in {"completed", "failed"}:
                break
            time.sleep(0.05)

    def test_runtime_records_llm_fallback_reason(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root_dir = Path(__file__).resolve().parents[2]
        config = AppConfig(root_dir=root_dir)
        config.data_dir = Path(temp_dir.name) / "backend" / "data"
        config.state_dir = config.data_dir / "state"
        config.uploads_dir = config.data_dir / "uploads"
        config.outputs_dir = config.data_dir / "outputs"
        config.state_file = config.state_dir / "runtime.json"
        config.ensure_dirs()
        runtime = WebGISRuntime(config=config, store=RuntimeStore(config.state_file))
        runtime.llm_planner = LLMPlanner(_FailingMiniMaxClient(), AssistantService(config), _StubQgisBridge())
        project = runtime.create_project()

        response = runtime.submit_assistant_message(project["project_id"], "解释当前地图", target="webgis")
        current = None
        for _ in range(20):
            current = runtime.store.get_job(response["job_id"])
            if current and current.status in {"completed", "failed"}:
                break
            time.sleep(0.05)

        self.assertIsNotNone(current)
        self.assertEqual(current.result.get("planner"), "rule_fallback")
        self.assertIn("minimax unavailable", current.result.get("llm_fallback_reason", ""))


if __name__ == "__main__":
    unittest.main()
