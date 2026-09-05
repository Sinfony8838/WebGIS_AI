from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.app.config import AppConfig
from backend.app.models import LessonRecord
from backend.app.runtime import WebGISRuntime
from backend.app.store import RuntimeStore


def _valid_plan() -> dict:
    """一份可通过预演校验的最小完整教案（40 分钟、两个环节、目标均有活动支撑）。"""
    question = {
        "question_id": "q_s1_1",
        "type": "open",
        "text": "指出世界人口分布的稠密区域并说明共同自然条件。",
        "options": [],
        "answer_index": None,
        "expected_points": [],
        "misconceptions": [],
    }
    manual = {
        "question_id": "q_s2_1",
        "type": "open",
        "source": "teacher_manual",
        "text": "用一句话概括胡焕庸线的地理意义。",
        "options": [],
        "answer_index": None,
        "answer": "中国人口分布东南稠密、西北稀疏的近似分界线。",
        "explanation": "瑷珲—腾冲线两侧人口密度差异显著。",
        "expected_points": [],
        "misconceptions": [],
    }
    return {
        "title": "人口分布",
        "grade": "高一",
        "duration_minutes": 40,
        "objectives": ["描述世界人口分布格局", "解释人口分布的自然成因"],
        "core_questions": {
            "core": "世界人口为什么这样分布？",
            "sub_questions": ["人口集中在哪里？", "为什么集中在这里？"],
        },
        "design_thinking": "以世界人口密度图切入，先描述分布格局，再用地形与气候图层叠加探究成因，最后用胡焕庸线迁移回中国情境，形成区域认知与综合思维的双重训练。",
        "homework": {"basic": ["完成地图册人口分布练习"], "inquiry": ["查一个国家的人口分布并解释"]},
        "stages": [
            {
                "stage_id": "s1",
                "title": "情境导入与分布描述",
                "minutes": 12,
                "knowledge_conclusion": "世界人口呈斑块状集中在中低纬度沿海平原。",
                "student_activities": ["读世界人口密度图，圈画稠密区"],
                "question_chain": ["人口集中在哪里？"],
                "objective_refs": [1],
                "questions": [question],
                "scene": {"basemap_id": "", "templates": [], "layer_visibility": {}, "view": {}, "annotations": []},
            },
            {
                "stage_id": "s2",
                "title": "成因探究与迁移",
                "minutes": 28,
                "knowledge_conclusion": "气候、地形与水源共同决定人口分布格局。",
                "student_activities": ["叠加地形与气候图层，小组归纳成因"],
                "question_chain": ["为什么集中在这里？"],
                "objective_refs": [2],
                "questions": [manual],
                "scene": {"basemap_id": "", "templates": [], "layer_visibility": {}, "view": {}, "annotations": []},
            },
        ],
    }


class LessonRehearsalServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root_dir = Path(__file__).resolve().parents[2]
        config = AppConfig(root_dir=root_dir)
        config.data_dir = Path(self.temp_dir.name) / "backend" / "data"
        config.state_dir = config.data_dir / "state"
        config.uploads_dir = config.data_dir / "uploads"
        config.outputs_dir = config.data_dir / "outputs"
        config.state_file = config.state_dir / "runtime.json"
        config.minimax_api_key = ""
        config.minimax_token_plan_key = ""
        config.ensure_dirs()
        self.store = RuntimeStore(config.state_file)
        self.runtime = WebGISRuntime(config=config, store=self.store)
        self.project = self.runtime.create_project()["project_id"]
        self.addCleanup(self.temp_dir.cleanup)

    def make_lesson(self) -> LessonRecord:
        plan = _valid_plan()
        return self.runtime.classroom.lesson_service.create_lesson(
            {
                "title": plan["title"],
                "subject": "地理",
                "grade": plan["grade"],
                "objectives": plan["objectives"],
                "stages": plan["stages"],
                "metadata": {
                    "design_id": "design_x",
                    "project_id": self.project,
                    "created_from": "lesson_design",
                    "lesson_version": 1,
                    "ready_for_class": False,
                },
                "plan": plan,
            },
            source="assistant_draft",
            owner_user_id="local_admin",
        )

    # ------------------------------------------------------------------
    # 开启 / 续用 / 开课闸门
    # ------------------------------------------------------------------

    def test_rehearsal_gates_real_class_and_resumes(self) -> None:
        lesson = self.make_lesson()
        cw = self.runtime.classroom

        # 教案设计产出且未通过模拟测试：不能开真实课堂。
        with self.assertRaises(ValueError):
            cw.create_class_session(lesson.lesson_id, self.project)

        created = cw.create_lesson_rehearsal(self.project, lesson.lesson_id, "local_admin")
        rehearsal = created["rehearsal"]
        self.assertFalse(created["resumed"])
        self.assertEqual(rehearsal["status"], "active")
        self.assertEqual(rehearsal["base_version"], 1)
        self.assertEqual(len(rehearsal["working_copy"]["stages"]), 2)
        # 工作副本是课时 plan 的拷贝，含完整题目。
        self.assertTrue(rehearsal["working_copy"]["stages"][1]["questions"])

        # 同课时重复开启：续用同一条记录。
        resumed = cw.create_lesson_rehearsal(self.project, lesson.lesson_id, "local_admin")
        self.assertTrue(resumed["resumed"])
        self.assertEqual(resumed["rehearsal"]["rehearsal_id"], rehearsal["rehearsal_id"])

        # 内置课时不能进入模拟测试。
        builtin = next(item for item in self.store.list_lessons() if item.source == "builtin")
        with self.assertRaises(ValueError):
            cw.create_lesson_rehearsal(self.project, builtin.lesson_id, "local_admin")

    # ------------------------------------------------------------------
    # 工作副本调整 + 修订冲突
    # ------------------------------------------------------------------

    def test_update_operations_and_revision_conflict(self) -> None:
        lesson = self.make_lesson()
        cw = self.runtime.classroom
        rid = cw.create_lesson_rehearsal(self.project, lesson.lesson_id, "local_admin")["rehearsal"]["rehearsal_id"]

        stages = cw.get_lesson_rehearsal(rid)["rehearsal"]["working_copy"]["stages"]
        stages[0]["minutes"] = stages[0]["minutes"] + 2
        updated = cw.update_lesson_rehearsal(rid, patch={"stages": stages}, expected_revision=0)
        rehearsal = updated["rehearsal"]
        self.assertEqual(rehearsal["revision"], 1)
        self.assertEqual(rehearsal["working_copy"]["stages"][0]["minutes"], 14)

        updated = cw.update_lesson_rehearsal(
            rid,
            question_bind={
                "stage_id": "s1",
                "manual": {
                    "text": "判断：赤道附近人口一定稠密。",
                    "type": "open",
                    "answer": "错误，湿热雨林人口稀疏。",
                    "explanation": "气候过湿且土壤贫瘠，不宜大规模聚居。",
                },
            },
            expected_revision=1,
        )
        manual_questions = [
            question
            for question in updated["rehearsal"]["working_copy"]["stages"][0]["questions"]
            if question.get("source") == "teacher_manual"
        ]
        self.assertTrue(manual_questions)
        self.assertTrue(manual_questions[0]["answer_complete"])

        updated = cw.update_lesson_rehearsal(
            rid,
            image_bind={
                "stage_id": "s1",
                "question_id": "q_s1_1",
                "image": {"url": "/files/uploads/question_banks/t/p.png", "order": 1},
            },
            expected_revision=2,
        )
        bound = [
            question
            for question in updated["rehearsal"]["working_copy"]["stages"][0]["questions"]
            if question["question_id"] == "q_s1_1"
        ][0]
        self.assertTrue(any("p.png" in image["url"] for image in bound["images"]))

        updated = cw.update_lesson_rehearsal(
            rid,
            scene_capture={"stage_id": "s1", "snapshot": {"basemap_id": "amap_street", "view": {"center": [116.4, 39.9], "zoom": 5}}},
            expected_revision=3,
        )
        self.assertEqual(updated["rehearsal"]["working_copy"]["stages"][0]["scene"]["basemap_id"], "amap_street")

        updated = cw.update_lesson_rehearsal(
            rid,
            test_result={"key": "map_test", "passed": True, "note": "图层切换正常"},
            expected_revision=4,
        )
        self.assertTrue(updated["rehearsal"]["test_results"]["map_test"]["passed"])

        # 过期修订号必须被拒绝。
        with self.assertRaises(ValueError):
            cw.update_lesson_rehearsal(rid, patch={"title": "x"}, expected_revision=3)

    # ------------------------------------------------------------------
    # 完成：校验闸门 → 提交新版本 → 可开真实课堂
    # ------------------------------------------------------------------

    def test_complete_blocked_then_commits_new_version(self) -> None:
        lesson = self.make_lesson()
        cw = self.runtime.classroom
        rid = cw.create_lesson_rehearsal(self.project, lesson.lesson_id, "local_admin")["rehearsal"]["rehearsal_id"]

        # 环节时长改为 42 分钟：与 40 分钟课时不一致，完成必须被拦下。
        stages = cw.get_lesson_rehearsal(rid)["rehearsal"]["working_copy"]["stages"]
        stages[1]["minutes"] = stages[1]["minutes"] + 2
        cw.update_lesson_rehearsal(rid, patch={"stages": stages}, expected_revision=0)
        with self.assertRaises(ValueError) as ctx:
            cw.complete_lesson_rehearsal(rid, expected_revision=1)
        self.assertIn("分钟", str(ctx.exception))
        # 被拦下的记录保留事件与 active 状态，可继续修。
        blocked = self.store.get_lesson_rehearsal(rid)
        self.assertEqual(blocked.status, "active")
        self.assertTrue(any(event["action"] == "complete_blocked" for event in blocked.modification_events))

        report = cw.lesson_rehearsal_report(rid)["report"]
        self.assertFalse(report["ready"])

        # 修回 40 分钟后完成：提交为新版本并放开真实课堂。
        stages = cw.get_lesson_rehearsal(rid)["rehearsal"]["working_copy"]["stages"]
        stages[1]["minutes"] = stages[1]["minutes"] - 2
        cw.update_lesson_rehearsal(rid, patch={"stages": stages}, expected_revision=2)

        completed = cw.complete_lesson_rehearsal(rid, expected_revision=3)
        meta = completed["lesson"]["metadata"]
        self.assertEqual(meta["lesson_version"], 2)
        self.assertTrue(meta["ready_for_class"])
        self.assertEqual(meta["last_rehearsal"]["rehearsal_id"], rid)
        self.assertEqual(completed["rehearsal"]["status"], "completed")
        self.assertEqual(completed["rehearsal"]["committed_version"], 2)
        self.assertEqual(self.store.get_lesson(lesson.lesson_id).metadata["lesson_version"], 2)

        # 开课成功，且班课快照读取开课时刻的版本。
        session = cw.create_class_session(lesson.lesson_id, self.project)["session"]
        self.assertEqual(session["metadata"]["lesson_snapshot"]["metadata"]["lesson_version"], 2)
        # 课时之后再演进也不影响已开班课快照。
        store_lesson = self.store.get_lesson(lesson.lesson_id)
        store_lesson.metadata["lesson_version"] = 99
        self.store.upsert_lesson(store_lesson)
        again = self.store.get_class_session(session["session_id"])
        self.assertEqual(again.metadata["lesson_snapshot"]["metadata"]["lesson_version"], 2)
        # 模拟测试不会写入班课事件流。
        self.assertFalse(any("rehearsal" in event["type"] for event in again.events))
        cw.end_class_session(session["session_id"])

    # ------------------------------------------------------------------
    # 取消：丢弃修改、保留历史记录
    # ------------------------------------------------------------------

    def test_cancel_discards_changes_and_keeps_history(self) -> None:
        lesson = self.make_lesson()
        cw = self.runtime.classroom
        rid = cw.create_lesson_rehearsal(self.project, lesson.lesson_id, "local_admin")["rehearsal"]["rehearsal_id"]
        cw.update_lesson_rehearsal(rid, patch={"title": "改过的标题"}, expected_revision=0)

        cancelled = cw.cancel_lesson_rehearsal(rid)
        self.assertEqual(cancelled["rehearsal"]["status"], "cancelled")
        # 课时保持未发布状态。
        store_lesson = self.store.get_lesson(lesson.lesson_id)
        self.assertEqual(store_lesson.metadata["lesson_version"], 1)
        self.assertNotEqual(store_lesson.metadata.get("ready_for_class"), True)
        with self.assertRaises(ValueError):
            cw.create_class_session(lesson.lesson_id, self.project)

        # 已结束的记录不能再改；再次开启得到全新工作副本。
        with self.assertRaises(ValueError):
            cw.update_lesson_rehearsal(rid, patch={"title": "x"}, expected_revision=1)
        fresh = cw.create_lesson_rehearsal(self.project, lesson.lesson_id, "local_admin")
        self.assertFalse(fresh["resumed"])
        self.assertNotEqual(fresh["rehearsal"]["rehearsal_id"], rid)
        self.assertEqual(fresh["rehearsal"]["working_copy"]["title"], "人口分布")

        listed = cw.list_lesson_rehearsals(project_id=self.project, lesson_id=lesson.lesson_id)["items"]
        self.assertEqual({item["status"] for item in listed}, {"active", "cancelled"})

    def test_store_round_trip_persists_rehearsal(self) -> None:
        lesson = self.make_lesson()
        cw = self.runtime.classroom
        rid = cw.create_lesson_rehearsal(self.project, lesson.lesson_id, "local_admin")["rehearsal"]["rehearsal_id"]
        cw.update_lesson_rehearsal(rid, patch={"title": "持久化标题"}, expected_revision=0)

        reloaded = RuntimeStore(self.store.state_file)
        restored = reloaded.get_lesson_rehearsal(rid)
        self.assertIsNotNone(restored)
        self.assertEqual(restored.working_copy["title"], "持久化标题")
        self.assertEqual(restored.status, "active")
        self.assertEqual(len(restored.modification_events), 2)


if __name__ == "__main__":
    unittest.main()
