from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.config import AppConfig
from backend.app.runtime import WebGISRuntime
from backend.app.store import RuntimeStore


BUILTIN_LESSON_ID = "lesson_builtin_population_distribution"


class ClassSessionTest(unittest.TestCase):
    def build_runtime(self) -> tuple[WebGISRuntime, RuntimeStore, str]:
        temp_dir = tempfile.TemporaryDirectory()
        root_dir = Path(__file__).resolve().parents[2]
        config = AppConfig(root_dir=root_dir)
        config.data_dir = Path(temp_dir.name) / "backend" / "data"
        config.state_dir = config.data_dir / "state"
        config.uploads_dir = config.data_dir / "uploads"
        config.outputs_dir = config.data_dir / "outputs"
        config.state_file = config.state_dir / "runtime.json"
        config.ensure_dirs()
        store = RuntimeStore(config.state_file)
        runtime = WebGISRuntime(config=config, store=store)
        project = runtime.create_project()
        self.addCleanup(temp_dir.cleanup)
        return runtime, store, project["project_id"]

    def start_session(self, runtime: WebGISRuntime, project_id: str) -> dict:
        return runtime.classroom.create_class_session(BUILTIN_LESSON_ID, project_id)

    def test_session_lifecycle_and_events(self) -> None:
        runtime, store, project_id = self.build_runtime()

        response = self.start_session(runtime, project_id)
        self.assertEqual(response["status"], "success")
        session = response["session"]
        self.assertEqual(session["status"], "running")
        self.assertEqual(len(session["join_code"]), 6)
        self.assertIn("/student/", response["student_join_url"])

        session_id = session["session_id"]
        result = runtime.classroom.enter_session_stage(session_id, "s1")
        self.assertEqual(result["stage"]["stage_id"], "s1")

        record = store.get_class_session(session_id)
        event_types = [event["type"] for event in record.events]
        self.assertIn("session_start", event_types)
        self.assertIn("stage_enter", event_types)
        self.assertIn("scene_applied", event_types)

        ended = runtime.classroom.end_class_session(session_id)
        self.assertNotEqual(ended["session"]["ended_at"], "")
        record = store.get_class_session(session_id)
        self.assertEqual(record.status, "ended")
        self.assertIn("session_end", [event["type"] for event in record.events])
        with self.assertRaises(ValueError):
            runtime.classroom.enter_session_stage(session_id, "s2")

    def test_question_launch_answer_and_tally(self) -> None:
        runtime, store, project_id = self.build_runtime()
        session_id = self.start_session(runtime, project_id)["session"]["session_id"]
        runtime.classroom.enter_session_stage(session_id, "s4")

        launch = runtime.classroom.launch_session_question(session_id, question_id="s4q1")
        active = launch["active_question"]
        self.assertEqual(active["type"], "choice")
        join_code = store.get_class_session(session_id).join_code

        state = runtime.classroom.student_state(join_code, nickname="小李")
        self.assertEqual(state["active_question"]["question_id"], "s4q1")
        self.assertNotIn("answer_index", state["active_question"])

        runtime.classroom.student_answer(join_code, {"nickname": "小李", "question_id": "s4q1", "choice_index": 2})
        runtime.classroom.student_answer(join_code, {"nickname": "小王", "question_id": "s4q1", "choice_index": 0})
        # 同一昵称重复提交应覆盖旧答案
        runtime.classroom.student_answer(join_code, {"nickname": "小王", "question_id": "s4q1", "choice_index": 2})

        live = runtime.classroom.session_live(session_id)
        self.assertEqual(live["tally"]["total"], 2)
        self.assertEqual(live["tally"]["option_counts"][2], 2)
        self.assertEqual(live["tally"]["correct_rate"], 1.0)
        self.assertGreaterEqual(live["joined_count"], 2)

        closed = runtime.classroom.close_session_question(session_id)
        self.assertEqual(closed["tally"]["total"], 2)
        record = store.get_class_session(session_id)
        self.assertEqual(record.active_question, {})

        with self.assertRaises(ValueError):
            runtime.classroom.student_answer(join_code, {"nickname": "小赵", "question_id": "s4q1", "choice_index": 1})

    def test_invalid_student_answers_rejected(self) -> None:
        runtime, store, project_id = self.build_runtime()
        session_id = self.start_session(runtime, project_id)["session"]["session_id"]
        runtime.classroom.enter_session_stage(session_id, "s4")
        runtime.classroom.launch_session_question(session_id, question_id="s4q1")
        join_code = store.get_class_session(session_id).join_code

        with self.assertRaises(ValueError):
            runtime.classroom.student_answer(join_code, {"nickname": "越界", "question_id": "s4q1", "choice_index": 9})
        with self.assertRaises(KeyError):
            runtime.classroom.student_answer("000000" if join_code != "000000" else "111111", {"question_id": "s4q1", "choice_index": 1})

    def test_student_answer_persists_response_and_event_in_one_write(self) -> None:
        runtime, store, project_id = self.build_runtime()
        session_id = self.start_session(runtime, project_id)["session"]["session_id"]
        runtime.classroom.enter_session_stage(session_id, "s4")
        runtime.classroom.launch_session_question(session_id, question_id="s4q1")
        join_code = store.get_class_session(session_id).join_code

        with patch.object(store, "_write_state_file", wraps=store._write_state_file) as write_state:
            runtime.classroom.student_answer(
                join_code,
                {"nickname": "Student A", "question_id": "s4q1", "choice_index": 2},
            )

        self.assertEqual(write_state.call_count, 1)
        session = store.get_class_session(session_id)
        self.assertEqual(len(session.responses["s4q1"]), 1)
        answer_events = [event for event in session.events if event["type"] == "student_response"]
        self.assertEqual(len(answer_events), 1)
        self.assertEqual(answer_events[0]["payload"]["choice_index"], 2)

    def test_teacher_observation_and_adhoc_question(self) -> None:
        runtime, store, project_id = self.build_runtime()
        session_id = self.start_session(runtime, project_id)["session"]["session_id"]
        runtime.classroom.enter_session_stage(session_id, "s2")

        observation = runtime.classroom.add_session_observation(
            session_id,
            {"stage_id": "s2", "question_id": "s2q1", "verdict": "misconception", "tag": "混淆数量与密度", "note": "有学生认为山东人口密度一定比新疆低"},
        )
        self.assertEqual(observation["event"]["payload"]["verdict"], "misconception")
        with self.assertRaises(ValueError):
            runtime.classroom.add_session_observation(session_id, {"verdict": "unknown"})

        adhoc = runtime.classroom.launch_session_question(
            session_id,
            stage_id="s2",
            adhoc={"text": "临时投票：大家同意吗？", "options": ["同意", "不同意"]},
        )
        self.assertEqual(adhoc["active_question"]["type"], "choice")
        self.assertTrue(adhoc["active_question"]["question_id"].startswith("adhoc_"))

    def test_teacher_oral_question_records_evidence_without_opening_student_poll(self) -> None:
        runtime, store, project_id = self.build_runtime()
        session_id = self.start_session(runtime, project_id)["session"]["session_id"]

        presented = runtime.classroom.launch_session_question(
            session_id,
            stage_id="s1",
            question_id="s1q1",
            delivery="teacher_oral",
        )

        self.assertEqual(presented["active_question"], {})
        self.assertEqual(presented["presented_question"]["delivery"], "teacher_oral")
        session = store.get_class_session(session_id)
        self.assertEqual(session.active_question, {})
        events = [event for event in session.events if event["type"] == "teacher_question_presented"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["payload"]["question_id"], "s1q1")

    def test_teacher_only_report_marks_student_response_data_uncollected(self) -> None:
        runtime, store, project_id = self.build_runtime()
        runtime.classroom.report_service.minimax_client = None
        session_id = self.start_session(runtime, project_id)["session"]["session_id"]
        runtime.classroom.enter_session_stage(session_id, "s1")
        runtime.classroom.launch_session_question(
            session_id,
            stage_id="s1",
            question_id="s1q1",
            delivery="teacher_oral",
        )
        runtime.classroom.add_session_observation(
            session_id,
            {"stage_id": "s1", "question_id": "s1q1", "verdict": "partial", "tag": "", "note": "只描述了东多西少"},
        )
        runtime.classroom.end_class_session(session_id)

        session = store.get_class_session(session_id)
        lesson = store.get_lesson(session.lesson_id)
        statistics = runtime.classroom.report_service.build_statistics(session, lesson)
        diagnosis = runtime.classroom.report_service.compose_diagnosis(statistics)
        practice = runtime.classroom.report_service.build_practice_recommendations(statistics, lesson)
        markdown = runtime.classroom.report_service.render_markdown(statistics, diagnosis, practice)

        self.assertFalse(statistics["response_data_collected"])
        self.assertEqual(statistics["participant_count"], 0)
        self.assertEqual(statistics["questions"][0]["collection_mode"], "teacher_observation")
        self.assertIsNone(statistics["questions"][0]["correct_rate"])
        self.assertIn("学生端作答数据：未采集", markdown)
        self.assertIn("教师口头呈现", markdown)
        self.assertIn("未采集学生端作答数据", diagnosis["text"])
        self.assertEqual(len(practice), 3)
        self.assertEqual(practice[0]["title"], "人口总量与人口密度辨析")
        self.assertIn("没有足够证据判定全班共性误区", practice[0]["evidence_basis"])
        self.assertIn("课后推荐练习巩固", markdown)
        self.assertIn("不计入40分钟正式课时", markdown)

    def test_teacher_only_report_never_uses_llm_to_infer_student_performance(self) -> None:
        class HallucinatingClient:
            def chat_completion(self, *_args, **_kwargs):
                return "学生错误率达到 80%，并且普遍误解了胡焕庸线。"

        runtime, store, project_id = self.build_runtime()
        runtime.classroom.report_service.minimax_client = HallucinatingClient()
        session_id = self.start_session(runtime, project_id)["session"]["session_id"]
        runtime.classroom.enter_session_stage(session_id, "s1")
        runtime.classroom.launch_session_question(
            session_id,
            stage_id="s1",
            question_id="s1q1",
            delivery="teacher_oral",
        )
        runtime.classroom.add_session_observation(
            session_id,
            {"stage_id": "s1", "question_id": "s1q1", "verdict": "partial", "tag": "", "note": ""},
        )
        runtime.classroom.end_class_session(session_id)

        session = store.get_class_session(session_id)
        lesson = store.get_lesson(session.lesson_id)
        statistics = runtime.classroom.report_service.build_statistics(session, lesson)
        diagnosis = runtime.classroom.report_service.compose_diagnosis(statistics)

        self.assertEqual(diagnosis["generator"], "rules")
        self.assertIn("未采集学生端作答数据", diagnosis["text"])
        self.assertNotIn("80%", diagnosis["text"])
        self.assertNotIn("普遍误解", diagnosis["text"])

    def test_default_anonymous_nickname_is_not_counted_as_a_participant(self) -> None:
        runtime, store, project_id = self.build_runtime()
        session_id = self.start_session(runtime, project_id)["session"]["session_id"]
        runtime.classroom.enter_session_stage(session_id, "s1")
        runtime.classroom.launch_session_question(session_id, question_id="s1q1")
        join_code = store.get_class_session(session_id).join_code

        runtime.classroom.student_answer(join_code, {"question_id": "s1q1", "choice_index": 1})

        session = store.get_class_session(session_id)
        lesson = store.get_lesson(session.lesson_id)
        statistics = runtime.classroom.report_service.build_statistics(session, lesson)
        self.assertEqual(statistics["participant_count"], 0)

    def test_report_generation_with_rule_fallback(self) -> None:
        runtime, store, project_id = self.build_runtime()
        # 本用例断言规则诊断路径：即使宿主机配置了 MiniMax key 也不走真实 LLM。
        runtime.classroom.report_service.minimax_client = None
        session_id = self.start_session(runtime, project_id)["session"]["session_id"]
        runtime.classroom.enter_session_stage(session_id, "s1")
        runtime.classroom.launch_session_question(session_id, question_id="s1q1")
        join_code = store.get_class_session(session_id).join_code
        runtime.classroom.student_answer(join_code, {"nickname": "小李", "question_id": "s1q1", "choice_index": 1})
        runtime.classroom.student_answer(join_code, {"nickname": "小王", "question_id": "s1q1", "choice_index": 0})
        runtime.classroom.close_session_question(session_id)
        runtime.classroom.add_session_observation(
            session_id,
            {"stage_id": "s1", "verdict": "misconception", "tag": "只见城市不见格局", "note": ""},
        )
        runtime.classroom.end_class_session(session_id)

        submitted = runtime.classroom.submit_session_report(session_id)
        job_id = submitted["job_id"]
        for _ in range(50):
            job = runtime.get_job(job_id)
            if job["status"] in {"completed", "failed"}:
                break
            time.sleep(0.1)
        self.assertEqual(job["status"], "completed")

        statistics = job["result"]["statistics"]
        self.assertEqual(statistics["participant_count"], 2)
        self.assertEqual(len(statistics["questions"]), 1)
        self.assertEqual(statistics["questions"][0]["correct_rate"], 0.5)
        self.assertEqual(statistics["observations"]["verdict_counts"]["misconception"], 1)
        # 无 LLM 环境走规则诊断
        self.assertEqual(job["result"]["diagnosis"]["generator"], "rules")
        self.assertIn("学情诊断", job["result"]["diagnosis"]["text"])
        self.assertEqual(len(job["result"]["practice_recommendations"]), 3)

        report_artifacts = [item for item in store.list_outputs(project_id) if item["artifact_type"] == "class_report"]
        self.assertEqual(len(report_artifacts), 1)
        report_path = Path(report_artifacts[0]["path"])
        self.assertTrue(report_path.is_file())
        content = report_path.read_text(encoding="utf-8")
        self.assertIn("课堂报告", content)
        self.assertIn("只见城市不见格局", content)
        self.assertIn("课后推荐练习巩固", content)


if __name__ == "__main__":
    unittest.main()
