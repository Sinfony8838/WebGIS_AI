from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.app.config import AppConfig
from backend.app.runtime import WebGISRuntime
from backend.app.store import RuntimeStore


def _bank_question() -> dict:
    """带完整答案/解析/考点的题库快照题（投屏揭示路径的核心用例）。"""
    return {
        "question_id": "qb_pop_1",
        "type": "choice",
        "source": "question_bank",
        "text": "影响人口分布的最主要自然因素组合是？",
        "task_text": "读图完成下列各题。",
        "material": "下图为世界人口密度分布示意图。",
        "options": ["气候与地形", "政策与文化", "宗教与语言", "历史与军事"],
        "answer": "气候与地形",
        "answer_letter": "A",
        "answer_index": 0,
        "explanation": "中低纬度沿海平原气候适宜、地形平坦，集中了大部分人口。",
        "sub_questions": [],
        "images": [],
        "answer_complete": True,
        "knowledge_points": ["人口分布", "自然因素"],
        "expected_points": ["人口分布", "自然因素"],
        "misconceptions": [],
        "suggested_seconds": 120,
        "explanation_source": "official",
    }


class ClassQuestionPracticeTest(unittest.TestCase):
    def setUp(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        root_dir = Path(__file__).resolve().parents[2]
        config = AppConfig(root_dir=root_dir)
        config.data_dir = Path(temp_dir.name) / "backend" / "data"
        config.state_dir = config.data_dir / "state"
        config.uploads_dir = config.data_dir / "uploads"
        config.outputs_dir = config.data_dir / "outputs"
        config.state_file = config.state_dir / "runtime.json"
        # 测试环境强制无 LLM key：AI 讲解必须走规则回退，不发起真实请求。
        config.minimax_api_key = ""
        config.minimax_token_plan_key = ""
        config.ensure_dirs()
        self.store = RuntimeStore(config.state_file)
        self.runtime = WebGISRuntime(config=config, store=self.store)
        self.project_id = self.runtime.create_project()["project_id"]
        self.addCleanup(temp_dir.cleanup)

        self.lesson = self.runtime.classroom.lesson_service.create_lesson(
            {
                "title": "人口分布投屏课",
                "subject": "地理",
                "grade": "高一",
                "objectives": ["描述人口分布格局"],
                "stages": [
                    {
                        "stage_id": "s1",
                        "title": "读图探究",
                        "minutes": 10,
                        "questions": [_bank_question()],
                        "scene": {
                            "basemap_id": "",
                            "templates": [],
                            "layer_visibility": {},
                            "view": {},
                            "annotations": [],
                        },
                    }
                ],
                "metadata": {"project_id": self.project_id},
            },
            source="assistant_draft",
            owner_user_id="local_admin",
        )
        self.session_id = self.runtime.classroom.create_class_session(
            self.lesson.lesson_id, self.project_id
        )["session"]["session_id"]

    def backdate_running_since(self, seconds: int) -> None:
        """把当前 running 段起点改到过去，模拟已经计时的秒数（避免真实等待）。"""
        session = self.store.get_class_session(self.session_id)
        active = dict(session.active_question)
        active["timer"]["running_since"] = (
            datetime.now(timezone.utc) - timedelta(seconds=seconds)
        ).isoformat()
        self.store.set_active_question(self.session_id, active)

    def events(self, event_type: str) -> list:
        session = self.store.get_class_session(self.session_id)
        return [event for event in session.events if event["type"] == event_type]

    # ------------------------------------------------------------------
    # 投屏启动：服务端计时状态初始化 + 事件不含答案
    # ------------------------------------------------------------------

    def test_projection_launch_initializes_server_timer(self) -> None:
        launch = self.runtime.classroom.launch_session_question(
            self.session_id, stage_id="s1", question_id="qb_pop_1"
        )
        timer = launch["active_question"]["timer"]
        self.assertEqual(timer["status"], "idle")
        self.assertEqual(timer["suggested_seconds"], 120)
        self.assertEqual(timer["question_source"], "question_bank")
        self.assertFalse(timer["revealed"])
        self.assertIsNone(timer["actual_seconds"])

        # 题目投屏事件只含题面字段，不含答案。
        launched = self.events("question_launched")
        self.assertEqual(len(launched), 1)
        self.assertEqual(
            sorted(launched[0]["payload"].keys()),
            ["options", "question_id", "text", "type"],
        )

        # 服务端持久化：断线重连/刷新后重新读取会话即可恢复计时状态。
        restored = self.store.get_class_session(self.session_id)
        self.assertEqual(restored.active_question["timer"]["status"], "idle")
        self.assertEqual(restored.active_question["timer"]["question_source"], "question_bank")

        # 口头提问不建计时（不进学生端）。
        oral = self.runtime.classroom.launch_session_question(
            self.session_id, stage_id="s1", question_id="qb_pop_1", delivery="teacher_oral"
        )
        self.assertEqual(oral["active_question"], {})
        # 注意：student 投屏仍保持活跃题；口头提问只是另发一个事件。

    # ------------------------------------------------------------------
    # 计时状态机：开始 / 暂停 / 继续 / 重置
    # ------------------------------------------------------------------

    def test_timer_lifecycle_start_pause_resume_reset(self) -> None:
        cw = self.runtime.classroom
        cw.launch_session_question(self.session_id, stage_id="s1", question_id="qb_pop_1")

        with self.assertRaises(ValueError):
            cw.update_question_timer(self.session_id, "pause")  # idle 不能暂停
        started = cw.update_question_timer(self.session_id, "start")
        self.assertEqual(started["timer"]["status"], "running")
        self.assertEqual(started["timer"]["elapsed_seconds"], 0)
        self.assertNotEqual(started["timer"]["running_since"], "")
        with self.assertRaises(ValueError):
            cw.update_question_timer(self.session_id, "start")  # 重复开始
        with self.assertRaises(ValueError):
            cw.update_question_timer(self.session_id, "resume")  # running 不能继续
        with self.assertRaises(ValueError):
            cw.update_question_timer(self.session_id, "fast_forward")  # 未知动作

        self.backdate_running_since(65)
        paused = cw.update_question_timer(self.session_id, "pause")
        self.assertEqual(paused["timer"]["status"], "paused")
        self.assertEqual(paused["timer"]["elapsed_seconds"], 65)
        self.assertEqual(paused["timer"]["running_since"], "")

        resumed = cw.update_question_timer(self.session_id, "resume")
        self.assertEqual(resumed["timer"]["status"], "running")
        self.assertGreaterEqual(resumed["timer"]["elapsed_seconds"], 65)  # 暂停累计被保留

        self.backdate_running_since(10)
        reset = cw.update_question_timer(self.session_id, "reset")
        self.assertEqual(reset["timer"]["status"], "idle")
        self.assertEqual(reset["timer"]["elapsed_seconds"], 0)
        self.assertEqual(reset["timer"]["reset_count"], 1)

        actions = [event["payload"]["action"] for event in self.events("question_timer")]
        self.assertEqual(actions, ["start", "pause", "resume", "reset"])
        # 计时事件只含时长信息，不含答案。
        for event in self.events("question_timer"):
            self.assertNotIn("answer", event["payload"])
            self.assertNotIn("explanation", event["payload"])

    # ------------------------------------------------------------------
    # 揭示：记录实际用时/超时/来源 + 官方答案 + AI 讲解（规则回退）
    # ------------------------------------------------------------------

    def test_reveal_records_duration_and_official_payload(self) -> None:
        cw = self.runtime.classroom
        cw.launch_session_question(self.session_id, stage_id="s1", question_id="qb_pop_1")
        cw.update_question_timer(self.session_id, "start")
        self.backdate_running_since(200)

        revealed = cw.reveal_session_question(self.session_id)
        timer = revealed["timer"]
        self.assertEqual(timer["status"], "revealed")
        self.assertTrue(timer["revealed"])
        self.assertEqual(timer["actual_seconds"], 200)
        self.assertEqual(timer["overtime_seconds"], 80)  # 200 - 120
        self.assertEqual(timer["question_source"], "question_bank")

        official = revealed["official"]
        self.assertEqual(official["answer"], "气候与地形")
        self.assertEqual(official["answer_index"], 0)
        self.assertEqual(official["explanation"], "中低纬度沿海平原气候适宜、地形平坦，集中了大部分人口。")
        self.assertEqual(official["knowledge_points"], ["人口分布", "自然因素"])
        self.assertTrue(official["answer_complete"])

        # 测试环境无 MiniMax key：AI 讲解退回规则拼装，内容来自官方信息。
        self.assertEqual(revealed["ai_explanation"]["generator"], "rules")
        self.assertIn("气候与地形", revealed["ai_explanation"]["text"])

        # 揭示事件记录用时/超时/来源，不携带答案。
        events = self.events("question_revealed")
        self.assertEqual(len(events), 1)
        payload = events[0]["payload"]
        self.assertEqual(payload["actual_seconds"], 200)
        self.assertEqual(payload["overtime_seconds"], 80)
        self.assertEqual(payload["source"], "question_bank")
        self.assertNotIn("answer", payload)
        self.assertNotIn("explanation", payload)

        # 幂等：刷新后重复揭示不再产生事件，也不重置用时。
        again = cw.reveal_session_question(self.session_id)
        self.assertEqual(again["timer"]["actual_seconds"], 200)
        self.assertEqual(len(self.events("question_revealed")), 1)

        # 揭示后计时不可再操作。
        with self.assertRaises(ValueError):
            cw.update_question_timer(self.session_id, "start")

        # 学生端永远看不到答案与计时状态。
        join_code = self.store.get_class_session(self.session_id).join_code
        student = cw.student_state(join_code, nickname="小李")
        self.assertEqual(student["active_question"]["question_id"], "qb_pop_1")
        self.assertNotIn("answer", student["active_question"])
        self.assertNotIn("timer", student["active_question"])

        # 揭示后收题：事件记录 revealed=True 与揭示时的用时。
        closed = cw.close_session_question(self.session_id)
        self.assertEqual(closed["status"], "success")
        closed_events = self.events("question_closed")
        self.assertEqual(len(closed_events), 1)
        closed_payload = closed_events[0]["payload"]
        self.assertTrue(closed_payload["revealed"])
        self.assertEqual(closed_payload["actual_seconds"], 200)
        self.assertEqual(closed_payload["overtime_seconds"], 80)
        self.assertEqual(closed_payload["source"], "question_bank")

    # ------------------------------------------------------------------
    # 未揭示收题：记录「未揭示答案」事实与最终用时
    # ------------------------------------------------------------------

    def test_close_without_reveal_records_unrevealed(self) -> None:
        cw = self.runtime.classroom
        cw.launch_session_question(self.session_id, stage_id="s1", question_id="qb_pop_1")
        cw.update_question_timer(self.session_id, "start")
        self.backdate_running_since(50)

        cw.close_session_question(self.session_id)
        events = self.events("question_closed")
        self.assertEqual(len(events), 1)
        payload = events[0]["payload"]
        self.assertFalse(payload["revealed"])
        self.assertEqual(payload["actual_seconds"], 50)
        self.assertEqual(payload["overtime_seconds"], 0)
        self.assertEqual(payload["source"], "question_bank")

        # 收题后活跃题清空，学生端回到等待态，计时操作不再可用。
        self.assertEqual(self.store.get_class_session(self.session_id).active_question, {})
        with self.assertRaises(ValueError):
            cw.update_question_timer(self.session_id, "start")
        with self.assertRaises(ValueError):
            cw.reveal_session_question(self.session_id)

    def test_close_without_timer_backfill_and_end_session_finalizes(self) -> None:
        """旧数据兼容：无 timer 的活跃题可正常收题；结束时未收的投屏题按未揭示收口。"""
        cw = self.runtime.classroom
        cw.launch_session_question(self.session_id, stage_id="s1", question_id="qb_pop_1")
        # 模拟历史数据：直接抹掉 timer 字段。
        session = self.store.get_class_session(self.session_id)
        active = dict(session.active_question)
        active.pop("timer", None)
        self.store.set_active_question(self.session_id, active)

        # 收题仍成功，事件不带计时字段（未揭示事实无从谈起）。
        cw.close_session_question(self.session_id)
        payload = self.events("question_closed")[0]["payload"]
        self.assertNotIn("revealed", payload)

        # 结束课堂前还有一道未揭示的投屏题：按未揭示事实收口。
        cw.launch_session_question(self.session_id, stage_id="s1", question_id="qb_pop_1")
        cw.update_question_timer(self.session_id, "start")
        self.backdate_running_since(30)
        cw.end_class_session(self.session_id)
        closed = [event for event in self.events("question_closed") if event["payload"].get("revealed") is False]
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["payload"]["actual_seconds"], 30)
        ended = self.store.get_class_session(self.session_id)
        self.assertEqual(ended.status, "ended")
        self.assertEqual(ended.active_question, {})
        # 已结束的课堂不能再计时或揭示。
        with self.assertRaises(ValueError):
            cw.update_question_timer(self.session_id, "start")
        with self.assertRaises(ValueError):
            cw.reveal_session_question(self.session_id)

    def test_adhoc_projection_labels_source_and_explains_honestly(self) -> None:
        """临时题投屏：来源标记 adhoc；无官方答案时讲解如实说明，不编造。"""
        cw = self.runtime.classroom
        launch = cw.launch_session_question(
            self.session_id,
            stage_id="s1",
            adhoc={"text": "临场投票：这题选哪个？", "options": ["A", "B"]},
        )
        timer = launch["active_question"]["timer"]
        self.assertEqual(timer["question_source"], "adhoc")
        cw.update_question_timer(self.session_id, "start")
        revealed = cw.reveal_session_question(self.session_id)
        self.assertEqual(revealed["official"]["answer"], "")
        self.assertFalse(revealed["official"]["answer_complete"])
        self.assertEqual(revealed["ai_explanation"]["generator"], "rules")
        self.assertIn("暂无官方答案", revealed["ai_explanation"]["text"])

    def test_replacing_projection_closes_previous_question_with_facts(self) -> None:
        """换题投屏时上一题按事实收口，不丢计时证据。"""
        cw = self.runtime.classroom
        cw.launch_session_question(self.session_id, stage_id="s1", question_id="qb_pop_1")
        cw.update_question_timer(self.session_id, "start")
        self.backdate_running_since(40)

        replacement = cw.launch_session_question(
            self.session_id,
            stage_id="s1",
            adhoc={"text": "换一道临场题", "options": []},
        )
        self.assertNotEqual(replacement["active_question"]["question_id"], "qb_pop_1")
        closed = [event for event in self.events("question_closed") if event["payload"]["question_id"] == "qb_pop_1"]
        self.assertEqual(len(closed), 1)
        self.assertFalse(closed[0]["payload"]["revealed"])
        self.assertEqual(closed[0]["payload"]["actual_seconds"], 40)
        # 新题成为唯一活跃题。
        active = self.store.get_class_session(self.session_id).active_question
        self.assertEqual(active["question_id"], replacement["active_question"]["question_id"])

    def test_session_reads_return_live_computed_timer(self) -> None:
        """会话读取接口返回实时计算后的计时视图，前端无需再自行推算。"""
        cw = self.runtime.classroom
        cw.launch_session_question(self.session_id, stage_id="s1", question_id="qb_pop_1")
        cw.update_question_timer(self.session_id, "start")
        self.backdate_running_since(73)

        fetched = cw.get_class_session(self.session_id)
        timer = fetched["session"]["active_question"]["timer"]
        self.assertEqual(timer["status"], "running")
        self.assertGreaterEqual(timer["elapsed_seconds"], 73)
        live = cw.session_live(self.session_id)
        self.assertGreaterEqual(live["active_question"]["timer"]["elapsed_seconds"], 73)
        listed = cw.list_class_sessions(project_id=self.project_id)
        running_item = next(item for item in listed["items"] if item["session_id"] == self.session_id)
        self.assertGreaterEqual(running_item["active_question"]["timer"]["elapsed_seconds"], 73)
        # 持久化层仍是「累计值 + 段起点」，实时视图没有污染存储。
        persisted = self.store.get_class_session(self.session_id).active_question["timer"]
        self.assertEqual(persisted["elapsed_seconds"], 0)


if __name__ == "__main__":
    unittest.main()
