"""智能交互（interaction 模式）工具链路测试。

覆盖：8 个 interaction 工具的注册/校验器/分发、跨模式拒绝（教学模式调
操控工具 → blocked）、end_class_session 确认流、start_class_session 课节
互斥、interaction 分层解析（规则快通道 / LLM 兜底 / 失败回落）与中文阶段
反馈。全部测试不连网：MiniMax 两个独立引用都置 None/Fake。
"""
import tempfile
import time
import unittest
from pathlib import Path
from typing import Tuple

from backend.app.config import AppConfig
from backend.app.runtime import WebGISRuntime
from backend.app.store import RuntimeStore

BUILTIN_LESSON_ID = "lesson_builtin_population_distribution"

INTERACTION_TOOLS = (
    "switch_view_mode",
    "open_panel",
    "focus_layer",
    "set_layer_opacity",
    "enter_lesson_stage",
    "run_workflow",
    "start_class_session",
    "end_class_session",
)


class FakeLLM:
    """Deterministic stand-in for the MiniMax chat client."""

    def __init__(self, response: str = '{"assistant_message": "好的。", "actions": [{"tool_name": "open_panel", "tool_params": {"panel": "layers", "open": true}}]}'):
        self.response = response
        self.calls = 0

    def chat_completion(self, messages, temperature=0.2, **kwargs):
        self.calls += 1
        return self.response

    def status(self):
        return {"configured": False}


class InteractionToolsTest(unittest.TestCase):
    def build_runtime(self) -> Tuple[WebGISRuntime, RuntimeStore, str]:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root_dir = Path(__file__).resolve().parents[2]
        config = AppConfig(root_dir=root_dir)
        config.data_dir = Path(temp_dir.name) / "backend" / "data"
        config.state_dir = config.data_dir / "state"
        config.uploads_dir = config.data_dir / "uploads"
        config.outputs_dir = config.data_dir / "outputs"
        config.state_file = config.state_dir / "runtime.json"
        config.assistant_v2_enabled = False
        config.ensure_dirs()
        runtime = WebGISRuntime(config=config, store=RuntimeStore(config.state_file))
        # Hermetic: two independent LLM references must both be neutralised,
        # otherwise a dev machine with a real key hits the network.
        runtime.session_engine.knowledge.minimax_client = None
        runtime.session_engine.knowledge.resource_search = None
        runtime.session_engine.tool_planner.llm_planner.minimax_client = None
        project = runtime.create_project()
        return runtime, runtime.store, project["project_id"]

    def start_session(self, runtime: WebGISRuntime, project_id: str) -> str:
        return runtime.classroom.create_class_session(BUILTIN_LESSON_ID, project_id)["session"]["session_id"]

    def teaching_context(self, session_id: str = "", stage_id: str = "", phase: str = "", lesson_id: str = "") -> dict:
        return {
            "lesson_id": lesson_id or BUILTIN_LESSON_ID,
            "session_id": session_id,
            "stage_id": stage_id,
            "phase": phase,
        }

    def wait_for_job(self, runtime: WebGISRuntime, job_id: str) -> dict:
        for _ in range(300):
            payload = runtime.get_job(job_id)
            if payload["status"] in {"completed", "failed"}:
                return payload
            time.sleep(0.05)
        self.fail(f"Job did not finish in time: {job_id}")

    # ------------------------------------------------------------------
    # Registry & mode gating
    # ------------------------------------------------------------------

    def test_all_interaction_tools_registered_with_interaction_visibility(self) -> None:
        runtime, _store, _project_id = self.build_runtime()
        registry = runtime.session_engine.tool_executor.tool_registry
        for tool in INTERACTION_TOOLS:
            self.assertIn(tool, registry, tool)
            self.assertEqual(registry[tool]["visible_in_mode"], ["interaction"], tool)

    def test_interaction_tools_blocked_outside_interaction_mode(self) -> None:
        runtime, _store, _project_id = self.build_runtime()
        for mode in ("teaching_action", "tool", "hybrid"):
            assessment = runtime.session_engine.tool_executor.assess(
                "webgis",
                [{"tool_name": "switch_view_mode", "tool_params": {"mode": "globe"}}],
                assistant_mode=mode,
            )
            self.assertEqual(assessment["risk_level"], "blocked", mode)

    def test_classroom_tools_blocked_in_interaction_mode(self) -> None:
        runtime, _store, _project_id = self.build_runtime()
        assessment = runtime.session_engine.tool_executor.assess(
            "webgis",
            [{"tool_name": "record_observation", "tool_params": {"verdict": "correct"}}],
            assistant_mode="interaction",
            map_context={"teaching_context": self.teaching_context(phase="in_class")},
        )
        self.assertEqual(assessment["risk_level"], "blocked")

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------

    def test_set_layer_opacity_validator_requires_zero_to_one(self) -> None:
        runtime, _store, _project_id = self.build_runtime()
        bad = runtime.session_engine.tool_executor.assess(
            "webgis",
            [{"tool_name": "set_layer_opacity", "tool_params": {"layer_id": "l1", "opacity": 1.5}}],
            assistant_mode="interaction",
        )
        self.assertEqual(bad["risk_level"], "blocked")

    def test_run_workflow_validator_rejects_outside_whitelist(self) -> None:
        runtime, _store, _project_id = self.build_runtime()
        assessment = runtime.session_engine.tool_executor.assess(
            "webgis",
            [{"tool_name": "run_workflow", "tool_params": {"template_id": "facility_buffer"}}],
            assistant_mode="interaction",
        )
        self.assertEqual(assessment["risk_level"], "blocked")

    def test_end_class_session_requires_confirmation(self) -> None:
        runtime, _store, _project_id = self.build_runtime()
        session_id = self.start_session(runtime, _project_id)
        assessment = runtime.session_engine.tool_executor.assess(
            "webgis",
            [{"tool_name": "end_class_session", "tool_params": {}}],
            assistant_mode="interaction",
            map_context={"teaching_context": self.teaching_context(session_id=session_id, phase="in_class")},
        )
        self.assertEqual(assessment["risk_level"], "high")
        self.assertTrue(assessment["requires_confirmation"])

    def test_start_class_session_rejected_when_session_running(self) -> None:
        runtime, _store, _project_id = self.build_runtime()
        session_id = self.start_session(runtime, _project_id)
        assessment = runtime.session_engine.tool_executor.assess(
            "webgis",
            [{"tool_name": "start_class_session", "tool_params": {}}],
            assistant_mode="interaction",
            project_state={"project_id": _project_id},
            map_context={"teaching_context": self.teaching_context(session_id=session_id, phase="in_class")},
        )
        self.assertEqual(assessment["risk_level"], "blocked")
        self.assertIn("班课", assessment["actions_planned"][0]["validation_error"])

    # ------------------------------------------------------------------
    # Execution branches (runtime._execute_assistant_action)
    # ------------------------------------------------------------------

    def test_switch_view_mode_emits_ui_action(self) -> None:
        runtime, _store, project_id = self.build_runtime()
        result = runtime._execute_assistant_action(
            project_id,
            {"tool_name": "switch_view_mode", "tool_params": {"mode": "globe"}},
            {},
        )
        self.assertEqual(result["ui_actions"], [{"type": "switch_view", "mode": "globe"}])

    def test_open_panel_emits_ui_action(self) -> None:
        runtime, _store, project_id = self.build_runtime()
        result = runtime._execute_assistant_action(
            project_id,
            {"tool_name": "open_panel", "tool_params": {"panel": "layers", "open": True}},
            {},
        )
        self.assertEqual(result["ui_actions"], [{"type": "open_panel", "panel": "layers", "open": True}])

    def test_set_layer_opacity_patches_layer(self) -> None:
        runtime, store, project_id = self.build_runtime()
        layer = store.upsert_layer(
            project_id,
            __import__("backend.app.models", fromlist=["LayerRecord"]).LayerRecord(
                layer_id="l_density",
                name="人口密度",
                kind="geojson",
                source="builtin",
                geometry_type="polygon",
                opacity=1.0,
            ),
        )
        result = runtime._execute_assistant_action(
            project_id,
            {"tool_name": "set_layer_opacity", "tool_params": {"layer_name": "人口密度", "opacity": 0.5}},
            {},
        )
        self.assertIn("人口密度", result["assistant_message"])
        project = runtime._require_project(project_id)
        patched = next(layer for layer in project.layers if layer.layer_id == "l_density")
        self.assertEqual(patched.opacity, 0.5)

    def test_focus_layer_sets_view_from_bbox(self) -> None:
        runtime, _store, project_id = self.build_runtime()
        LayerRecord = __import__("backend.app.models", fromlist=["LayerRecord"]).LayerRecord
        runtime.store.upsert_layer(
            project_id,
            LayerRecord(
                layer_id="l_city",
                name="上海",
                kind="geojson",
                source="builtin",
                geometry_type="polygon",
                data={"type": "FeatureCollection", "features": [
                    {"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [121.47, 31.23]}}
                ]},
            ),
        )
        result = runtime._execute_assistant_action(
            project_id,
            {"tool_name": "focus_layer", "tool_params": {"layer_name": "上海"}},
            {},
        )
        self.assertIn("上海", result["assistant_message"])
        self.assertIn("view", result)
        view = result["view"]
        self.assertAlmostEqual(view["center"][0], 121.47, places=2)

    def test_enter_lesson_stage_next_moves_stage_and_returns_stage(self) -> None:
        runtime, _store, project_id = self.build_runtime()
        session_id = self.start_session(runtime, project_id)
        session = runtime.store.get_class_session(session_id)
        lesson = runtime.classroom._lesson_for_session(session)
        stage_ids = [stage["stage_id"] for stage in lesson.stages]
        first_stage = stage_ids[0]
        runtime.classroom.enter_session_stage(session_id, first_stage)

        result = runtime._execute_assistant_action(
            project_id,
            {"tool_name": "enter_lesson_stage", "tool_params": {"offset": "next"}},
            {"teaching_context": self.teaching_context(session_id=session_id, stage_id=first_stage, phase="in_class")},
        )
        self.assertIn("已进入环节", result["assistant_message"])
        moved = runtime.store.get_class_session(session_id)
        self.assertEqual(moved.current_stage_id, stage_ids[1])

    def test_run_workflow_submits_allowed_template(self) -> None:
        runtime, store, project_id = self.build_runtime()
        result = runtime._execute_assistant_action(
            project_id,
            {"tool_name": "run_workflow", "tool_params": {"template_id": "hu_line_compare"}},
            {},
        )
        self.assertIn("已提交", result["assistant_message"])
        self.assertEqual(result["ui_actions"][0]["type"], "open_panel")
        workflow_id = result["workflow"]["workflow_id"]
        self.assertTrue(workflow_id)
        # 等工作流落地，确认它真的在执行（不依赖网络：内置数据集）。
        for _ in range(120):
            record = store.get_workflow(workflow_id)
            if record is not None and record.status in {"completed", "failed"}:
                break
            time.sleep(0.05)
        record = store.get_workflow(workflow_id)
        self.assertIsNotNone(record)

    def test_start_and_end_class_session_roundtrip_via_executor(self) -> None:
        runtime, _store, project_id = self.build_runtime()
        started = runtime._execute_assistant_action(
            project_id,
            {"tool_name": "start_class_session", "tool_params": {}},
            {"teaching_context": self.teaching_context(lesson_id=BUILTIN_LESSON_ID, phase="course_prep")},
        )
        session = started["class_session"]
        self.assertEqual(session["status"], "running")

        ended = runtime._execute_assistant_action(
            project_id,
            {"tool_name": "end_class_session", "tool_params": {}},
            {"teaching_context": self.teaching_context(session_id=session["session_id"], phase="in_class")},
        )
        self.assertIn("已结束", ended["assistant_message"])
        record = runtime.store.get_class_session(session["session_id"])
        self.assertEqual(record.status, "ended")

    # ------------------------------------------------------------------
    # E2E via submit_assistant_message (interaction mode)
    # ------------------------------------------------------------------

    def test_interaction_e2e_rule_fast_path_with_zero_llm_calls(self) -> None:
        runtime, _store, project_id = self.build_runtime()
        fake = FakeLLM()
        runtime.session_engine.tool_planner.llm_planner.minimax_client = fake
        response = runtime.submit_assistant_message(
            project_id, "切换到三维地球", assistant_mode="interaction", input_mode="voice"
        )
        job = self.wait_for_job(runtime, response["job_id"])
        result = job["result"]
        self.assertEqual(job["status"], "completed")
        self.assertEqual(result["intent"], "interaction")
        self.assertEqual(result["planner"], "interaction_rule")
        self.assertEqual(fake.calls, 0)
        executed = result["actions_executed"]
        self.assertEqual(executed[0]["action"]["tool_name"], "switch_view_mode")
        self.assertEqual(executed[0]["result"]["ui_actions"], [{"type": "switch_view", "mode": "globe"}])

    def test_interaction_e2e_llm_fallback_when_rules_miss(self) -> None:
        runtime, _store, project_id = self.build_runtime()
        fake = FakeLLM()
        runtime.session_engine.tool_planner.llm_planner.minimax_client = fake
        response = runtime.submit_assistant_message(
            project_id, "帮我把那个右侧的面板弄出来一下谢谢", assistant_mode="interaction", input_mode="voice"
        )
        job = self.wait_for_job(runtime, response["job_id"])
        result = job["result"]
        self.assertEqual(result["planner"], "interaction_minimax")
        self.assertEqual(fake.calls, 1)
        self.assertEqual(result["actions_executed"][0]["action"]["tool_name"], "open_panel")

    def test_interaction_e2e_voice_clarification_when_llm_fails(self) -> None:
        runtime, _store, project_id = self.build_runtime()
        # minimax_client=None：LLM 必然失败，语音应回落「没听清」话术而非报错。
        runtime.session_engine.tool_planner.llm_planner.minimax_client = None
        response = runtime.submit_assistant_message(
            project_id, "完全不知所云的语句xyz", assistant_mode="interaction", input_mode="voice"
        )
        job = self.wait_for_job(runtime, response["job_id"])
        result = job["result"]
        self.assertEqual(job["status"], "completed")
        self.assertEqual(result["planner"], "voice_clarification")
        self.assertIn("没有直接听懂", result["assistant_message"])

    def test_interaction_e2e_end_class_session_requires_confirmation_flow(self) -> None:
        runtime, _store, project_id = self.build_runtime()
        session_id = self.start_session(runtime, project_id)
        response = runtime.submit_assistant_message(
            project_id,
            "结束上课",
            assistant_mode="interaction",
            input_mode="voice",
            map_context={"teaching_context": self.teaching_context(session_id=session_id, phase="in_class")},
        )
        job = self.wait_for_job(runtime, response["job_id"])
        result = job["result"]
        self.assertTrue(result["requires_confirmation"])
        self.assertTrue(result["confirmation_id"])
        # 结束前班课仍在跑。
        self.assertEqual(runtime.store.get_class_session(session_id).status, "running")
        # 教师确认 → 执行 → 班课结束。
        confirm = runtime.confirm_assistant_action(result["confirmation_id"], decision="approve")
        confirm_job = self.wait_for_job(runtime, confirm["job_id"])
        self.assertEqual(confirm_job["status"], "completed")
        self.assertEqual(runtime.store.get_class_session(session_id).status, "ended")

    def test_interaction_e2e_chinese_stage_feedback(self) -> None:
        runtime, _store, project_id = self.build_runtime()
        response = runtime.submit_assistant_message(
            project_id, "切换到三维地球", assistant_mode="interaction", input_mode="voice"
        )
        job = self.wait_for_job(runtime, response["job_id"])
        stages = job["stages"]
        self.assertEqual(stages["routing"]["summary"], "已识别为系统操控指令")
        self.assertEqual(stages["planning"]["summary"], "快速通道命中，无需等待")


if __name__ == "__main__":
    unittest.main()
