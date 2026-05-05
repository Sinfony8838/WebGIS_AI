import tempfile
import time
import unittest
from pathlib import Path
from typing import Tuple

from backend.app.config import AppConfig
from backend.app.runtime import WebGISRuntime
from backend.app.store import RuntimeStore


class AssistantV2RuntimeTest(unittest.TestCase):
    def build_runtime(self, enable_v2: bool = True) -> Tuple[WebGISRuntime, str]:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root_dir = Path(__file__).resolve().parents[2]
        config = AppConfig(root_dir=root_dir)
        config.data_dir = Path(temp_dir.name) / "backend" / "data"
        config.state_dir = config.data_dir / "state"
        config.uploads_dir = config.data_dir / "uploads"
        config.outputs_dir = config.data_dir / "outputs"
        config.state_file = config.state_dir / "runtime.json"
        config.assistant_v2_enabled = enable_v2
        config.ensure_dirs()
        runtime = WebGISRuntime(config=config, store=RuntimeStore(config.state_file))
        project = runtime.create_project()
        return runtime, project["project_id"]

    def wait_for_job(self, runtime: WebGISRuntime, job_id: str, max_iterations: int = 200) -> dict:
        for _ in range(max_iterations):
            payload = runtime.get_job(job_id)
            if payload["status"] in {"completed", "failed"}:
                return payload
            time.sleep(0.05)
        self.fail(f"Job did not finish in time: {job_id}")

    def test_knowledge_mode_returns_citations_without_tool_actions(self) -> None:
        runtime, project_id = self.build_runtime(enable_v2=False)

        response = runtime.submit_assistant_message(project_id, "what is hu huanyong line", assistant_mode="knowledge")
        job = self.wait_for_job(runtime, response["job_id"])

        self.assertEqual(job["result"]["intent"], "knowledge")
        self.assertEqual(job["result"]["actions_planned"], [])
        self.assertEqual(job["result"]["actions_executed"], [])
        self.assertTrue(job["result"]["citations"])

    def test_knowledge_mode_answers_assistant_identity_without_map_grounding(self) -> None:
        runtime, project_id = self.build_runtime(enable_v2=False)

        response = runtime.submit_assistant_message(
            project_id,
            "你是谁",
            assistant_mode="knowledge",
            map_context={"zoom": 4, "visible_layers": [{"name": "欧亚区域框架"}, {"name": "课堂关注点"}]},
        )
        job = self.wait_for_job(runtime, response["job_id"])

        self.assertEqual(job["result"]["knowledge"]["answer_type"], "assistant_identity")
        self.assertIn("超级地理助手", job["result"]["assistant_message"])
        self.assertNotIn("欧亚区域框架", job["result"]["assistant_message"])
        self.assertNotIn("这类问题属于助手身份说明", job["result"]["assistant_message"])
        self.assertFalse(job["result"]["citations"])

    def test_knowledge_mode_answers_assistant_model_from_runtime_config(self) -> None:
        runtime, project_id = self.build_runtime(enable_v2=False)

        response = runtime.submit_assistant_message(project_id, "你是什么大模型", assistant_mode="knowledge")
        job = self.wait_for_job(runtime, response["job_id"])

        self.assertEqual(job["result"]["knowledge"]["answer_type"], "assistant_model")
        self.assertIn("MiniMax-M2.5", job["result"]["assistant_message"])
        self.assertIn("minimax", job["result"]["assistant_message"].lower())
        self.assertNotIn("这里回答的是系统运行配置", job["result"]["assistant_message"])

    def test_tool_mode_high_risk_qgis_action_enters_confirmation(self) -> None:
        runtime, project_id = self.build_runtime()
        runtime.llm_planner.plan_actions = lambda *args, **kwargs: {
            "assistant_message": "Export the current QGIS map.",
            "target": "qgis",
            "actions": [{"tool_name": "export_map", "tool_params": {"file_path": "C:/Users/Public/test.png"}}],
            "planner": "test_stub",
        }

        response = runtime.submit_assistant_message(project_id, "export qgis map", assistant_mode="tool", target="qgis")
        job = self.wait_for_job(runtime, response["job_id"])

        self.assertEqual(job["result"]["intent"], "tool")
        self.assertTrue(job["result"]["requires_confirmation"])
        self.assertTrue(job["result"]["confirmation_id"])
        self.assertEqual(job["result"]["actions_executed"], [])

    def test_confirmed_high_risk_action_executes(self) -> None:
        runtime, project_id = self.build_runtime()
        runtime.llm_planner.plan_actions = lambda *args, **kwargs: {
            "assistant_message": "Export the current QGIS map.",
            "target": "qgis",
            "actions": [{"tool_name": "export_map", "tool_params": {"file_path": "C:/Users/Public/test.png"}}],
            "planner": "test_stub",
        }
        runtime.qgis_bridge.execute = lambda tool_name, params=None: {"status": "success", "message": f"ok:{tool_name}"}

        first = runtime.submit_assistant_message(project_id, "export qgis map", assistant_mode="tool", target="qgis")
        first_job = self.wait_for_job(runtime, first["job_id"])
        confirmation_id = first_job["result"]["confirmation_id"]

        confirm = runtime.confirm_assistant_action(confirmation_id)
        confirm_job = self.wait_for_job(runtime, confirm["job_id"])

        self.assertEqual(confirm_job["result"]["planner"], "confirmation")
        self.assertTrue(confirm_job["result"]["actions_executed"])
        self.assertFalse(confirm_job["result"]["requires_confirmation"])
        self.assertEqual(confirm_job["result"]["confirmation_status"], "approved")

    def test_rejected_high_risk_action_is_memorized(self) -> None:
        runtime, project_id = self.build_runtime()
        runtime.llm_planner.plan_actions = lambda *args, **kwargs: {
            "assistant_message": "Export the current QGIS map.",
            "target": "qgis",
            "actions": [{"tool_name": "export_map", "tool_params": {"file_path": "C:/Users/Public/test.png"}}],
            "planner": "test_stub",
        }

        first = runtime.submit_assistant_message(project_id, "export qgis map", assistant_mode="tool", target="qgis")
        first_job = self.wait_for_job(runtime, first["job_id"])
        confirmation_id = first_job["result"]["confirmation_id"]

        reject = runtime.confirm_assistant_action(confirmation_id, decision="reject")
        reject_job = self.wait_for_job(runtime, reject["job_id"])

        conversation = runtime.store.get_conversation(reject_job["result"]["conversation_id"])
        self.assertEqual(reject_job["result"]["planner"], "confirmation_rejected")
        self.assertEqual(reject_job["result"]["confirmation_status"], "rejected")
        self.assertEqual(reject_job["result"]["actions_executed"], [])
        self.assertIn("export_map", conversation.pinned_state["rejected_tools"])

    def test_expired_confirmation_cannot_execute(self) -> None:
        runtime, project_id = self.build_runtime()
        runtime.llm_planner.plan_actions = lambda *args, **kwargs: {
            "assistant_message": "Export the current QGIS map.",
            "target": "qgis",
            "actions": [{"tool_name": "export_map", "tool_params": {"file_path": "C:/Users/Public/test.png"}}],
            "planner": "test_stub",
        }

        first = runtime.submit_assistant_message(project_id, "export qgis map", assistant_mode="tool", target="qgis")
        first_job = self.wait_for_job(runtime, first["job_id"])
        confirmation_id = first_job["result"]["confirmation_id"]
        runtime.store.confirmations[confirmation_id].expires_at = "2000-01-01T00:00:00+00:00"

        confirm = runtime.confirm_assistant_action(confirmation_id)
        confirm_job = self.wait_for_job(runtime, confirm["job_id"])

        self.assertEqual(confirm_job["status"], "failed")
        self.assertIn("expired", confirm_job["error"].lower())

    def test_confirmation_contains_frozen_plan_fingerprint(self) -> None:
        runtime, project_id = self.build_runtime()
        runtime.llm_planner.plan_actions = lambda *args, **kwargs: {
            "assistant_message": "Export the current QGIS map.",
            "target": "qgis",
            "actions": [{"tool_name": "export_map", "tool_params": {"file_path": "C:/Users/Public/test.png"}}],
            "planner": "test_stub",
        }

        response = runtime.submit_assistant_message(project_id, "export qgis map", assistant_mode="tool", target="qgis")
        job = self.wait_for_job(runtime, response["job_id"])
        confirmation = runtime.store.get_confirmation(job["result"]["confirmation_id"])

        self.assertTrue(job["result"]["prompt_parts"]["context_fingerprint"])
        self.assertTrue(job["result"]["plan_fingerprint"])
        self.assertEqual(confirmation.plan_fingerprint, job["result"]["plan_fingerprint"])
        self.assertTrue(confirmation.expires_at)

    def test_hybrid_mode_executes_then_explains(self) -> None:
        runtime, project_id = self.build_runtime()
        runtime.llm_planner.plan_actions = lambda *args, **kwargs: {
            "assistant_message": "Switch the basemap first.",
            "target": "webgis",
            "actions": [{"tool_name": "switch_basemap", "tool_params": {"basemap_id": "amap_light"}}],
            "planner": "test_stub",
        }

        response = runtime.submit_assistant_message(project_id, "switch basemap and explain coastal attraction", assistant_mode="tool")
        job = self.wait_for_job(runtime, response["job_id"])

        self.assertEqual(job["result"]["intent"], "hybrid")
        self.assertTrue(job["result"]["actions_executed"])
        self.assertTrue(job["result"]["citations"])
        # The hybrid message includes the tool plan message plus a knowledge grounding section
        self.assertIn("Switch the basemap first.", job["result"]["assistant_message"])
        self.assertGreater(len(job["result"]["assistant_message"]), 40)

    def test_legacy_request_body_remains_compatible(self) -> None:
        runtime, project_id = self.build_runtime(enable_v2=False)

        response = runtime.submit_assistant_message(project_id, "explain current map")
        job = self.wait_for_job(runtime, response["job_id"])

        self.assertEqual(job["request"]["target"], "webgis")
        self.assertEqual(job["request"]["input_mode"], "text")
        self.assertIn(job["status"], {"completed", "failed"})

    def test_long_history_is_compressed_into_running_summary(self) -> None:
        runtime, project_id = self.build_runtime()
        history = [{"role": "user" if index % 2 == 0 else "assistant", "text": f"message {index}"} for index in range(20)]
        project = runtime._require_project(project_id)

        runtime.session_engine.handle(
            job_id="job_memory_test",
            project=project,
            message="continue explaining this region",
            assistant_mode="knowledge",
            conversation_id="",
            history=history,
            map_context={"visible_layers": []},
            target="webgis",
            input_mode="text",
            stage_callback=lambda *args, **kwargs: None,
        )

        conversation = next(iter(runtime.store.conversations.values()))
        self.assertTrue(conversation.running_summary)
        self.assertLessEqual(len(conversation.raw_messages), 8)
        self.assertIn("last_map_grounding", conversation.pinned_state)


if __name__ == "__main__":
    unittest.main()
