import unittest
from backend.tests import test_voice_tools as fixtures
from backend.app.services.assistant import AssistantService
from unittest.mock import patch

class GlobeViewCommandsTest(unittest.TestCase):
    build_runtime = fixtures.InteractionToolsTest.build_runtime
    wait_for_job = fixtures.InteractionToolsTest.wait_for_job

    def test_feedback_does_not_mutate_view_or_call_model(self):
        runtime, _, pid = self.build_runtime()
        fake = fixtures.FakeLLM()
        runtime.llm_planner.minimax_client = fake
        for text in ("你这还是二维啊", "怎么还是二维地图", "三维地球没有切换", "为什么切换三维后还是二维", "看起来仍然是平面地图"):
            with self.subTest(text=text):
                result = self.wait_for_job(runtime, runtime.submit_assistant_message(pid, text, assistant_mode="operate")["job_id"])["result"]
                self.assertEqual(result["actions_executed"], [])
                self.assertIn("本次保持当前视图", result["assistant_message"])
        self.assertEqual(fake.calls, 0)

    def test_view_intent_preserves_requested_camera(self):
        runtime, store, pid = self.build_runtime()
        for text, expected in (
            ("切换三维地球", {"mode": "globe"}),
            ("切换三维地图", {"mode": "globe"}),
            ("切换成三维地球原始视图", {"mode": "globe", "view": "default"}),
            ("恢复三维地球初始视图", {"mode": "globe", "view": "default"}),
            ("显示地球全景", {"mode": "globe"}),
            ("切换三维地球保留当前位置和缩放", {"mode": "globe", "view": "preserve"}),
            ("切换二维地图", {"mode": "plane"}),
        ):
            with self.subTest(text=text):
                plan = runtime.assistant_service.plan_interaction_actions(text, store.get_project(pid))
                self.assertEqual(plan["actions"], [{"tool_name": "switch_view_mode", "tool_params": expected}])

    def test_whole_utterance_matching_rejects_questions_and_constraints(self):
        for text in ("你这还是二维啊", "不要切换三维地球", "切换三维地球并截图", "切换三维地球但不要改变缩放", "三维地球是什么", "切换二维地图？"):
            self.assertIsNone(AssistantService._view_command(text), text)

    def test_camera_preset_is_validated_before_execution(self):
        runtime, _, _ = self.build_runtime()
        executor = runtime.session_engine.tool_executor
        for params in ({"mode": "globe", "view": "unknown"}, {"mode": "globe", "view": []}, {"mode": "plane", "view": "default"}):
            assessed = executor.assess("webgis", [{"tool_name": "switch_view_mode", "tool_params": params}], assistant_mode="operate")
            self.assertEqual(assessed["risk_level"], "blocked")

    def test_failed_receipt_does_not_pollute_history_with_success(self):
        runtime, store, pid = self.build_runtime()
        with patch.object(runtime.interaction_operations, "observe_ui", return_value=[{"status":"failed", "detail":"camera failed"}]):
            result = self.wait_for_job(runtime, runtime.submit_assistant_message(pid, "切换三维地球", assistant_mode="operate")["job_id"])["result"]
        self.assertNotEqual(result["outcome"], "completed")
        self.assertNotIn("已切换", result["assistant_message"])
        self.assertEqual(store.get_project(pid).recent_actions[-1]["status"], "unconfirmed")
