from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from backend.app.config import AppConfig
from backend.app.runtime import WebGISRuntime
from backend.app.store import RuntimeStore


class LessonDesignServiceTest(unittest.TestCase):
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

    def advance(self, design_id: str, message: str, revision: int) -> tuple[dict, int]:
        current = self.store.get_lesson_design(design_id).current_step
        result = self.runtime.classroom.turn_lesson_design(design_id, message, revision)
        revision = result["revision"]
        if current in {
            "requirements", "analysis", "objectives", "core_questions", "process",
            "question_matching", "capabilities",
        }:
            resolved = self.runtime.classroom.resolve_lesson_design(design_id, current, "accept", "", revision)
            revision = resolved["design"]["revision"]
        return result, revision

    def test_guided_turns_persist_and_finalize_as_teacher_draft(self) -> None:
        design = self.runtime.classroom.create_lesson_design(self.project, "local_admin")
        design_id = design["design_id"]
        revision = design["revision"]
        messages = (
            "高一、40分钟、人口分布",  # 需求确认
            "课标强调空间分布和区域差异",  # 课标与学情
            "描述规律并解释原因",  # 目标与重难点
            "核心问题就按建议来",  # 核心问题与问题链
            "继续设计课堂过程",  # 教学过程
            "从题库匹配题目并补作业",  # 题目匹配
            "使用二维地图",  # GIS/AI能力
        )
        for message in messages:
            result, revision = self.advance(design_id, message, revision)
        result = self.runtime.classroom.turn_lesson_design(design_id, "运行预演", revision)
        revision = result["revision"]
        result = self.runtime.classroom.turn_lesson_design(design_id, "补充设计思路与反思", revision)
        revision = result["revision"]
        persisted = self.store.get_lesson_design(design_id)
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted.revision, revision)
        self.assertEqual(len(persisted.turns), 9)
        result = self.runtime.classroom.finalize_lesson_design(design_id, revision)
        self.assertEqual(result["lesson"]["source"], "assistant_draft")
        self.assertEqual(result["lesson"]["metadata"]["project_id"], self.project)
        self.assertEqual(self.store.get_lesson_design(design_id).status, "finalized")

    def test_store_round_trip_keeps_design_and_lesson_plan(self) -> None:
        design = self.runtime.classroom.create_lesson_design(self.project, "local_admin")
        result = self.runtime.classroom.turn_lesson_design(design["design_id"], "高一、40分钟、胡焕庸线", 0)
        self.assertEqual(result["revision"], 1)
        reloaded = RuntimeStore(self.store.state_file)
        restored = reloaded.get_lesson_design(design["design_id"])
        self.assertIsNotNone(restored)
        self.assertEqual(restored.draft["topic"], "胡焕庸线")

    def test_natural_requirement_sentence_keeps_short_book_title(self) -> None:
        design = self.runtime.classroom.create_lesson_design(self.project, "local_admin")
        message = (
            "高一必修二《人口分布》，单课时40分钟。学生已经学过人口密度，但容易把人口总量、"
            "人口密度和实时人口混为一谈。请围绕胡焕庸线安排Top20数据探究和课后复盘。"
        )
        result = self.runtime.classroom.turn_lesson_design(design["design_id"], message, 0)
        self.assertEqual(result["draft"]["title"], "人口分布")
        self.assertEqual(result["draft"]["topic"], "人口分布")
        self.assertEqual(result["draft"]["grade"], "高一")
        self.assertEqual(result["draft"]["duration_minutes"], 40)
        self.assertEqual(result["draft"]["requirements"]["raw"], message)
        self.assertNotIn("学生已经学过", result["draft"]["title"])

    def test_rehearsal_blocks_a_plan_that_does_not_fill_the_declared_class_time(self) -> None:
        design = self.runtime.classroom.create_lesson_design(self.project, "local_admin")
        record = self.store.get_lesson_design(design["design_id"])
        record.draft.update({
            "title": "人口分布",
            "grade": "高一",
            "duration_minutes": 40,
            "objectives": ["描述人口分布规律"],
            "stages": [
                {
                    "stage_id": "s1", "title": "导入", "minutes": 8,
                    "content": "观察人口分布图", "design_intent": "发现空间差异",
                    "questions": [{"text": "人口主要分布在哪里？"}],
                },
                {
                    "stage_id": "s2", "title": "探究", "minutes": 18,
                    "content": "分析胡焕庸线", "design_intent": "解释空间格局",
                    "questions": [{"text": "界线两侧为何差异明显？"}],
                },
                {
                    "stage_id": "s3", "title": "复盘", "minutes": 13,
                    "content": "完成证据链", "design_intent": "当堂检测目标",
                    "questions": [{"text": "如何用证据说明人口分布规律？"}],
                },
            ],
        })
        self.store.upsert_lesson_design(record)

        report = self.runtime.classroom.lesson_design.rehearse(design["design_id"])

        self.assertFalse(report["ready"])
        self.assertEqual(report["total_minutes"], 39)
        self.assertTrue(any("与课堂时长 40 分钟不一致" in item for item in report["errors"]))

    def test_direct_edit_revision_conflict_and_confirmed_section_stability(self) -> None:
        design = self.runtime.classroom.create_lesson_design(self.project, "local_admin")
        design_id = design["design_id"]
        edited = self.runtime.classroom.resolve_lesson_design(
            design_id,
            "requirements",
            "edit",
            "",
            design["revision"],
            {"requirements": {"raw": "高一、45分钟、人口迁移"}},
        )["design"]
        accepted = self.runtime.classroom.resolve_lesson_design(
            design_id, "requirements", "accept", "", edited["revision"]
        )["design"]
        self.assertEqual(accepted["section_status"]["requirements"], "confirmed")
        with self.assertRaisesRegex(ValueError, "已更新"):
            self.runtime.classroom.resolve_lesson_design(
                design_id, "title", "edit", "", edited["revision"], "过期修改"
            )
        result = self.runtime.classroom.turn_lesson_design(
            design_id, "继续分析学生已有基础", accepted["revision"], "analysis"
        )
        self.assertEqual(result["draft"]["requirements"]["raw"], "高一、45分钟、人口迁移")
        self.assertEqual(result["section_status"]["requirements"], "confirmed")

    def test_direct_edit_stages_stores_array_and_plan_items_stay_renderable(self) -> None:
        """回归（E2E 验收发现）：直接编辑教学过程必须把数组写入 draft.stages。

        前端曾把 ``{"stages": [...]}`` 包装对象作为 value 提交，SECTION 级
        resolve edit 会把它原样写入 ``draft.stages``，双端渲染环节列表时
        ``.map``/``stage.get`` 崩溃（前端白屏、后端 plan_items AttributeError）。
        """
        design = self.runtime.classroom.create_lesson_design(self.project, "local_admin")
        design_id = design["design_id"]
        revision = design["revision"]
        for message in ("高一、40分钟、人口分布", "课标强调空间分布", "描述规律", "核心问题按建议", "继续设计课堂过程"):
            _, revision = self.advance(design_id, message, revision)
        stages_value = [
            {
                "stage_id": "s1", "title": "情境导入", "minutes": 10, "material": "人口密度图",
                "question_chain": ["分布有何差异？"], "teacher_activities": ["引导读图"],
                "student_activities": ["观察并描述"], "knowledge_conclusion": "分布不均",
                "design_intent": "从证据进入",
            },
            {
                "stage_id": "s2", "title": "成因探究", "minutes": 20, "material": "地形气候图",
                "question_chain": ["哪些因素？"], "teacher_activities": ["组织对比"],
                "student_activities": ["小组归因"], "knowledge_conclusion": "自然加人文",
                "design_intent": "由描述到解释",
            },
            {
                "stage_id": "s3", "title": "归纳迁移", "minutes": 10, "material": "板书要点",
                "question_chain": ["如何迁移？"], "teacher_activities": ["收束规律"],
                "student_activities": ["结论卡片"], "knowledge_conclusion": "方法迁移",
                "design_intent": "检查目标",
            },
        ]
        result = self.runtime.classroom.resolve_lesson_design(
            design_id, "stages", "edit", "", revision, stages_value
        )
        stored = self.store.get_lesson_design(design_id)
        self.assertIsInstance(stored.draft["stages"], list)
        self.assertEqual(
            [stage["title"] for stage in stored.draft["stages"]],
            ["情境导入", "成因探究", "归纳迁移"],
        )
        # 会话视图（plan_items）必须可渲染，不得再抛 'str' object has no attribute 'get'
        stored.current_step = "process"  # 教学过程步骤的 plan_items 会逐个映射环节
        plan_items = self.runtime.classroom.lesson_design.session_view(stored)["plan_items"]
        stage_items = [item for item in plan_items if item["section_key"] == "stages"]
        self.assertEqual(len(stage_items[0]["value"]), 3)
        self.assertEqual(stored.section_status.get("stages"), "proposed")

    def test_rehearsal_rejects_unknown_registered_capabilities(self) -> None:
        design = self.runtime.classroom.create_lesson_design(self.project, "local_admin")
        with self.assertRaisesRegex(ValueError, "不可用系统能力"):
            self.runtime.classroom.resolve_lesson_design(
                design["design_id"],
                "capabilities",
                "edit",
                "",
                design["revision"],
                {"capabilities": [{"id": "invented-capability"}]},
            )
        record = self.store.get_lesson_design(design["design_id"])
        record.draft.update({
            "title": "人口分布",
            "objectives": ["描述人口分布规律"],
            "stages": [{
                "stage_id": "s1", "title": "读图", "minutes": 40,
                "content": "观察专题图", "design_intent": "形成空间认识",
                "questions": [{"text": "人口主要分布在哪里？"}],
                "scene": {
                    "templates": ["invented-template"],
                    "catalog_layers": ["invented-dataset"],
                    "globe": {"enabled": True, "themes": ["invented-theme"]},
                },
            }],
        })
        self.store.upsert_lesson_design(record)
        report = self.runtime.classroom.lesson_design.rehearse(design["design_id"])
        self.assertFalse(report["ready"])
        self.assertTrue(any("invented-template" in item for item in report["errors"]))
        self.assertTrue(any("invented-dataset" in item for item in report["errors"]))
        self.assertTrue(any("invented-theme" in item for item in report["errors"]))

    def test_cross_project_base_and_export_are_rejected(self) -> None:
        other_project = self.runtime.create_project()["project_id"]
        lesson = self.runtime.classroom.lesson_service.create_lesson({
            "title": "项目一课时",
            "subject": "地理",
            "grade": "高一",
            "objectives": [],
            "stages": [],
            "metadata": {"project_id": self.project},
            "plan": {},
        }, source="assistant_draft", owner_user_id="local_admin")
        with self.assertRaisesRegex(ValueError, "不属于当前项目"):
            self.runtime.classroom.create_lesson_design(other_project, "local_admin", lesson.lesson_id)
        with self.assertRaisesRegex(ValueError, "不属于当前项目"):
            self.runtime.classroom.export_lesson_docx(lesson.lesson_id, other_project)

    def test_docx_export_has_five_column_process_and_page_field(self) -> None:
        design = self.runtime.classroom.create_lesson_design(self.project, "local_admin")
        revision = 0
        messages = (
            "高一、40分钟、人口分布",
            "课标",
            "描述规律",
            "核心问题就按建议来",
            "设计过程",
            "从题库匹配题目并补作业",
            "二维地图",
        )
        for message in messages:
            result, revision = self.advance(design["design_id"], message, revision)
        result = self.runtime.classroom.turn_lesson_design(design["design_id"], "运行预演", revision)
        revision = result["revision"]
        result = self.runtime.classroom.turn_lesson_design(design["design_id"], "补充设计思路与反思", revision)
        revision = result["revision"]
        lesson = self.runtime.classroom.finalize_lesson_design(design["design_id"], revision)["lesson"]
        exported = self.runtime.classroom.export_lesson_docx(lesson["lesson_id"], self.project, design["design_id"])
        path = Path(exported["artifact"]["path"])
        self.assertTrue(path.is_file())
        from docx import Document
        document = Document(path)
        self.assertGreaterEqual(len(document.tables), 2)
        self.assertEqual([cell.text for cell in document.tables[1].rows[0].cells], ["环节", "知识单元", "知识点", "具体内容/活动", "设计意图"])
        with ZipFile(path) as archive:
            footer = archive.read("word/footer1.xml").decode("utf-8")
            document_xml = archive.read("word/document.xml").decode("utf-8")
            core_xml = archive.read("docProps/core.xml").decode("utf-8")
        self.assertIn("PAGE", footer)
        self.assertIn("w:tblHeader", document_xml)
        self.assertIn('w:tblLayout w:type="fixed"', document_xml)
        self.assertIn("WebGIS-AI", core_xml)
        self.assertNotIn("张珂", path.read_bytes().decode("latin1", errors="ignore"))


if __name__ == "__main__":
    unittest.main()
