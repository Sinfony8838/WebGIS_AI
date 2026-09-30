from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import fitz
from docx import Document

from backend.app.config import AppConfig
from backend.app.runtime import WebGISRuntime
from backend.app.store import RuntimeStore
from backend.app.services.lesson_pdf_export import write_lesson_pdf


def _draft() -> dict:
    return {
        "title": "人口分布",
        "subject": "地理",
        "grade": "高一",
        "duration_minutes": 40,
        "requirements": {"raw": "高一人口分布，40分钟"},
        "curriculum_interpretation": "课标要求描述人口分布特点并解释成因。",
        "student_analysis": "学生已具备读图基础。",
        "textbook_analysis": "教材以人口密度图为主要素材。",
        "objectives": ["描述世界人口分布格局", "解释人口分布的自然成因"],
        "key_difficulties": {"key": ["人口分布格局"], "difficult": ["成因分析"]},
        "methods": ["情境教学", "小组合作探究"],
        "knowledge_structure": ["分布格局", "影响因素", "区域迁移"],
        "design_thinking": "以世界人口密度图切入，先描述分布格局，再叠加图层探究成因，最后迁移到中国情境。",
        "homework": {"basic": ["完成地图册人口分布练习"], "inquiry": ["查一个国家的人口分布并解释"]},
        "board_design": "人口分布：格局 → 成因 → 迁移",
        "reflection": "课后根据课堂记录补充。",
        "references": [{"title": "人教版必修二第二章", "year": "2019", "url": ""}],
        "stages": [
            {
                "stage_id": "s1", "title": "情境导入", "minutes": 12,
                "knowledge_point": "人口分布格局",
                "material": "世界人口密度图",
                "teacher_activities": ["展示人口密度图"],
                "student_activities": ["圈画稠密区"],
                "question_chain": ["人口集中在哪里？"],
                "knowledge_conclusion": "中低纬度沿海平原人口稠密。",
                "design_intent": "建立空间感知",
                "questions": [{"text": "世界人口集中在哪里？", "answer": "沿海平原", "explanation": "略"}],
                "scene": {},
            },
            {
                "stage_id": "s2", "title": "成因探究", "minutes": 28,
                "knowledge_point": "影响因素",
                "teacher_activities": ["引导叠加图层"],
                "student_activities": ["小组归纳成因"],
                "knowledge_conclusion": "气候地形水源共同作用。",
                "questions": [{"text": "影响人口分布的自然因素？", "answer": "气候等", "explanation": "略"}],
                "scene": {},
            },
        ],
    }


def _proxy(draft: dict) -> SimpleNamespace:
    return SimpleNamespace(
        title=draft["title"], subject=draft.get("subject", "地理"), grade=draft.get("grade", ""),
        objectives=list(draft.get("objectives") or []),
        stages=[stage for stage in draft.get("stages") or [] if isinstance(stage, dict)],
        plan=dict(draft), metadata={"duration_minutes": draft.get("duration_minutes", 40)},
    )


class LessonExportFormatsTest(unittest.TestCase):
    def test_long_stage_pdf_continues_across_pages_without_losing_tail(self) -> None:
        draft = _draft()
        draft["stages"][0]["teacher_activities"] = ["观察地图并解释空间分布。" * 600 + "长环节结束标记"]
        path = self.tmp / "long.pdf"
        write_lesson_pdf(path, draft["title"], draft["subject"], draft["grade"], draft, draft["stages"], "草稿")
        with fitz.open(path) as document:
            text = "".join(page.get_text() for page in document).replace("\n", "")
            self.assertIn("长环节结束标记", text)
            self.assertIn("成因探究", text)
            self.assertGreater(document.page_count, 2)
            for page in document:
                for block in page.get_text("blocks"):
                    self.assertLess(block[3], page.rect.height)

    """同一份教案数据 → Word 与 PDF；保留环节顺序、素材出处与草稿/已确认状态。"""

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
        self.service = self.runtime.classroom.lesson_design
        self.tmp = Path(self.temp_dir.name)
        self.addCleanup(self.temp_dir.cleanup)

    def test_write_docx_accepts_draft_proxy_with_status_label(self) -> None:
        draft = _draft()
        path = self.tmp / "draft.docx"
        self.service._write_docx(path, _proxy(draft), status_label="草稿（未发布）")
        doc = Document(str(path))
        table_texts = [
            cell.text for table in doc.tables for row in table.rows for cell in row.cells
        ]
        self.assertIn("草稿（未发布）", table_texts)
        joined = "\n".join(table_texts)
        self.assertIn("情境导入", joined)
        self.assertIn("世界人口密度图", joined)
        # 环节顺序保留
        self.assertLess(joined.find("情境导入"), joined.find("成因探究"))

    def test_write_lesson_pdf_renders_chinese_with_status_and_materials(self) -> None:
        draft = _draft()
        path = self.tmp / "draft.pdf"
        write_lesson_pdf(path, title=draft["title"], subject=draft["subject"], grade=draft["grade"],
                         plan=draft, stages=draft["stages"], status_label="已确认 · 版本 2")
        with fitz.open(str(path)) as pdf:
            self.assertGreaterEqual(pdf.page_count, 1)
            text = "".join(page.get_text() for page in pdf)
        for expected in ("人口分布", "已确认 · 版本 2", "情境导入", "成因探究", "世界人口密度图",
                         "描述世界人口分布格局", "教学过程", "人教版必修二第二章"):
            self.assertIn(expected, text)
        self.assertLess(text.find("情境导入"), text.find("成因探究"))

    def test_export_design_and_lesson_docx_pdf_end_to_end(self) -> None:
        design = self.service.create_or_resume(self.project, "local_admin")
        design.draft.update(_draft())
        self.store.upsert_lesson_design(design)
        docx_result = self.runtime.classroom.export_design_docx(design.design_id, self.project)
        pdf_result = self.runtime.classroom.export_design_pdf(design.design_id, self.project)
        self.assertTrue(Path(docx_result["artifact"]["path"]).is_file())
        self.assertTrue(Path(pdf_result["artifact"]["path"]).is_file())
        self.assertIn("草稿", docx_result["artifact"]["title"])
        with fitz.open(pdf_result["artifact"]["path"]) as pdf:
            pdf_text = "".join(page.get_text() for page in pdf)
        self.assertIn("草稿（未发布）", pdf_text)
        # 定稿后课时导出为已确认状态
        latest = self.service.get(design.design_id)
        self.service.resolve(design.design_id, "all", "accept", expected_revision=latest.revision)
        latest = self.service.get(design.design_id)
        result = self.service.finalize(design.design_id, latest.revision)
        lesson_id = result["lesson"]["lesson_id"]
        lesson_pdf = self.runtime.classroom.export_lesson_pdf(lesson_id, self.project)
        self.assertTrue(Path(lesson_pdf["artifact"]["path"]).is_file())

    def test_export_rejects_cross_project_design(self) -> None:
        design = self.service.create_or_resume(self.project, "local_admin")
        other_project = self.runtime.create_project()["project_id"]
        with self.assertRaisesRegex(ValueError, "不属于当前项目"):
            self.service.export_design_docx(design.design_id, other_project)


if __name__ == "__main__":
    unittest.main()
