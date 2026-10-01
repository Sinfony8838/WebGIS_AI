"""Word 导入校对：待归类条目的人工归类、图片绑定、草稿版本检查。"""
from __future__ import annotations

import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Inches
from PIL import Image

from backend.app.config import AppConfig
from backend.app.runtime import WebGISRuntime
from backend.app.store import RuntimeStore
from backend.app.services.lesson_docx_import import parse_lesson_docx


def _merged_stage_table_bytes() -> bytes:
    """带横向合并（gridSpan）与纵向合并（vMerge）环节表的教案。"""
    doc = Document()
    doc.add_heading("合并单元格教案", level=1)
    table = doc.add_table(rows=4, cols=4)
    headers = ["环节", "时长", "教师活动", "学生活动"]
    for cell, text in zip(table.rows[0].cells, headers):
        cell.text = text
    # 第一行：普通行
    for cell, text in zip(table.rows[1].cells, ["情境导入", "5", "播放视频", "观察现象"]):
        cell.text = text
    # 第二行：纵向合并 —— 环节格标记 vMerge restart，第三行延续
    row2 = table.rows[2].cells
    row2[0].text = "成因探究"
    tc_pr = row2[0]._tc.get_or_add_tcPr()
    vmerge = tc_pr.makeelement(qn("w:vMerge"), {qn("w:val"): "restart"})
    tc_pr.append(vmerge)
    row2[1].text = "20"
    row2[2].text = "引导讨论\n追问成因"
    row2[3].text = "小组讨论"
    row3 = table.rows[3].cells
    row3[0].text = ""
    tc_pr3 = row3[0]._tc.get_or_add_tcPr()
    vmerge3 = tc_pr3.makeelement(qn("w:vMerge"), {})
    tc_pr3.append(vmerge3)
    row3[1].text = ""
    row3[2].text = "总结推拉因素"
    row3[3].text = "汇报展示"
    output = BytesIO()
    doc.save(output)
    return output.getvalue()


class LessonDocxImportMergedCellTest(unittest.TestCase):
    def test_vmerge_continuation_rows_merge_into_previous_stage(self) -> None:
        result = parse_lesson_docx(_merged_stage_table_bytes())
        stages = result["draft"]["stages"]
        self.assertEqual(len(stages), 2)
        second = stages[1]
        self.assertEqual(second["title"], "成因探究")
        self.assertEqual(second["minutes"], 20)
        self.assertEqual(second["teacher_activities"], ["引导讨论", "追问成因", "总结推拉因素"])
        self.assertEqual(second["student_activities"], ["小组讨论", "汇报展示"])


class LessonImportReviewTest(unittest.TestCase):
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
        self.config = config
        self.addCleanup(self.temp_dir.cleanup)

    def _import_design(self) -> dict:
        doc = Document()
        doc.add_heading("导入校对教案", level=1)
        doc.add_paragraph("课题：季风气候")
        doc.add_paragraph("一、教学目标")
        doc.add_paragraph("描述季风的形成")
        table = doc.add_table(rows=3, cols=3)
        for row, values in zip(
            table.rows,
            [["环节", "教师活动", "学生活动"], ["导入", "展示地图", "读图"], ["小结", "梳理结构", "填写笔记"]],
        ):
            for cell, text in zip(row.cells, values):
                cell.text = text
        doc.add_paragraph("一段无法识别的内容")
        image = Image.new("RGB", (3, 3), (30, 90, 200))
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)
        doc.add_picture(buffer, width=Inches(1))
        buffer.close()
        output = BytesIO()
        doc.save(output)
        result = self.runtime.classroom.import_lesson_design_docx(
            self.project, "local_admin", output.getvalue(), "校对.docx"
        )
        return result

    def _unclassified_index(self, design: dict, keyword: str) -> int:
        items = design["draft"]["import_review"]["unclassified"]
        for index, item in enumerate(items):
            if keyword in str(item.get("text") or ""):
                return index
        raise AssertionError(f"未找到包含 {keyword} 的待归类条目")

    def test_assign_text_to_section_append_and_replace(self) -> None:
        result = self._import_design()
        design_id = result["design"]["design_id"]
        design = result["design"]
        item_index = self._unclassified_index(design, "无法识别")

        applied = self.runtime.classroom.apply_lesson_design_import_review(
            design_id, item_index, action="assign",
            target={"section": "objectives"}, mode="append", expected_revision=design["revision"],
        )
        draft = applied["design"]["draft"]
        self.assertIn("一段无法识别的内容", draft["objectives"])
        item = draft["import_review"]["unclassified"][item_index]
        self.assertEqual(item["status"], "assigned")
        self.assertEqual(item["assignment"]["section"], "objectives")
        # 未处理条目仍在清单中（保留原文）
        self.assertEqual(item["text"], "一段无法识别的内容")

        replaced = self.runtime.classroom.apply_lesson_design_import_review(
            design_id, item_index, action="assign",
            target={"section": "objectives"}, mode="replace", expected_revision=applied["design"]["revision"],
        )
        self.assertEqual(replaced["design"]["draft"]["objectives"], ["一段无法识别的内容"])

    def test_assign_text_to_stage_column(self) -> None:
        result = self._import_design()
        design_id = result["design"]["design_id"]
        design = result["design"]
        item_index = self._unclassified_index(design, "无法识别")
        stage_id = result["design"]["draft"]["stages"][0]["stage_id"]

        applied = self.runtime.classroom.apply_lesson_design_import_review(
            design_id, item_index, action="assign",
            target={"stage_id": stage_id, "column": "student_activities"}, mode="append",
            expected_revision=design["revision"],
        )
        stage = applied["design"]["draft"]["stages"][0]
        self.assertIn("一段无法识别的内容", stage["student_activities"])
        self.assertEqual(applied["design"]["draft"]["stages"][0]["student_activities"][-1], "一段无法识别的内容")
        self.assertEqual(applied["design"]["section_status"]["stages"], "proposed")

    def test_assign_image_binds_stage_presentation_and_moves_on_reassign(self) -> None:
        result = self._import_design()
        design_id = result["design"]["design_id"]
        design = result["design"]
        items = design["draft"]["import_review"]["unclassified"]
        image_index = next(index for index, item in enumerate(items) if item.get("kind") == "image")
        self.assertTrue(items[image_index].get("url"), "导入图片应有可访问 url")
        stages = design["draft"]["stages"]
        self.assertGreaterEqual(len(stages), 1)
        first_id, second_id = stages[0]["stage_id"], stages[-1]["stage_id"]

        applied = self.runtime.classroom.apply_lesson_design_import_review(
            design_id, image_index, action="assign", target={"stage_id": first_id},
            expected_revision=design["revision"],
        )
        blocks = applied["design"]["draft"]["stages"][0].get("presentation", {}).get("blocks", [])
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["type"], "image")
        self.assertEqual(blocks[0]["asset"]["url"], items[image_index]["url"])
        assignment = applied["design"]["draft"]["import_review"]["unclassified"][image_index]["assignment"]
        self.assertEqual(assignment["kind"], "stage_material")

        # 改绑到另一环节：旧环节的区块被移走
        reapplied = self.runtime.classroom.apply_lesson_design_import_review(
            design_id, image_index, action="assign", target={"stage_id": second_id},
            expected_revision=applied["design"]["revision"],
        )
        first_blocks = reapplied["design"]["draft"]["stages"][0].get("presentation", {}).get("blocks", [])
        second_blocks = reapplied["design"]["draft"]["stages"][-1].get("presentation", {}).get("blocks", [])
        self.assertEqual(first_blocks, [])
        self.assertEqual(len(second_blocks), 1)

    def test_revision_conflict_and_invalid_targets(self) -> None:
        result = self._import_design()
        design_id = result["design"]["design_id"]
        design = result["design"]
        item_index = self._unclassified_index(design, "无法识别")

        with self.assertRaisesRegex(ValueError, "更新"):
            self.runtime.classroom.apply_lesson_design_import_review(
                design_id, item_index, action="assign",
                target={"section": "objectives"}, expected_revision=design["revision"] + 5,
            )
        with self.assertRaisesRegex(ValueError, "教案字段|栏目"):
            self.runtime.classroom.apply_lesson_design_import_review(
                design_id, item_index, action="assign", target={"section": "not_a_field"},
                expected_revision=design["revision"],
            )
        with self.assertRaisesRegex(ValueError, "目标环节|没有找到"):
            self.runtime.classroom.apply_lesson_design_import_review(
                design_id, item_index, action="assign",
                target={"stage_id": "missing", "column": "material"}, expected_revision=design["revision"],
            )
        with self.assertRaisesRegex(ValueError, "不存在"):
            self.runtime.classroom.apply_lesson_design_import_review(
                design_id, 999, action="assign", target={"section": "title"},
                expected_revision=design["revision"],
            )

    def test_ignore_keeps_item_and_updates_summary(self) -> None:
        result = self._import_design()
        design_id = result["design"]["design_id"]
        design = result["design"]
        item_index = self._unclassified_index(design, "无法识别")
        applied = self.runtime.classroom.apply_lesson_design_import_review(
            design_id, item_index, action="ignore", expected_revision=design["revision"],
        )
        item = applied["design"]["draft"]["import_review"]["unclassified"][item_index]
        self.assertEqual(item["status"], "ignored")
        self.assertIn(item["text"], str(item))
        self.assertIn("忽略 1 条", applied["design"]["draft"]["import_review"]["summary"])


if __name__ == "__main__":
    unittest.main()
