"""Render a lesson plan to PDF with PyMuPDF.

与 Word 导出（lesson_design._write_docx）共享同一份教案数据：
- 使用 PyMuPDF 内置 CJK 字体（china-s 正文 / china-ss 标题），不依赖系统字体文件；
  部署可另在 backend/app/data/builtin/fonts/ 放置字体（预留，当前不读取）。
- 保留环节顺序、素材出处（材料/参考）与「草稿／已确认」状态标签。
- 全部文本经 insert_textbox 排版（MuPDF 自行量宽换行）；fitz.Font.text_length
  对含 ASCII 的 CJK 行会低估宽度，禁止用于布局判断。
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import fitz

PAGE_W, PAGE_H = 595.0, 842.0
MARGIN = 40.0
BOTTOM = PAGE_H - MARGIN - 18.0
BODY_FONT = "china-s"
HEAD_FONT = "china-ss"
BODY_SIZE = 10.5
TABLE_SIZE = 8.8
LINE_FACTOR = 1.42
# 教学过程表列宽（合计 = 可用宽度 515pt）：环节 | 知识点 | 活动与素材 | 题目
TABLE_WIDTHS = (60.0, 80.0, 270.0, 105.0)
TABLE_HEADERS = ("环节", "知识点", "活动与素材", "题目")

_MEASURE_DOC = fitz.open()
_MEASURE_PAGE = _MEASURE_DOC.new_page(width=4000.0, height=10000.0)


def _measure_height(text: str, size: float, width: float) -> Optional[float]:
    """insert_textbox 实测高度；返回 None 表示单行都放不下（理论不发生）。"""
    rect = fitz.Rect(0.0, 0.0, width, 10000.0)
    leftover = _MEASURE_PAGE.new_shape().insert_textbox(rect, str(text or ""), fontname=BODY_FONT,
                                            fontsize=size, lineheight=LINE_FACTOR)
    if leftover < 0:
        return None
    return rect.height - leftover


def _as_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _stage_cell_values(stage: Dict[str, Any]) -> List[str]:
    head = _as_text(stage.get("title")) or "未命名环节"
    minutes = stage.get("minutes")
    try:
        head += f"\n（{int(minutes)}分钟）"
    except (TypeError, ValueError):
        head += "\n（未设时长）"
    activities: List[str] = []
    if _as_text(stage.get("material")):
        activities.append("材料：" + _as_text(stage.get("material")))
    for label, key in (("教师", "teacher_activities"), ("学生", "student_activities")):
        values = stage.get(key) or stage.get("activities") or []
        if isinstance(values, list) and values:
            activities.append(f"{label}活动：" + "；".join(_as_text(item) for item in values))
        elif _as_text(values):
            activities.append(f"{label}活动：" + _as_text(values))
    chain = stage.get("question_chain") or []
    if isinstance(chain, list) and chain:
        activities.append("问题链：" + "；".join(_as_text(item) for item in chain))
    if _as_text(stage.get("knowledge_conclusion")):
        activities.append("结论：" + _as_text(stage.get("knowledge_conclusion")))
    system_steps = stage.get("system_steps") or []
    if isinstance(system_steps, list) and system_steps:
        activities.append("系统操作：" + "；".join(_as_text(item) for item in system_steps))
    if _as_text(stage.get("design_intent")):
        activities.append("意图：" + _as_text(stage.get("design_intent")))
    question_lines: List[str] = []
    for question in stage.get("questions") or []:
        if isinstance(question, dict):
            text = _as_text(question.get("text") or question.get("task_text"))
            if text:
                question_lines.append(text)
    return [head, _as_text(stage.get("knowledge_point")), "\n".join(activities) or "待补充",
            "\n".join(question_lines) or "—"]


class _PdfCanvas:
    def __init__(self) -> None:
        self.doc = fitz.open()
        self.page = self.doc.new_page(width=PAGE_W, height=PAGE_H)
        self.y = MARGIN

    def _new_page(self) -> None:
        self.page = self.doc.new_page(width=PAGE_W, height=PAGE_H)
        self.y = MARGIN

    def _place(self, text: str, size: float, font: str, x: float, width: float,
               align: int = 0) -> None:
        """insert_textbox 排版一段文本；放不下剩余页高时换页重试。"""
        text = str(text or "")
        if not text.strip():
            self.y += size * LINE_FACTOR * 0.6
            return
        for _ in range(8):
            rect = fitz.Rect(x, self.y, x + width, BOTTOM)
            leftover = self.page.insert_textbox(rect, text, fontname=font, fontsize=size,
                                                lineheight=LINE_FACTOR, align=align)
            if leftover >= 0:
                self.y += (BOTTOM - self.y) - leftover
                return
            if self.y <= MARGIN + 0.1:
                # 整页高度仍放不下（异常超长段落）：对半拆分递归，避免死循环。
                middle = max(1, len(text) // 2)
                self._place(text[:middle], size, font, x, width, align)
                self._place(text[middle:], size, font, x, width, align)
                return
            self._new_page()
        self.y += size * LINE_FACTOR

    def text(self, text: str, size: float = BODY_SIZE, font: str = BODY_FONT,
             x: float = MARGIN, width: Optional[float] = None, after_gap: float = 2.0) -> None:
        lines = str(text or "").splitlines() or [""]
        for line in lines:
            self._place(line, size, font, x, width if width is not None else PAGE_W - MARGIN - x)
        self.y += after_gap

    def centered(self, text: str, size: float, font: str, after_gap: float = 4.0) -> None:
        self._place(text, size, font, MARGIN, PAGE_W - 2 * MARGIN,
                    align=fitz.TEXT_ALIGN_CENTER)
        self.y += after_gap

    def right(self, text: str, size: float, font: str, after_gap: float = 2.0) -> None:
        self._place(text, size, font, MARGIN, PAGE_W - 2 * MARGIN,
                    align=fitz.TEXT_ALIGN_RIGHT)
        self.y += after_gap

    def heading(self, text: str) -> None:
        self.y += 4.0
        self.text(text, size=12.5, font=HEAD_FONT, after_gap=3.0)

    def bullet(self, text: str) -> None:
        self.text("· " + str(text or ""), x=MARGIN + 10.0)

    def table(self, rows: List[List[str]], widths: List[float], headers: List[str]) -> None:
        size = TABLE_SIZE
        padding = 3.0
        line_height = size * LINE_FACTOR

        def row_height(values: List[str]) -> float:
            height = 0.0
            for value, width in zip(values, widths):
                measured = _measure_height(value, size, width - 2 * padding)
                lines = max(1, math.ceil((measured or line_height) / line_height))
                height = max(height, lines * line_height + 2 * padding)
            # +1pt 余量：防止 insert_textbox 因浮点误差返回负 leftover 而静默丢弃整格。
            return height + 1.0

        def draw_row(values: List[str], height: float, fill: Optional[Tuple] = None) -> None:
            x = MARGIN
            for value, width in zip(values, widths):
                rect = fitz.Rect(x, self.y, x + width, self.y + height)
                self.page.draw_rect(rect, color=(0.55, 0.55, 0.6), width=0.5,
                                    fill=fill, fill_opacity=1.0 if fill else 0.0)
                if str(value).strip():
                    leftover = self.page.insert_textbox(
                        fitz.Rect(x + padding, self.y + padding, x + width - padding,
                                  self.y + height - padding),
                        str(value), fontname=BODY_FONT, fontsize=size,
                        lineheight=LINE_FACTOR, align=0)
                    if leftover < 0:
                        raise ValueError("PDF 表格文字未能完整排版，请重试。")
                x += width
            self.y += height

        header_values = list(headers)
        header_height = row_height(header_values)
        if self.y + header_height + 2 * line_height > BOTTOM:
            self._new_page()
        draw_row(header_values, header_height, fill=(0.85, 0.9, 0.96))
        for values in rows:
            remaining = list(values)
            while any(remaining):
                available = BOTTOM - self.y
                if available < 2 * line_height + 2 * padding + 1:
                    self._new_page()
                    draw_row(header_values, header_height, fill=(0.85, 0.9, 0.96))
                    available = BOTTOM - self.y
                chunks = []
                tails = []
                for value, width in zip(remaining, widths):
                    low, high = 0, len(value)
                    budget = available - 2 * padding - 1
                    # Split each cell into the largest prefix that fits. Continue
                    # all columns on the next page with a repeated header.
                    while low < high:
                        middle = (low + high + 1) // 2
                        measured = _measure_height(value[:middle], size, width - 2 * padding)
                        if measured is not None and measured <= budget:
                            low = middle
                        else:
                            high = middle - 1
                    chunks.append(value[:low])
                    tails.append(value[low:])
                if not any(chunks):
                    raise ValueError("PDF 表格单元格无法排版。")
                height = max(_measure_height(value, size, width - 2 * padding) or line_height
                             for value, width in zip(chunks, widths)) + 2 * padding + 1
                draw_row(chunks, height)
                remaining = tails
                if any(remaining):
                    self._new_page()
                    draw_row(header_values, header_height, fill=(0.85, 0.9, 0.96))
        self.y += 6.0

    def save(self, path: Path) -> None:
        count = self.doc.page_count
        for index, page in enumerate(self.doc):
            page.insert_textbox(fitz.Rect(PAGE_W - 130.0, PAGE_H - 26.0, PAGE_W - MARGIN, PAGE_H - 10.0),
                                f"第 {index + 1} / {count} 页", fontname=BODY_FONT, fontsize=8,
                                align=fitz.TEXT_ALIGN_RIGHT)
        self.doc.save(str(path))
        self.doc.close()


def write_lesson_pdf(
    path: Path, title: str, subject: str, grade: str, plan: Dict[str, Any],
    stages: List[Dict[str, Any]], status_label: str,
) -> None:
    """从教案数据渲染 PDF（与 Word 导出同源）。"""
    plan = plan or {}
    canvas = _PdfCanvas()
    canvas.right(f"WebGIS-AI 教案 · {_as_text(status_label) or '草稿'}", 9, BODY_FONT, after_gap=6.0)
    canvas.centered(_as_text(title) or "未命名教案", 16, HEAD_FONT, after_gap=6.0)
    try:
        duration = int(plan.get("duration_minutes") or 0)
    except (TypeError, ValueError):
        duration = 0
    info = f"学科：{_as_text(subject) or '—'}    年级：{_as_text(grade) or '待填写'}    课时：{duration or '—'} 分钟"
    canvas.centered(info, 10, BODY_FONT, after_gap=8.0)

    canvas.heading("一、课标与前置分析")
    for label, key in (("课标解读", "curriculum_interpretation"), ("学情分析", "student_analysis"),
                       ("教材分析", "textbook_analysis")):
        value = _as_text(plan.get(key)) or "待教师补充。"
        canvas.text(f"{label}：{value}")

    canvas.heading("二、教学目标与重难点")
    objectives = plan.get("objectives") or []
    for objective in objectives if isinstance(objectives, list) else [objectives]:
        canvas.bullet(_as_text(objective))
    if not objectives:
        canvas.text("待教师补充。")
    difficulties = plan.get("key_difficulties") or {}
    key_items = "；".join(_as_text(item) for item in difficulties.get("key") or []) if isinstance(difficulties, dict) else ""
    difficult_items = "；".join(_as_text(item) for item in difficulties.get("difficult") or []) if isinstance(difficulties, dict) else ""
    canvas.text(f"重点：{key_items or '待确认'}    难点：{difficult_items or '待确认'}")
    methods = plan.get("methods") or []
    if methods:
        canvas.text("教学方法：" + "；".join(_as_text(item) for item in methods))

    canvas.heading("三、知识结构")
    knowledge = plan.get("knowledge_structure") or []
    structure = " → ".join(_as_text(item) for item in knowledge if _as_text(item))
    canvas.text(structure or "待教师补充。")

    canvas.heading("四、教学过程")
    stage_rows = [_stage_cell_values(stage) for stage in (stages or []) if isinstance(stage, dict)]
    if stage_rows:
        canvas.table(stage_rows, list(TABLE_WIDTHS), list(TABLE_HEADERS))
    else:
        canvas.text("还没有教学过程环节。")

    canvas.heading("五、课后作业")
    homework = plan.get("homework") or {}
    for label, key in (("基础作业", "basic"), ("探究作业", "inquiry")):
        items = homework.get(key) or [] if isinstance(homework, dict) else []
        canvas.text(f"{label}：" + ("；".join(_as_text(item) for item in items) or "待补充"))

    canvas.heading("六、参考资料与教学反思")
    references = plan.get("references") or []
    for reference in references:
        if isinstance(reference, dict):
            parts = [_as_text(reference.get("title")), _as_text(reference.get("year")), _as_text(reference.get("url"))]
            canvas.bullet("｜".join(part for part in parts if part))
        elif _as_text(reference):
            canvas.bullet(_as_text(reference))
    if not references:
        canvas.text("本教案未强制附加默认来源；需要核验时由教师指定资料。")
    canvas.text("教学反思：" + (_as_text(plan.get("reflection")) or "课后根据课堂记录补充。"))
    canvas.save(path)
