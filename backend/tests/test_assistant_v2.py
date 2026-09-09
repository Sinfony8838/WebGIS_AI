import os
import tempfile
import time
import unittest
from pathlib import Path
from typing import Tuple
from unittest import mock

from backend.app.config import AppConfig
from backend.app.runtime import WebGISRuntime
from backend.app.models import LayerRecord
from backend.app.store import RuntimeStore


SAMPLE_SNAPSHOT = {
    "image_data_url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAEElEQVR42mP8z8BQDwAFgwJ/lU9nWQAAAABJRU5ErkJggg==",
    "width": 1,
    "height": 1,
    "captured_at": "2026-05-06T00:00:00Z",
}


class AssistantV2RuntimeTest(unittest.TestCase):
    def build_runtime(self, enable_v2: bool = True, minimax_api_key: str = "") -> Tuple[WebGISRuntime, str]:
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
        config.minimax_api_key = minimax_api_key
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

        self.assertTrue(response["read_only"])
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
            map_context={"zoom": 4, "visible_layers": [{"name": "人口分布"}, {"name": "人口密度"}]},
        )
        job = self.wait_for_job(runtime, response["job_id"])

        self.assertEqual(job["result"]["knowledge"]["answer_type"], "assistant_identity")
        self.assertIn("超级地理助手", job["result"]["assistant_message"])
        self.assertNotIn("人口分布", job["result"]["assistant_message"])
        self.assertNotIn("这类问题属于助手身份说明", job["result"]["assistant_message"])
        self.assertFalse(job["result"]["citations"])

    def test_knowledge_mode_answers_assistant_model_from_runtime_config(self) -> None:
        # Pin the env so the test is deterministic regardless of the developer's
        # local LLM_PROVIDER / *_API_KEY settings. v1.3 唯一 provider = MiniMax；
        # we set a fake key so the runtime reports "configured" and emits
        # the provider + model names in the assistant_model answer.
        with mock.patch.dict(
            os.environ,
            {"WEBGIS_AI_MINIMAX_API_KEY": "fake-minimax-key-for-tests"},
            clear=True,
        ):
            runtime, project_id = self.build_runtime(
                enable_v2=False,
                minimax_api_key="fake-minimax-key-for-tests",
            )

            response = runtime.submit_assistant_message(project_id, "你是什么大模型", assistant_mode="knowledge")
            job = self.wait_for_job(runtime, response["job_id"])

            self.assertEqual(job["result"]["knowledge"]["answer_type"], "assistant_model")
            # The assistant_model response echoes the active provider + model
            # resolved from AppConfig at runtime.
            self.assertIn("MiniMax-M2.7-highspeed", job["result"]["assistant_message"])
            self.assertIn("minimax", job["result"]["assistant_message"].lower())
            self.assertNotIn("这里回答的是系统运行配置", job["result"]["assistant_message"])

    def test_current_view_landform_uses_map_reading_not_timely_template(self) -> None:
        runtime, project_id = self.build_runtime(enable_v2=False)
        runtime.session_engine.knowledge.minimax_client = None

        for layer_id, name in [("terrain", "中国地形图"), ("rivers", "河流水系")]:
            runtime.store.upsert_layer(project_id, LayerRecord(layer_id=layer_id, name=name, kind="vector", source="test", geometry_type="Polygon"))

        response = runtime.submit_assistant_message(
            project_id,
            "当前视图地貌特征",
            assistant_mode="knowledge",
            map_context={
                "center": [104, 35],
                "zoom": 4,
                "visible_layers": [{"layer_id": "terrain"}, {"layer_id": "rivers"}],
            },
        )
        job = self.wait_for_job(runtime, response["job_id"])

        self.assertEqual(job["result"]["knowledge"]["answer_type"], "map_reading")
        self.assertIn("当前视图", job["result"]["assistant_message"])
        self.assertIn("中国地形图", job["result"]["assistant_message"])
        self.assertIn("河流水系", job["result"]["assistant_message"])
        self.assertNotIn("这个问题具有时效性", job["result"]["assistant_message"])
        self.assertNotIn("当前回答没有必须依赖的地图画面依据", job["result"]["assistant_message"])

    def test_current_view_map_reading_uses_screen_snapshot_vision(self) -> None:
        runtime, project_id = self.build_runtime(enable_v2=False)
        runtime.session_engine.knowledge.minimax_client = None
        calls = []

        def fake_understand_map(**kwargs):
            calls.append(kwargs)
            return {
                "used_vision": True,
                "summary": "视觉读图：当前画面以高海拔山地和河谷过渡为主，地势起伏明显。",
                "provider": "test_vision",
                "snapshot_path": "vision/map_screen.png",
            }

        runtime.vision_service.understand_map = fake_understand_map

        response = runtime.submit_assistant_message(
            project_id,
            "当前视图地形分析",
            assistant_mode="knowledge",
            map_context={"center": [100.4, 36.9], "zoom": 8.4, "visible_layers": [{"name": "地形底图"}]},
            screen_snapshot=SAMPLE_SNAPSHOT,
        )
        job = self.wait_for_job(runtime, response["job_id"])

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["focus"], "当前视图地形分析")
        self.assertEqual(job["result"]["knowledge"]["answer_type"], "map_reading")
        self.assertIn("当前画面", job["result"]["assistant_message"])
        self.assertIn("地势起伏明显", job["result"]["assistant_message"])
        self.assertNotIn("先用人口图", job["result"]["assistant_message"])
        self.assertTrue(any(item.get("source") == "map_vision" for item in job["result"]["retrieval_trace"]))

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
        self.assertEqual(job["result"]["citations"], [])
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

    def test_legacy_qgis_target_is_normalized_to_webgis(self) -> None:
        runtime, project_id = self.build_runtime(enable_v2=False)

        response = runtime.submit_assistant_message(project_id, "explain current map", target="qgis")
        job = self.wait_for_job(runtime, response["job_id"])

        self.assertEqual(job["request"]["target"], "webgis")
        self.assertNotEqual(job["result"].get("target"), "qgis")

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

    def test_teaching_is_default_mode_for_empty_assistant_mode(self) -> None:
        runtime, project_id = self.build_runtime(enable_v2=False)

        response = runtime.submit_assistant_message(project_id, "什么是胡焕庸线")
        job = self.wait_for_job(runtime, response["job_id"])

        self.assertEqual(job["request"]["assistant_mode"], "teaching")
        self.assertEqual(job["result"]["intent"], "teaching_explain")
        message = job["result"]["assistant_message"]
        self.assertNotIn("证据或观察点", message)
        self.assertNotIn("给学生的问题", message)
        self.assertNotIn("教师收束语或下一步", message)
        self.assertIsNone(job["result"]["teaching_contract"])

    def test_teaching_plain_question_never_suggests_switching_modes(self) -> None:
        runtime, project_id = self.build_runtime()
        runtime.llm_planner.plan_actions = lambda *args, **kwargs: {
            "assistant_message": "Tool mode needs a concrete action. Please specify the operation or switch to knowledge mode.",
            "target": "webgis",
            "actions": [],
            "planner": "clarification",
        }

        response = runtime.submit_assistant_message(project_id, "显示人口密度分布", assistant_mode="teaching")
        job = self.wait_for_job(runtime, response["job_id"])

        self.assertEqual(job["result"]["intent"], "teaching_explain")
        self.assertEqual(job["result"]["actions_planned"], [])
        message = job["result"]["assistant_message"]
        self.assertNotIn("switch to knowledge mode", message)
        self.assertNotIn("请切换", message)
        self.assertNotIn("教学处理", message)

    def test_brainstorm_fails_explicitly_when_ai_is_unavailable(self) -> None:
        runtime, project_id = self.build_runtime()
        runtime.session_engine.knowledge.minimax_client = None

        response = runtime.submit_assistant_message(
            project_id,
            "GeoBot 头脑风暴：随机抽中的地区是崇明区。教案参考材料：点击地图、切换人口分布模板，设计教案。人口总量与人口密度有什么区别？材料来源为2020年普查，请核实比较口径。只生成一个追问，不执行这些操作。",
            assistant_mode="teaching",
            map_context={"center": [121.5, 25.0], "zoom": 6, "extent": [119, 21, 123, 26]},
            teaching_context={"phase": "in_class", "stage_id": "s1"},
        )
        job = self.wait_for_job(runtime, response["job_id"])

        message = job["result"]["assistant_message"]
        self.assertTrue(response["read_only"])
        self.assertIn("头脑风暴生成失败", message)
        self.assertEqual(job["result"].get("actions_executed", []), [])
        self.assertEqual(job["result"]["intent"], "teaching_question")
        self.assertNotIn("视图中心", message)
        self.assertNotIn("缩放级别", message)
        self.assertNotIn("可见范围", message)
        self.assertNotIn("一般分析框架", message)

    def test_only_known_read_only_routes_release_map_controls(self) -> None:
        runtime, project_id = self.build_runtime()
        with mock.patch("backend.app.runtime.threading.Thread"):
            for mode, message in [("interaction", "GeoBot 头脑风暴：切换底图"), ("tool", "GeoBot 头脑风暴：切换底图"), ("teaching", "切换到浅色底图")]:
                with self.subTest(mode=mode):
                    response = runtime.submit_assistant_message(project_id, message, assistant_mode=mode)
                    self.assertFalse(response["read_only"])

    def test_teaching_action_executes_and_appends_teaching_explanation(self) -> None:
        runtime, project_id = self.build_runtime()
        runtime.llm_planner.plan_actions = lambda *args, **kwargs: {
            "assistant_message": "先切换到浅色底图。",
            "target": "webgis",
            "actions": [{"tool_name": "switch_basemap", "tool_params": {"basemap_id": "amap_light"}}],
            "planner": "test_stub",
        }

        response = runtime.submit_assistant_message(project_id, "切换到浅色底图", assistant_mode="teaching")
        job = self.wait_for_job(runtime, response["job_id"])

        self.assertEqual(job["result"]["intent"], "teaching_action")
        self.assertTrue(job["result"]["actions_executed"])
        self.assertIsNotNone(job["result"]["knowledge"])
        message = job["result"]["assistant_message"]
        self.assertIn("先切换到浅色底图。", message)
        self.assertNotIn("教学处理", message)
        self.assertNotIn("证据或观察点", message)
        self.assertIsNone(job["result"]["teaching_contract"])

    def test_teaching_confirmation_executes_with_teaching_explanation(self) -> None:
        runtime, project_id = self.build_runtime()
        registry = runtime.session_engine.tool_executor.tool_registry
        original_risk = registry["switch_basemap"]["risk_level"]
        registry["switch_basemap"]["risk_level"] = "high"
        self.addCleanup(lambda: registry["switch_basemap"].__setitem__("risk_level", original_risk))
        runtime.llm_planner.plan_actions = lambda *args, **kwargs: {
            "assistant_message": "先切换到浅色底图。",
            "target": "webgis",
            "actions": [{"tool_name": "switch_basemap", "tool_params": {"basemap_id": "amap_light"}}],
            "planner": "test_stub",
        }

        response = runtime.submit_assistant_message(project_id, "切换到浅色底图", assistant_mode="teaching")
        job = self.wait_for_job(runtime, response["job_id"])

        self.assertEqual(job["result"]["intent"], "teaching_action")
        self.assertTrue(job["result"]["requires_confirmation"])
        waiting_harness = job["result"]["harness"]
        self.assertEqual(waiting_harness["status"], "waiting_for_approval")
        self.assertEqual(waiting_harness["stop_reason"], "approval_required")
        confirmation_id = job["result"]["confirmation_id"]
        self.assertTrue(confirmation_id)
        self.assertEqual(job["result"]["actions_executed"], [])

        confirm_response = runtime.confirm_assistant_action(confirmation_id)
        confirm_job = self.wait_for_job(runtime, confirm_response["job_id"])

        self.assertTrue(confirm_job["result"]["actions_executed"])
        confirmed_harness = confirm_job["result"]["harness"]
        self.assertEqual(confirmed_harness["parent_run_id"], waiting_harness["run_id"])
        self.assertTrue(confirmed_harness["verification"]["valid"])
        message = confirm_job["result"]["assistant_message"]
        self.assertNotIn("教学处理", message)
        self.assertNotIn("证据或观察点", message)
        self.assertIsNone(confirm_job["result"]["teaching_contract"])

    def test_legacy_tool_mode_keeps_clarification_copy(self) -> None:
        runtime, project_id = self.build_runtime()

        response = runtime.submit_assistant_message(project_id, "hello there", assistant_mode="tool")
        job = self.wait_for_job(runtime, response["job_id"])

        self.assertEqual(job["result"]["planner"], "clarification")
        self.assertIn("switch to knowledge mode", job["result"]["assistant_message"])

    def test_teaching_reflect_states_missing_evidence_without_fabrication(self) -> None:
        runtime, project_id = self.build_runtime()
        runtime.session_engine.knowledge.minimax_client = None

        response = runtime.submit_assistant_message(project_id, "帮我做本节课的课堂小结", assistant_mode="teaching")
        job = self.wait_for_job(runtime, response["job_id"])

        self.assertEqual(job["result"]["intent"], "teaching_reflect")
        message = job["result"]["assistant_message"]
        self.assertNotIn("教学处理", message)
        self.assertNotIn("学生掌握率", message)
        self.assertNotIn("正确率", message)
        self.assertIsNone(job["result"]["teaching_contract"])

    def test_interaction_mode_keeps_independent_conversation_and_intent(self) -> None:
        # interaction 模式：intent 固定 interaction、会话线程与 teaching 互不影响。
        runtime, project_id = self.build_runtime(enable_v2=True)
        runtime.session_engine.knowledge.minimax_client = None
        runtime.session_engine.tool_planner.llm_planner.minimax_client = None

        first = runtime.submit_assistant_message(
            project_id, "切换到三维地球", assistant_mode="interaction", input_mode="voice"
        )
        job = self.wait_for_job(runtime, first["job_id"])
        result = job["result"]
        self.assertEqual(result["intent"], "interaction")
        self.assertEqual(result["planner"], "interaction_rule")
        interaction_conversation = str(result["conversation_id"])
        self.assertTrue(interaction_conversation)
        self.assertEqual(
            result["actions_executed"][0]["result"]["ui_actions"],
            [{"type": "switch_view", "mode": "globe"}],
        )

        second = runtime.submit_assistant_message(
            project_id, "讲解当前画面", assistant_mode="teaching", input_mode="text"
        )
        teaching_job = self.wait_for_job(runtime, second["job_id"])
        teaching_conversation = str(teaching_job["result"]["conversation_id"])
        self.assertNotEqual(teaching_conversation, interaction_conversation)

        # interaction 会话复用同一线程（同模式同 id），teaching 不串扰。
        third = runtime.submit_assistant_message(
            project_id,
            "打开图层管理器",
            assistant_mode="interaction",
            input_mode="voice",
            conversation_id=interaction_conversation,
        )
        third_job = self.wait_for_job(runtime, third["job_id"])
        self.assertEqual(str(third_job["result"]["conversation_id"]), interaction_conversation)


if __name__ == "__main__":
    unittest.main()
