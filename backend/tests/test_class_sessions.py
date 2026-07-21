from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from backend.app.config import AppConfig
from backend.app.runtime import WebGISRuntime
from backend.app.store import RuntimeStore


BUILTIN_LESSON_ID = "lesson_builtin_population_distribution"
TOPIC_LESSON_ID = "lesson_population_topic_distribution"


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

        report_artifacts = [item for item in store.list_outputs(project_id) if item["artifact_type"] == "class_report"]
        self.assertEqual(len(report_artifacts), 1)
        report_path = Path(report_artifacts[0]["path"])
        self.assertTrue(report_path.is_file())
        content = report_path.read_text(encoding="utf-8")
        self.assertIn("课堂报告", content)
        self.assertIn("只见城市不见格局", content)

    def test_population_topic_requires_map_evidence_and_reports_coverage(self) -> None:
        runtime, store, project_id = self.build_runtime()
        runtime.classroom.report_service.minimax_client = None
        session = runtime.classroom.create_class_session(TOPIC_LESSON_ID, project_id)["session"]
        session_id = session["session_id"]
        join_code = session["join_code"]
        runtime.classroom.enter_session_stage(session_id, "s1")
        runtime.classroom.launch_session_question(session_id, question_id="pd1q1")

        public_question = runtime.classroom.student_state(join_code, nickname="学生甲")["active_question"]
        self.assertTrue(public_question["evidence_required"])
        self.assertTrue(public_question["evidence_options"])
        with self.assertRaises(ValueError):
            runtime.classroom.student_answer(join_code, {"nickname": "学生甲", "question_id": "pd1q1", "choice_index": 1})

        runtime.classroom.student_answer(
            join_code,
            {
                "nickname": "学生甲",
                "question_id": "pd1q1",
                "choice_index": 1,
                "evidence_ids": ["east_dense"],
            },
        )
        record = store.get_class_session(session_id)
        statistics = runtime.classroom.report_service.build_statistics(record, store.get_lesson(TOPIC_LESSON_ID))
        self.assertEqual(statistics["evidence"]["required_question_count"], 1)
        self.assertEqual(statistics["evidence"]["coverage_rate"], 1.0)
        self.assertEqual(statistics["questions"][0]["evidence_counts"]["east_dense"], 1)


if __name__ == "__main__":
    unittest.main()
