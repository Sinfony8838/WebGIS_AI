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

    # Note: high-risk QGIS confirmation tests were removed when the legacy
    # QGIS bridge target was retired. Heavy GIS work now flows through
    # /workflow/* (covered by tests in ``test_workflow_executor.py``).

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
