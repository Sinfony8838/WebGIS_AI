from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from backend.app.config import AppConfig
from backend.app.runtime import WebGISRuntime
from backend.app.store import RuntimeStore


BUILTIN_LESSON_ID = "lesson_builtin_population_distribution"


class FakeRecordingLLM:
    """Chat client stub that records prompts and returns a canned answer."""

    def __init__(self) -> None:
        self.calls = []

    def chat_completion(self, messages, temperature=0.3, **kwargs):
        self.calls.append(messages)
        return (
            "这节课整体表现稳定。\n\n"
            "原理分析：错误集中在密度与总量的混淆上。\n\n"
            "课堂要点：\n- 证据或观察点：见课堂记录\n- 给学生的问题：密度和总量的区别是什么？\n- 教师收束语或下一步：下节课先复测该概念"
        )


class FakeResourceSearch:
    def __init__(self) -> None:
        self.calls = []

    def search(self, query="", scope="web", limit=5, **kwargs):
        self.calls.append(query)
        return {"items": []}


class TeachingContextIntegrationTest(unittest.TestCase):
    def build_runtime(self, minimax_api_key: str = ""):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root_dir = Path(__file__).resolve().parents[2]
        config = AppConfig(root_dir=root_dir)
        config.data_dir = Path(temp_dir.name) / "backend" / "data"
        config.state_dir = config.data_dir / "state"
        config.uploads_dir = config.data_dir / "uploads"
        config.outputs_dir = config.data_dir / "outputs"
        config.state_file = config.state_dir / "runtime.json"
        if minimax_api_key:
            config.minimax_api_key = minimax_api_key
        # Hermetic: ignore whatever WEBGIS_AI_ASSISTANT_V2_ENABLED the dev
        # machine carries; teaching mode still always routes to v2.
        config.assistant_v2_enabled = False
        config.ensure_dirs()
        store = RuntimeStore(config.state_file)
        runtime = WebGISRuntime(config=config, store=store)
        # Hermetic by default: the developer machine may carry a real MiniMax
        # key in its env, and tests must never hit the network. Tests that
        # need an LLM or search assign their own fakes after build.
        runtime.session_engine.knowledge.minimax_client = None
        runtime.session_engine.knowledge.resource_search = None
        project = runtime.create_project()
        return runtime, store, project["project_id"]

    def wait_for_job(self, runtime: WebGISRuntime, job_id: str, max_iterations: int = 200) -> dict:
        for _ in range(max_iterations):
            payload = runtime.get_job(job_id)
            if payload["status"] in {"completed", "failed"}:
                return payload
            time.sleep(0.05)
        self.fail(f"Job did not finish in time: {job_id}")

    def start_session(self, runtime: WebGISRuntime, project_id: str) -> str:
        return runtime.classroom.create_class_session(BUILTIN_LESSON_ID, project_id)["session"]["session_id"]

    def teaching_context(self, session_id: str = "", stage_id: str = "", phase: str = "") -> dict:
        return {"lesson_id": BUILTIN_LESSON_ID, "session_id": session_id, "stage_id": stage_id, "phase": phase}

    # ------------------------------------------------------------------
    # P0-1: run_visual_query registry fix
    # ------------------------------------------------------------------

    def test_run_visual_query_is_registered_not_blocked(self) -> None:
        runtime, _store, _project_id = self.build_runtime()
        assessment = runtime.session_engine.tool_executor.assess(
            "webgis",
            [{"tool_name": "run_visual_query", "tool_params": {"limit": 20}}],
            assistant_mode="teaching_action",
        )
        descriptor = assessment["actions_planned"][0]
        self.assertEqual(descriptor["risk_level"], "medium")
        self.assertNotEqual(assessment["risk_level"], "blocked")

    # ------------------------------------------------------------------
    # P0-2 / P0-4: teaching_context passthrough + assistant_exchange writeback
    # ------------------------------------------------------------------

    def test_assistant_exchange_logged_for_running_session(self) -> None:
        runtime, store, project_id = self.build_runtime()
        session_id = self.start_session(runtime, project_id)
        runtime.classroom.enter_session_stage(session_id, "s2")

        response = runtime.submit_assistant_message(
            project_id,
            "什么是胡焕庸线",
            assistant_mode="teaching",
            teaching_context=self.teaching_context(session_id=session_id, stage_id="s2", phase="in_class"),
        )
        job = self.wait_for_job(runtime, response["job_id"])
        self.assertEqual(job["status"], "completed")

        job_record = store.get_job(response["job_id"])
        self.assertEqual(job_record.request["teaching_context"]["session_id"], session_id)

        record = store.get_class_session(session_id)
        exchanges = [event for event in record.events if event["type"] == "assistant_exchange"]
        self.assertEqual(len(exchanges), 1)
        payload = exchanges[0]["payload"]
        self.assertEqual(payload["phase"], "in_class")
        self.assertEqual(payload["intent"], job["result"]["intent"])
        self.assertIn("胡焕庸线", payload["user_message"])
        self.assertEqual(exchanges[0]["stage_id"], "s2")

    def test_assistant_exchange_not_logged_without_session_or_after_end(self) -> None:
        runtime, store, project_id = self.build_runtime()
        session_id = self.start_session(runtime, project_id)

        response = runtime.submit_assistant_message(project_id, "什么是人口密度", assistant_mode="teaching")
        self.wait_for_job(runtime, response["job_id"])
        record = store.get_class_session(session_id)
        self.assertEqual([e for e in record.events if e["type"] == "assistant_exchange"], [])

        runtime.classroom.end_class_session(session_id)
        response = runtime.submit_assistant_message(
            project_id,
            "什么是人口密度",
            assistant_mode="teaching",
            teaching_context=self.teaching_context(session_id=session_id, phase="post_class"),
        )
        self.wait_for_job(runtime, response["job_id"])
        record = store.get_class_session(session_id)
        self.assertEqual([e for e in record.events if e["type"] == "assistant_exchange"], [])

    def test_report_statistics_count_assistant_exchanges(self) -> None:
        runtime, store, project_id = self.build_runtime()
        session_id = self.start_session(runtime, project_id)
        for message in ("什么是胡焕庸线", "东部为什么人口多"):
            response = runtime.submit_assistant_message(
                project_id,
                message,
                assistant_mode="teaching",
                teaching_context=self.teaching_context(session_id=session_id, phase="in_class"),
            )
            self.wait_for_job(runtime, response["job_id"])
        session = store.get_class_session(session_id)
        lesson = runtime.classroom.lesson_service.get_lesson(BUILTIN_LESSON_ID)
        statistics = runtime.classroom.report_service.build_statistics(session, lesson)
        self.assertEqual(statistics["assistant_exchange_count"], 2)

    # ------------------------------------------------------------------
    # P1-1: phase-differentiated routing + in-class retrieval skip
    # ------------------------------------------------------------------

    def test_post_class_phase_defaults_to_reflection(self) -> None:
        runtime, _store, _project_id = self.build_runtime()
        router = runtime.session_engine.router
        route = router.route(
            "teaching",
            "这节课学生的整体表现怎么样",
            [],
            {"teaching_context": {"phase": "post_class"}},
            {},
        )
        self.assertEqual(route["intent"], "teaching_reflect")
        self.assertIn("phase_default", route["reason"])

        route = router.route(
            "teaching",
            "打开人口密度图层",
            [],
            {"teaching_context": {"phase": "post_class"}},
            {},
        )
        self.assertEqual(route["intent"], "teaching_action")

        route = router.route(
            "teaching",
            "这节课学生的整体表现怎么样",
            [],
            {"teaching_context": {"phase": "in_class"}},
            {},
        )
        self.assertEqual(route["intent"], "teaching_explain")

    def test_classroom_verbs_route_to_teaching_action(self) -> None:
        runtime, _store, _project_id = self.build_runtime()
        router = runtime.session_engine.router
        for message in ("把第三题发给学生", "发布一道现场提问", "记一下这个误区"):
            route = router.route("teaching", message, [], {}, {})
            self.assertEqual(route["intent"], "teaching_action", message)

    def test_in_class_phase_skips_online_retrieval(self) -> None:
        runtime, _store, _project_id = self.build_runtime()
        knowledge = runtime.session_engine.knowledge
        fake_search = FakeResourceSearch()
        knowledge.resource_search = fake_search

        knowledge.answer(
            "什么是胡焕庸线",
            map_context={"teaching_context": {"phase": "in_class", "session_id": "x"}},
            teaching_task="teaching_explain",
        )
        self.assertEqual(fake_search.calls, [])

        knowledge.answer(
            "什么是胡焕庸线",
            map_context={"teaching_context": {"phase": "course_prep"}},
            teaching_task="teaching_explain",
        )
        self.assertEqual(len(fake_search.calls), 1)

    # ------------------------------------------------------------------
    # P1-2: real session records ground reflection
    # ------------------------------------------------------------------

    def test_reflection_prompt_quotes_real_session_records(self) -> None:
        runtime, _store, project_id = self.build_runtime(minimax_api_key="fake-key-for-tests")
        session_id = self.start_session(runtime, project_id)
        runtime.classroom.enter_session_stage(session_id, "s2")
        runtime.classroom.add_session_observation(
            session_id,
            {"stage_id": "s2", "verdict": "misconception", "tag": "混淆数量与密度", "note": ""},
        )

        fake_llm = FakeRecordingLLM()
        runtime.session_engine.knowledge.minimax_client = fake_llm
        runtime.session_engine.knowledge.resource_search = FakeResourceSearch()

        response = runtime.submit_assistant_message(
            project_id,
            "帮我复盘一下这节课",
            assistant_mode="teaching",
            teaching_context=self.teaching_context(session_id=session_id, stage_id="s2", phase="post_class"),
        )
        job = self.wait_for_job(runtime, response["job_id"])
        self.assertEqual(job["result"]["intent"], "teaching_reflect")
        self.assertTrue(fake_llm.calls)
        user_content = fake_llm.calls[-1][-1]["content"]
        self.assertIn("课堂真实记录", user_content)
        self.assertIn("混淆数量与密度", user_content)

    # ------------------------------------------------------------------
    # P1-3: record_observation tool
    # ------------------------------------------------------------------

    def test_record_observation_executes_with_session(self) -> None:
        runtime, store, project_id = self.build_runtime()
        session_id = self.start_session(runtime, project_id)
        runtime.classroom.enter_session_stage(session_id, "s2")

        result = runtime._execute_assistant_action(
            project_id,
            {"tool_name": "record_observation", "tool_params": {"verdict": "误区", "tag": "混淆数量与密度", "note": "把总量当密度比"}},
            {"teaching_context": self.teaching_context(session_id=session_id, stage_id="s2", phase="in_class")},
        )
        self.assertIn("已记录课堂学情", result["assistant_message"])
        record = store.get_class_session(session_id)
        observations = [e for e in record.events if e["type"] == "teacher_observation"]
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0]["payload"]["verdict"], "misconception")

    def test_record_observation_blocked_without_session(self) -> None:
        runtime, _store, _project_id = self.build_runtime()
        assessment = runtime.session_engine.tool_executor.assess(
            "webgis",
            [{"tool_name": "record_observation", "tool_params": {"verdict": "correct"}}],
            assistant_mode="teaching_action",
            map_context={"center": [104, 35]},
        )
        descriptor = assessment["actions_planned"][0]
        self.assertEqual(descriptor["risk_level"], "blocked")
        self.assertIn("班课", descriptor["validation_error"])

    def test_classroom_tools_blocked_for_ended_session(self) -> None:
        runtime, _store, project_id = self.build_runtime()
        session_id = self.start_session(runtime, project_id)
        runtime.classroom.end_class_session(session_id)

        assessment = runtime.session_engine.tool_executor.assess(
            "webgis",
            [{"tool_name": "record_observation", "tool_params": {"verdict": "misconception", "tag": "x"}}],
            assistant_mode="teaching_action",
            map_context={"teaching_context": self.teaching_context(session_id=session_id, phase="post_class")},
        )
        descriptor = assessment["actions_planned"][0]
        self.assertEqual(descriptor["risk_level"], "blocked")
        self.assertIn("已结束", descriptor["validation_error"])

    def test_record_observation_requires_explicit_verdict(self) -> None:
        runtime, _store, project_id = self.build_runtime()
        session_id = self.start_session(runtime, project_id)

        with self.assertRaises(ValueError) as ctx:
            runtime._execute_assistant_action(
                project_id,
                {"tool_name": "record_observation", "tool_params": {"note": "小组讨论质量很高"}},
                {"teaching_context": self.teaching_context(session_id=session_id, phase="in_class")},
            )
        self.assertIn("verdict", str(ctx.exception))
        record = runtime.store.get_class_session(session_id)
        self.assertEqual([e for e in record.events if e["type"] == "teacher_observation"], [])

    def test_launch_question_coerces_string_options_and_float_index(self) -> None:
        runtime, store, project_id = self.build_runtime()
        session_id = self.start_session(runtime, project_id)

        result = runtime._execute_assistant_action(
            project_id,
            {
                "tool_name": "launch_question",
                "tool_params": {"text": "谁更挤？", "options": "北京 / 上海", "answer_index": 1.0},
            },
            {"teaching_context": self.teaching_context(session_id=session_id, phase="in_class")},
        )
        active = result["active_question"]
        self.assertEqual(active["options"], ["北京", "上海"])
        self.assertEqual(active["answer_index"], 1)
        self.assertEqual(active["type"], "choice")
        self.assertEqual(store.get_class_session(session_id).active_question.get("text"), "谁更挤？")

    def test_v1_tool_mode_refuses_classroom_tools(self) -> None:
        runtime, store, project_id = self.build_runtime()
        session_id = self.start_session(runtime, project_id)

        plan = {
            "assistant_message": "计划发布提问。",
            "planner": "test_stub",
            "target": "webgis",
            "actions": [{"tool_name": "launch_question", "tool_params": {"text": "未确认直发"}}],
        }
        with mock.patch.object(runtime.llm_planner, "plan_actions", return_value=plan):
            response = runtime.submit_assistant_message(
                project_id,
                "把这道题发布给学生",
                assistant_mode="tool",
                map_context={"teaching_context": self.teaching_context(session_id=session_id, phase="in_class")},
            )
            job = self.wait_for_job(runtime, response["job_id"])

        self.assertEqual(job["status"], "completed")
        self.assertIn("专业教学智能体", job["result"]["assistant_message"])
        record = store.get_class_session(session_id)
        self.assertEqual(record.active_question, {})
        self.assertNotIn("question_launched", [event["type"] for event in record.events])

    # ------------------------------------------------------------------
    # P1-4: launch_question high-risk confirmation flow
    # ------------------------------------------------------------------

    def test_launch_question_full_confirmation_flow(self) -> None:
        runtime, store, project_id = self.build_runtime()
        session_id = self.start_session(runtime, project_id)
        runtime.classroom.enter_session_stage(session_id, "s3")

        plan = {
            "assistant_message": "准备向学生端发布提问。",
            "planner": "test_stub",
            "target": "webgis",
            "actions": [
                {
                    "tool_name": "launch_question",
                    "tool_params": {
                        "text": "为什么人口大城几乎都在胡焕庸线东南侧？",
                        "options": ["自然与经济条件叠加", "纯属历史巧合"],
                        "answer_index": 0,
                    },
                }
            ],
        }
        with mock.patch.object(runtime.session_engine.tool_planner, "plan", return_value=plan):
            response = runtime.submit_assistant_message(
                project_id,
                "把这道题发给学生",
                assistant_mode="teaching",
                teaching_context=self.teaching_context(session_id=session_id, stage_id="s3", phase="in_class"),
            )
            job = self.wait_for_job(runtime, response["job_id"])

        result = job["result"]
        self.assertTrue(result["requires_confirmation"])
        confirmation_id = result["confirmation_id"]
        self.assertTrue(confirmation_id)
        confirmation = store.get_confirmation(confirmation_id)
        self.assertIn("发布提问", confirmation.title)
        self.assertIn("胡焕庸线东南侧", confirmation.reason)

        self.assertEqual(store.get_class_session(session_id).active_question, {})

        # The class moves on before the teacher approves: the question must be
        # attributed to the CURRENT stage, not the plan-time one.
        runtime.classroom.enter_session_stage(session_id, "s4")

        confirm_response = runtime.confirm_assistant_action(confirmation_id, decision="approve")
        confirm_job = self.wait_for_job(runtime, confirm_response["job_id"])
        self.assertEqual(confirm_job["status"], "completed")
        executed = confirm_job["result"]["actions_executed"]
        self.assertEqual(len(executed), 1)
        self.assertIn("已向学生端发布提问", executed[0]["result"]["assistant_message"])

        record = store.get_class_session(session_id)
        self.assertEqual(record.active_question.get("text"), "为什么人口大城几乎都在胡焕庸线东南侧？")
        self.assertEqual(record.active_question.get("stage_id"), "s4")
        event_types = [event["type"] for event in record.events]
        self.assertIn("question_launched", event_types)
        # Exactly one exchange for the whole ask→confirm round trip (the
        # pending-confirmation reply must not double-count).
        self.assertEqual(event_types.count("assistant_exchange"), 1)

    def test_confirmation_invalidated_when_session_ended_before_approval(self) -> None:
        runtime, store, project_id = self.build_runtime()
        session_id = self.start_session(runtime, project_id)

        plan = {
            "assistant_message": "准备向学生端发布提问。",
            "planner": "test_stub",
            "target": "webgis",
            "actions": [{"tool_name": "launch_question", "tool_params": {"text": "下课前最后一题"}}],
        }
        with mock.patch.object(runtime.session_engine.tool_planner, "plan", return_value=plan):
            response = runtime.submit_assistant_message(
                project_id,
                "发布最后一题",
                assistant_mode="teaching",
                teaching_context=self.teaching_context(session_id=session_id, phase="in_class"),
            )
            job = self.wait_for_job(runtime, response["job_id"])
        confirmation_id = job["result"]["confirmation_id"]
        self.assertTrue(confirmation_id)

        runtime.classroom.end_class_session(session_id)

        confirm_response = runtime.confirm_assistant_action(confirmation_id, decision="approve")
        confirm_job = self.wait_for_job(runtime, confirm_response["job_id"])
        self.assertEqual(confirm_job["status"], "failed")
        self.assertIn("已结束", confirm_job.get("error") or "")
        confirmation = store.get_confirmation(confirmation_id)
        self.assertEqual(confirmation.status, "invalidated")
        record = store.get_class_session(session_id)
        self.assertNotIn("question_launched", [event["type"] for event in record.events])
        self.assertEqual(record.active_question, {})

    def test_launch_question_rejection_keeps_students_untouched(self) -> None:
        runtime, store, project_id = self.build_runtime()
        session_id = self.start_session(runtime, project_id)

        plan = {
            "assistant_message": "准备向学生端发布提问。",
            "planner": "test_stub",
            "target": "webgis",
            "actions": [{"tool_name": "launch_question", "tool_params": {"text": "临时提问"}}],
        }
        with mock.patch.object(runtime.session_engine.tool_planner, "plan", return_value=plan):
            response = runtime.submit_assistant_message(
                project_id,
                "发布一道临时提问",
                assistant_mode="teaching",
                teaching_context=self.teaching_context(session_id=session_id, phase="in_class"),
            )
            job = self.wait_for_job(runtime, response["job_id"])

        confirmation_id = job["result"]["confirmation_id"]
        reject_response = runtime.confirm_assistant_action(confirmation_id, decision="reject")
        reject_job = self.wait_for_job(runtime, reject_response["job_id"])
        self.assertEqual(reject_job["status"], "completed")
        record = store.get_class_session(session_id)
        self.assertEqual(record.active_question, {})
        self.assertNotIn("question_launched", [event["type"] for event in record.events])


if __name__ == "__main__":
    unittest.main()
