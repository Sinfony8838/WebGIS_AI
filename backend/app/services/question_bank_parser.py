# -*- coding: utf-8 -*-
"""题库 DOCX 解析器。

把"原卷版/解析版" DOCX 题库解析成结构化题组与题目。解析完全确定性
（不依赖 LLM），规则归纳自高考真题汇编的文档结构：

- 结构：题库标题 → 考点考情表（忽略）→ ``考点NN 标题`` 分节 → 题组。
- 题组 = 一段以 ``（年份·来源·高考真题）`` 开头的材料（或题干内嵌来源
  的独立题）+ 编号题 +（解析版）【答案】与【解析】/【详解】/【分析】块。
- 编号题形如 ``1．题干（  ）``；选项 ``A．…``（通常制表符并排多列）；
  ①②③④ 组合式选项的前置说明并入所属小问/题干。
- 综合题：**题干**含"根据材料完成下列小题/阅读图文材料，完成下列要求"
  等关键词（材料里出现"完成下面小题"不代表综合题）；题干后出现的
  ``(1)…``/``（1）…`` 一律按小问处理并把题组提升为综合题。个别文档用
  重新起号的 ``1.`` 表示选择式小问——编号小于组内首个题号时按小问处理
  （题干不含关键词但正文是小问结构的，如"小岗村"组，同样被覆盖）。
- 综合题材料与任务分流：任务句以"利用所学/结合材料/分析/说明…"等开头
  归入 ``task_text``，其余陈述性文本归入组材料。
- 答案/解析块中，无标记的续行跟随最近一次显式 ``(N)`` 定位到对应小问，
  避免 `(1)` 的多行答案串位到 `(2)`。
- 解析块之后的 ``2．…`` 是解析续段而非新题；只有未在当前考点出现过的
  编号、或题干内嵌（年份·来源·真题）时才开新题/新组。
- 题图通过 DOCX 关系 ID 绑定到所在题组；文档开头过小图片视为装饰丢弃，
  考点之前的题头/横幅图保留为题库级 ``unbound_images`` 供审计。

同一文件重复解析结果一致，便于内容指纹去重。
"""

from __future__ import annotations

import hashlib
import io
import re
import struct
import zipfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 常量与正则
# ---------------------------------------------------------------------------

SECTION_HEADER_RE = re.compile(r"^考点\s*(\d+)\s+(.*)$")
# （2025·湖南·高考真题）近年来，… / （2023·全国甲卷·高考真题）技术进步…
SOURCE_LINE_RE = re.compile(r"^[（(]\s*(\d{4})\s*·\s*([^）·]+?)\s*·\s*([^）]+?)\s*[）)]\s*(.*)$")
STEM_RE = re.compile(r"^(\d{1,3})\s*[．.、]\s*(.*)$")
SUB_RE = re.compile(r"^[（(]\s*(\d{1,2})\s*[）)]\s*(.*)$")
OPTION_LINE_RE = re.compile(r"^([A-DＡ-Ｄ])\s*[．.、]\s*(.*)$")
ANSWER_MARKER_RE = re.compile(r"^【(答案|解析|详解|分析)】\s*(.*)$")
# 【答案】1．D    2．A
NUMBERED_ANSWER_RE = re.compile(r"(\d{1,3})\s*[．.、]\s*([A-Da-d])(?![A-Za-z])")
BARE_ANSWER_RE = re.compile(r"^[A-Da-d]$")
COMBO_PREFIX_RE = re.compile(r"^[①②③④⑤⑥⑦⑧⑨]")
# 综合题任务句开头（区别于陈述性材料）
TASK_HINT_RE = re.compile(
    r"^(利用所学|结合(所学|材料|图文)|根据(材料|所学|图文|图示)|读图|读图文|试|请|"
    r"分析|说明|描述|概括|指出|比较|推测|提出|简述|评价|阐述|列举|归纳|绘图)"
)

# 图片尺寸下限：小于它的图片视为装饰图标，不入题库。
MIN_IMAGE_SIDE = 50
MIN_IMAGE_BYTES = 1024


# ---------------------------------------------------------------------------
# 上传安全校验
# ---------------------------------------------------------------------------

MAX_FILES_PER_IMPORT = 4
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
DOCX_MAGIC = b"PK\x03\x04"


class DocxValidationError(ValueError):
    """上传的文件不是安全的 DOCX 题库文件。"""


def validate_docx_bytes(raw: bytes, filename: str) -> None:
    """文件签名、体积与压缩包安全性检查。"""
    if not raw:
        raise DocxValidationError(f"文件 {filename} 为空。")
    if len(raw) > MAX_FILE_BYTES:
        raise DocxValidationError(f"文件 {filename} 超过单文件 50MB 上限。")
    if not raw.startswith(DOCX_MAGIC):
        raise DocxValidationError(f"文件 {filename} 不是有效的 DOCX（ZIP）文件。")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = set(archive.namelist())
            total = 0
            for info in archive.infolist():
                total += max(info.file_size, 0)
                name = info.filename.replace("\\", "/")
                if name.startswith("/") or ".." in name.split("/") or re.match(r"^[A-Za-z]:", name):
                    raise DocxValidationError(f"文件 {filename} 包含异常压缩路径：{info.filename}")
            if total > MAX_UNCOMPRESSED_BYTES:
                raise DocxValidationError(f"文件 {filename} 解压后超过 200MB 上限。")
            if "[Content_Types].xml" not in names or not any(n.startswith("word/") for n in names):
                raise DocxValidationError(f"文件 {filename} 缺少 DOCX 必需结构，可能已损坏。")
    except zipfile.BadZipFile as exc:
        raise DocxValidationError(f"文件 {filename} 无法作为压缩包打开：{exc}") from exc


# ---------------------------------------------------------------------------
# 图片工具（无第三方依赖的尺寸解析）
# ---------------------------------------------------------------------------


def image_dimensions(blob: bytes) -> Tuple[int, int]:
    """读取 PNG/JPEG/GIF/BMP 的像素尺寸，失败时返回 (0, 0)。"""
    try:
        if blob[:8] == b"\x89PNG\r\n\x1a\n" and len(blob) >= 24:
            width, height = struct.unpack(">II", blob[16:24])
            return int(width), int(height)
        if blob[:3] == b"\xff\xd8\xff":  # JPEG
            cursor = 2
            while cursor + 9 < len(blob):
                if blob[cursor] != 0xFF:
                    cursor += 1
                    continue
                marker = blob[cursor + 1]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    height, width = struct.unpack(">HH", blob[cursor + 5 : cursor + 9])
                    return int(width), int(height)
                if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                    cursor += 2
                    continue
                segment_length = struct.unpack(">H", blob[cursor + 2 : cursor + 4])[0]
                cursor += 2 + segment_length
        if blob[:6] in (b"GIF87a", b"GIF89a") and len(blob) >= 10:
            width, height = struct.unpack("<HH", blob[6:10])
            return int(width), int(height)
        if blob[:2] == b"BM" and len(blob) >= 26:
            width, height = struct.unpack("<ii", blob[18:26])
            return int(abs(width)), int(abs(height))
    except (struct.error, IndexError):
        pass
    return 0, 0


def is_decorative_image(blob: bytes, width: int, height: int) -> bool:
    """装饰性小图标：体积或边长过小的图片不入题库。

    注意不做"横幅比例"判断——考点之前的文档题头/横幅图会自然落入
    ``bank.unbound_images``（提取审计可见），不应在这里丢弃。
    """
    if len(blob) < MIN_IMAGE_BYTES:
        return True
    if width and height and (width < MIN_IMAGE_SIDE or height < MIN_IMAGE_SIDE):
        return True
    return False


# ---------------------------------------------------------------------------
# 解析数据结构
# ---------------------------------------------------------------------------


@dataclass
class ParsedImage:
    rId: str
    content_hash: str
    width: int
    height: int
    content_type: str
    order: int
    # 图片锚点：group（题组材料区）| question:<question_key>（某题题干后）
    anchor: str = "group"
    # 原始字节（服务层落盘用，不参与任何相等性判断）
    blob: bytes = b""


@dataclass
class ParsedQuestion:
    question_key: str = ""  # 组内唯一键，如 "q5"
    number: str = ""  # 展示题号（或选择式小问号）
    stem: str = ""
    task_text: str = ""  # 综合题整题任务文本（无小问时）
    options: List[str] = field(default_factory=list)
    answer: str = ""
    answer_letter: str = ""
    answer_index: Optional[int] = None
    explanation: str = ""
    sub_questions: List[Dict[str, Any]] = field(default_factory=list)
    para_start: int = 0
    para_end: int = 0


@dataclass
class ParsedGroup:
    group_key: str = ""  # 如 "g01_001"
    section_index: int = 0
    section_title: str = ""
    material: str = ""
    year: str = ""
    region: str = ""
    source_paper: str = ""
    is_composite: bool = False
    questions: List[ParsedQuestion] = field(default_factory=list)
    images: List[ParsedImage] = field(default_factory=list)
    tables: List[List[List[str]]] = field(default_factory=list)
    para_start: int = 0
    para_end: int = 0


@dataclass
class ParsedBank:
    title: str = ""
    sections: List[str] = field(default_factory=list)
    groups: List[ParsedGroup] = field(default_factory=list)
    # 通过尺寸检查但未绑定题组的图片（文档题头/横幅等），提取审计可见。
    unbound_images: List[ParsedImage] = field(default_factory=list)
    paragraph_count: int = 0
    table_count: int = 0


@dataclass
class _ParseContext:
    bank: ParsedBank
    section_index: int = 0
    section_title: str = ""
    section_stem_numbers: set = field(default_factory=set)
    group: Optional[ParsedGroup] = None
    active_stem: Optional[ParsedQuestion] = None
    in_answer: bool = False
    in_explanation: bool = False
    # 答案/解析块中最近一次显式 (N) 定位到的小问下标（组内最后一题），
    # 无标记续行据此归位，避免 (1) 的多行答案串位到 (2)。
    answer_sub_pos: Optional[int] = None
    explanation_sub_pos: Optional[int] = None
    seen_section_header: bool = False
    image_order: int = 0
    para_index: int = 0


# ---------------------------------------------------------------------------
# 解析器
# ---------------------------------------------------------------------------


class QuestionBankDocxParser:
    """把单个 DOCX（原卷版或解析版）解析为 ParsedBank。"""

    def __init__(self, filename: str, raw: bytes):
        self.filename = filename
        self.raw = raw

    def parse(self) -> ParsedBank:
        from docx import Document as DocxDocument
        from docx.oxml.ns import qn
        from docx.table import Table as DocxTable
        from docx.text.paragraph import Paragraph as DocxParagraph

        document = DocxDocument(io.BytesIO(self.raw))
        elements: List[Tuple[str, Any]] = []
        for child in document.element.body.iterchildren():
            if child.tag == qn("w:p"):
                elements.append(("p", DocxParagraph(child, document)))
            elif child.tag == qn("w:tbl"):
                elements.append(("tbl", DocxTable(child, document)))

        ctx = _ParseContext(bank=ParsedBank())
        ctx.bank.table_count = sum(1 for kind, _ in elements if kind == "tbl")
        ctx.bank.paragraph_count = sum(1 for kind, _ in elements if kind == "p")

        for kind, element in elements:
            if kind == "tbl":
                self._handle_table(ctx, element)
            else:
                self._handle_paragraph(ctx, element, document)

        self._finalize(ctx)
        return ctx.bank

    # -- 元素处理 ---------------------------------------------------------

    def _handle_table(self, ctx: _ParseContext, table: Any) -> None:
        rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
        if ctx.group is not None and ctx.seen_section_header:
            ctx.group.tables.append(rows)
        # 首个考点之前的表格是考情统计表，忽略。

    def _handle_paragraph(self, ctx: _ParseContext, paragraph: Any, document: Any) -> None:
        from docx.oxml.ns import qn

        ctx.para_index += 1
        text = paragraph.text.strip()
        # 先分派文本（可能开启新题组/激活题干），再挂载图片——否则材料
        # 段落内嵌的题图会错误地挂到上一个题组。
        self._dispatch_text(ctx, text)
        for blip in paragraph._p.findall(".//" + qn("a:blip")):
            rid = blip.get(qn("r:embed") or "")
            self._handle_image(ctx, document, rid)

    def _dispatch_text(self, ctx: _ParseContext, text: str) -> None:
        if not text:
            return

        # 1) 考点标题：新分节，重置已见题号与解析状态
        header = SECTION_HEADER_RE.match(text)
        if header:
            ctx.section_index += 1
            ctx.section_title = (header.group(2) or "").strip()
            if ctx.section_title and ctx.section_title not in ctx.bank.sections:
                ctx.bank.sections.append(ctx.section_title)
            ctx.group = None
            ctx.active_stem = None
            ctx.section_stem_numbers = set()
            ctx.in_answer = ctx.in_explanation = False
            ctx.answer_sub_pos = ctx.explanation_sub_pos = None
            ctx.seen_section_header = True
            return

        # 2) 题库标题：首个考点之前的短文本
        if not ctx.seen_section_header:
            if not ctx.bank.title and len(text) <= 60:
                ctx.bank.title = text
            return

        # 3) 【答案】/【解析】/【详解】/【分析】
        #    注意传原始 text：消费端靠重新匹配标记区分"标记行"与"续行"。
        marker = ANSWER_MARKER_RE.match(text)
        if marker and ctx.group is not None:
            label = marker.group(1)
            if label == "答案":
                ctx.in_answer, ctx.in_explanation = True, False
                ctx.active_stem = None
                self._consume_answer(ctx, ctx.group, text)
            else:
                ctx.in_answer, ctx.in_explanation = False, True
                ctx.active_stem = None
                self._consume_explanation(ctx, ctx.group, text)
            return

        # 4) 材料段落：（年份·来源·高考真题）…… → 新题组
        source = SOURCE_LINE_RE.match(text)
        if source:
            self._start_group(ctx, year=source.group(1), region=source.group(2),
                              source_paper=source.group(3), material=source.group(4).strip(),
                              para_index=ctx.para_index)
            return

        # 5) 编号行：解析续段 / 综合题选择式小问 / 新题
        stem = STEM_RE.match(text)
        if stem:
            if self._handle_numbered(ctx, number=stem.group(1), body=stem.group(2).strip()):
                return

        # 6) 小问 (1) / （1）
        sub = SUB_RE.match(text)
        if sub and ctx.group is not None:
            if ctx.in_answer:
                self._consume_answer(ctx, ctx.group, text)
            elif ctx.in_explanation:
                self._consume_explanation(ctx, ctx.group, text)
            elif ctx.active_stem is not None:
                # 题干语境下的 (N) 一律按小问处理（题干未必含综合题关键词，
                # 如"小岗村的蜕变"组）。
                ctx.active_stem.sub_questions.append(
                    {"index": sub.group(1), "text": sub.group(2).strip(), "options": [],
                     "answer": "", "answer_index": None, "explanation": ""}
                )
                ctx.group.is_composite = True
            elif ctx.group.is_composite and ctx.group.questions:
                ctx.group.questions[-1].sub_questions.append(
                    {"index": sub.group(1), "text": sub.group(2).strip(), "options": [],
                     "answer": "", "answer_index": None, "explanation": ""}
                )
            else:
                self._append_material(ctx.group, text)
            return

        # 7) 选项行
        if (
            OPTION_LINE_RE.match(text)
            and ctx.group is not None
            and ctx.active_stem is not None
            and not ctx.in_answer
            and not ctx.in_explanation
        ):
            target = ctx.active_stem
            if target.sub_questions:
                last_sub = target.sub_questions[-1]
                last_sub["options"] = self._merge_option_line(last_sub["options"], text)
            else:
                target.options = self._merge_option_line(target.options, text)
            return

        # 8) 普通文本：按状态归位
        if ctx.in_answer and ctx.group is not None:
            self._consume_answer(ctx, ctx.group, text)
            return
        if ctx.in_explanation and ctx.group is not None:
            self._consume_explanation(ctx, ctx.group, text)
            return
        if ctx.group is None:
            return  # 考点标题后的散落说明文本，忽略
        if ctx.active_stem is not None:
            self._absorb_stem_text(ctx, text)
            return
        self._append_material(ctx.group, text)

    def _handle_image(self, ctx: _ParseContext, document: Any, rid: str) -> None:
        try:
            part = document.part.related_parts[rid]
        except KeyError:
            return
        blob = part.blob
        width, height = image_dimensions(blob)
        if is_decorative_image(blob, width, height):
            return
        image = ParsedImage(
            rId=rid,
            content_hash=hashlib.sha256(blob).hexdigest(),
            width=width,
            height=height,
            content_type=str(part.content_type or ""),
            order=ctx.image_order,
            blob=blob,
        )
        ctx.image_order += 1
        if ctx.group is None or not ctx.seen_section_header:
            ctx.bank.unbound_images.append(image)
            return
        if ctx.active_stem is not None and not ctx.in_answer and not ctx.in_explanation:
            image.anchor = f"question:{ctx.active_stem.question_key or ctx.active_stem.number}"
        ctx.group.images.append(image)

    # -- 编号行分派 ---------------------------------------------------------

    def _handle_numbered(self, ctx: _ParseContext, number: str, body: str) -> bool:
        """返回 True 表示已处理。"""
        group = ctx.group

        # a) 解析/答案续段：编号在当前考点已作为题号出现过
        if group is not None and (ctx.in_answer or ctx.in_explanation) and int(number) in ctx.section_stem_numbers:
            question = self._find_question(group, number)
            if question is None and group.questions:
                question = group.questions[-1]
            if question is not None:
                if ctx.in_answer:
                    self._apply_answer_text(question, body)
                else:
                    self._apply_explanation_text(question, body)
                return True

        # b) 综合题选择式小问：编号小于组内首个题号（文档用重新起号的 1. 表示）
        if (
            group is not None
            and group.is_composite
            and group.questions
            and not ctx.in_answer
            and not ctx.in_explanation
            and int(number) < int(group.questions[0].number or "999")
        ):
            group.questions[-1].sub_questions.append(
                {"index": number, "text": body, "options": [], "answer": "", "answer_index": None, "explanation": ""}
            )
            return True

        # c) 新题。题干内嵌（年份·来源·真题）→ 一定是新题组；
        #    否则在答案/解析状态后开独立题组，或延续当前题组。
        inline = SOURCE_LINE_RE.match(body)
        year = region = source_paper = ""
        stem_text = body
        if inline:
            year, region, source_paper = inline.group(1), inline.group(2), inline.group(3)
            stem_text = inline.group(4).strip()

        if group is None or inline is not None or ctx.in_answer or ctx.in_explanation:
            self._start_group(ctx, year=year, region=region, source_paper=source_paper,
                              material="", para_index=ctx.para_index)
            group = ctx.group
        question = ParsedQuestion(number=number, stem=stem_text,
                                  para_start=ctx.para_index, para_end=ctx.para_index)
        group.questions.append(question)
        if re.search(r"(完成下列|完成下面|回答下列|回答下面|完成下列要求|下列小题|下列要求|下列问题)", body):
            group.is_composite = True
        ctx.section_stem_numbers.add(int(number))
        ctx.active_stem = question
        ctx.in_answer = ctx.in_explanation = False
        ctx.answer_sub_pos = ctx.explanation_sub_pos = None
        return True

    def _start_group(self, ctx: _ParseContext, *, year: str, region: str, source_paper: str,
                     material: str, para_index: int) -> None:
        group = ParsedGroup(
            section_index=ctx.section_index,
            section_title=ctx.section_title,
            material=material,
            year=year,
            region=region,
            source_paper=source_paper,
            para_start=para_index,
            para_end=para_index,
        )
        ctx.bank.groups.append(group)
        ctx.group = group
        ctx.active_stem = None
        ctx.in_answer = ctx.in_explanation = False
        ctx.answer_sub_pos = ctx.explanation_sub_pos = None

    # -- 答案 / 解析消费 ---------------------------------------------------

    def _consume_answer(self, ctx: _ParseContext, group: ParsedGroup, text: str) -> None:
        marker = ANSWER_MARKER_RE.match(text)
        payload = marker.group(2).strip() if marker else text.strip()
        is_marker_line = marker is not None
        if is_marker_line:
            ctx.answer_sub_pos = None

        # 编号式：1．D    2．A（仅【答案】行本身）
        pairs = NUMBERED_ANSWER_RE.findall(payload)
        if pairs and is_marker_line:
            matched = False
            for number, letter in pairs:
                question = self._find_question(group, number)
                if question is not None:
                    self._apply_answer_letter(question, letter.upper())
                    matched = True
                    continue
                if self._apply_sub_letter_answer(group, number, letter.upper()):
                    matched = True
            if matched:
                return
            # 一个都没对上（编号既非题号也非小问号）→ 落入后续分支按文本处理

        # 编号文字式："1．特征：……"（综合题小问的文字答案）
        stem = STEM_RE.match(payload)
        if stem and is_marker_line:
            number, body = stem.group(1), stem.group(2).strip()
            pos = self._find_sub_pos(group, number)
            if pos is not None:
                self._set_sub_answer(group, pos, body)
                ctx.answer_sub_pos = pos
                return
            question = self._find_question(group, number)
            if question is not None:
                self._apply_answer_text(question, body)
                return

        # 小问式：(1)……
        sub = SUB_RE.match(payload)
        if sub:
            pos = self._apply_sub_answer(group, sub.group(1), sub.group(2).strip())
            if pos is not None:
                ctx.answer_sub_pos = pos
            return

        # 裸字母：组内第一个待答单元
        if BARE_ANSWER_RE.match(payload) and group.questions:
            self._apply_bare_answer(group, payload.strip().upper())
            return

        # 直接文本：整题答案，或跟随最近 (N) 的小问答案续行
        if not group.questions:
            return
        last = group.questions[-1]
        if ctx.answer_sub_pos is not None and last.sub_questions:
            pos = min(ctx.answer_sub_pos, len(last.sub_questions) - 1)
            self._set_sub_answer(group, pos, payload)
            return
        if last.sub_questions:
            self._set_sub_answer(group, len(last.sub_questions) - 1, payload)
            return
        if not last.answer.strip() and not last.options:
            last.answer = payload
            return
        last.answer = self._join(last.answer, payload)

    def _consume_explanation(self, ctx: _ParseContext, group: ParsedGroup, text: str) -> None:
        marker = ANSWER_MARKER_RE.match(text)
        payload = marker.group(2).strip() if marker else text.strip()
        if marker is not None:
            ctx.explanation_sub_pos = None

        stem = STEM_RE.match(payload)
        if stem:
            number, body = stem.group(1), stem.group(2).strip()
            question = self._find_question(group, number)
            if question is not None:
                self._apply_explanation_text(question, body)
                return
            pos = self._find_sub_pos(group, number)
            if pos is not None:
                self._set_sub_explanation(group, pos, body)
                ctx.explanation_sub_pos = pos
                return

        sub = SUB_RE.match(payload)
        if sub:
            pos = self._apply_sub_explanation(group, sub.group(1), sub.group(2).strip())
            if pos is not None:
                ctx.explanation_sub_pos = pos
            return

        if not group.questions:
            return
        last = group.questions[-1]
        if ctx.explanation_sub_pos is not None and last.sub_questions:
            pos = min(ctx.explanation_sub_pos, len(last.sub_questions) - 1)
            self._set_sub_explanation(group, pos, payload)
            return
        if last.sub_questions:
            self._set_sub_explanation(group, len(last.sub_questions) - 1, payload)
            return
        self._apply_explanation_text(last, payload)

    # -- 小问定位与写入 -----------------------------------------------------

    def _find_sub_pos(self, group: ParsedGroup, number: str) -> Optional[int]:
        """在组内最后一题的小问中按编号定位（综合题组均为单题）。"""
        if not group.questions:
            return None
        for pos, item in enumerate(group.questions[-1].sub_questions):
            if str(item.get("index")) == number:
                return pos
        return None

    def _set_sub_answer(self, group: ParsedGroup, pos: int, answer_text: str) -> None:
        item = group.questions[-1].sub_questions[pos]
        if BARE_ANSWER_RE.match(answer_text.strip()) and item.get("options"):
            self._set_letter_answer(list(item["options"]), item, answer_text.strip().upper())
            return
        item["answer"] = self._join(item.get("answer"), answer_text)

    def _set_sub_explanation(self, group: ParsedGroup, pos: int, explanation_text: str) -> None:
        item = group.questions[-1].sub_questions[pos]
        item["explanation"] = self._join(item.get("explanation"), explanation_text)

    def _apply_sub_answer(self, group: ParsedGroup, sub_number: str, answer_text: str) -> Optional[int]:
        """按 (N) 写入小问答案；返回定位到的小问下标。"""
        pos = self._find_sub_pos(group, sub_number)
        if pos is not None:
            self._set_sub_answer(group, pos, answer_text)
            return pos
        if group.questions:  # 无对应小问（题面缺失小问）→ 追加
            last = group.questions[-1]
            last.sub_questions.append(
                {"index": sub_number, "text": "", "options": [], "answer": answer_text,
                 "answer_index": None, "explanation": ""}
            )
            return len(last.sub_questions) - 1
        return None

    def _apply_sub_explanation(self, group: ParsedGroup, sub_number: str, explanation_text: str) -> Optional[int]:
        pos = self._find_sub_pos(group, sub_number)
        if pos is not None:
            self._set_sub_explanation(group, pos, explanation_text)
            return pos
        if group.questions:
            last = group.questions[-1]
            last.sub_questions.append(
                {"index": sub_number, "text": "", "options": [], "answer": "",
                 "answer_index": None, "explanation": explanation_text}
            )
            return len(last.sub_questions) - 1
        return None

    def _apply_sub_letter_answer(self, group: ParsedGroup, number: str, letter: str) -> bool:
        """编号式答案 "1．A" 中编号对应小问时写入该小问。"""
        pos = self._find_sub_pos(group, number)
        if pos is None:
            return False
        item = group.questions[-1].sub_questions[pos]
        self._set_letter_answer(list(item.get("options") or []), item, letter)
        return True

    def _apply_bare_answer(self, group: ParsedGroup, letter: str) -> None:
        for question in reversed(group.questions):
            if question.sub_questions:
                for item in reversed(question.sub_questions):
                    if not str(item.get("answer") or "").strip():
                        self._set_letter_answer(list(item.get("options") or []), item, letter)
                        return
            if not question.answer.strip():
                self._apply_answer_letter(question, letter)
                return

    # -- 文本归位 -----------------------------------------------------------

    def _absorb_stem_text(self, ctx: _ParseContext, text: str) -> None:
        """题干激活时的普通文本：按综合题/小问语境分流。"""
        question = ctx.active_stem
        group = ctx.group
        assert question is not None and group is not None
        if question.sub_questions:
            # ①②③④ 组合选项说明并入所属小问；其余陈述性文本（多为数据段）
            # 归组材料。
            if COMBO_PREFIX_RE.match(text):
                question.sub_questions[-1]["text"] = self._join(question.sub_questions[-1]["text"], text)
            else:
                self._append_material(group, text)
            return
        if group.is_composite:
            if question.task_text:
                question.task_text = self._join(question.task_text, text)
            elif TASK_HINT_RE.match(text):
                question.task_text = text
            elif COMBO_PREFIX_RE.match(text):
                question.stem = self._join(question.stem, text)
            else:
                self._append_material(group, text)
            return
        if question.options:
            # 选项已出现后的补充行并到材料（罕见兜底）
            self._append_material(group, text)
            return
        question.stem = self._join(question.stem, text)

    @staticmethod
    def _append_material(group: ParsedGroup, text: str) -> None:
        group.material = QuestionBankDocxParser._join(group.material, text)

    @staticmethod
    def _join(existing: Any, addition: str) -> str:
        base = str(existing or "").strip()
        extra = str(addition or "").strip()
        if not extra:
            return base
        return (base + "\n" + extra).strip() if base else extra

    @staticmethod
    def _merge_option_line(options: List[str], line: str) -> List[str]:
        merged = list(options)
        for part in re.split(r"\t+", line.strip()):
            part = part.strip()
            match = OPTION_LINE_RE.match(part)
            if match:
                merged.append(f"{match.group(1)}．{match.group(2).strip()}")
            elif part and merged:
                merged[-1] = merged[-1].rstrip() + part
            elif part:
                merged.append(part)
        return merged

    @staticmethod
    def _find_question(group: ParsedGroup, number: str) -> Optional[ParsedQuestion]:
        for question in group.questions:
            if question.number == number:
                return question
        return None

    @staticmethod
    def _apply_answer_letter(question: ParsedQuestion, letter: str) -> None:
        question.answer_letter = letter
        question.answer = letter
        for index, option in enumerate(question.options):
            if option.startswith(f"{letter}．"):
                question.answer_index = index
                break

    @staticmethod
    def _set_letter_answer(options: List[str], item: Dict[str, Any], letter: str) -> None:
        item["answer"] = letter
        for index, option in enumerate(options):
            if option.startswith(f"{letter}．"):
                item["answer_index"] = index
                break

    @staticmethod
    def _apply_answer_text(question: ParsedQuestion, text: str) -> None:
        # 续行恰好是单个选项字母（"3．B" 换行续写）时按选项答案处理
        if BARE_ANSWER_RE.match(text.strip()):
            QuestionBankDocxParser._apply_answer_letter(question, text.strip().upper())
            return
        if question.sub_questions:
            item = question.sub_questions[-1]
            item["answer"] = QuestionBankDocxParser._join(item.get("answer"), text)
        else:
            question.answer = QuestionBankDocxParser._join(question.answer, text)

    @staticmethod
    def _apply_explanation_text(question: ParsedQuestion, text: str) -> None:
        if question.sub_questions:
            item = question.sub_questions[-1]
            item["explanation"] = QuestionBankDocxParser._join(item.get("explanation"), text)
        else:
            question.explanation = QuestionBankDocxParser._join(question.explanation, text)

    # -- 收尾 ---------------------------------------------------------------

    def _finalize(self, ctx: _ParseContext) -> None:
        bank = ctx.bank
        if not bank.title:
            bank.title = re.sub(r"\.(docx|doc)$", "", self.filename, flags=re.IGNORECASE).strip()
        for g_index, group in enumerate(bank.groups, start=1):
            group.group_key = f"g{group.section_index:02d}_{g_index:03d}"
            for q_index, question in enumerate(group.questions, start=1):
                if not question.question_key:
                    question.question_key = f"q{q_index}"
            if group.para_end < group.para_start:
                group.para_end = group.para_start


# ---------------------------------------------------------------------------
# 原卷版 / 解析版 配对与合并
# ---------------------------------------------------------------------------

ORIGINAL_SUFFIXES = ("原卷版", "学生版")
ANALYSIS_SUFFIXES = ("解析版", "教师版")


def normalize_bank_filename(filename: str) -> Tuple[str, str]:
    """去掉（原卷版）/（解析版）后缀，返回 (基础名, 版本标签 original|analysis|unknown)。"""
    base = filename
    for suffix in ORIGINAL_SUFFIXES + ANALYSIS_SUFFIXES:
        base = base.replace(f"（{suffix}）", "").replace(f"({suffix})", "")
    base = base.strip()
    stem = re.sub(r"\.(docx|doc)$", "", filename, flags=re.IGNORECASE)
    if any(s in stem for s in ORIGINAL_SUFFIXES):
        return base, "original"
    if any(s in stem for s in ANALYSIS_SUFFIXES):
        return base, "analysis"
    return base, "unknown"


def _question_fingerprint(section_title: str, question: ParsedQuestion) -> str:
    payload = "|".join(
        [
            re.sub(r"\s+", "", section_title),
            question.number,
            re.sub(r"\s+", "", question.stem)[:120],
            re.sub(r"\s+", "", "\n".join(question.options))[:120],
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def pair_parsed_banks(
    original: Optional[ParsedBank],
    analysis: Optional[ParsedBank],
) -> List[Dict[str, Any]]:
    """合并原卷版题面与解析版答案，输出题组记录列表。

    原卷版是学生题面来源；解析版补充答案与官方解析。两边按
    (考点序号, 组序) 对齐，并逐题做指纹校验；不一致时合并仍完成，
    但在 ``pairing_note`` 中说明，供导入界面提示教师复核。
    """
    if original is not None and analysis is not None:
        if len(original.groups) != len(analysis.groups):
            raise DocxValidationError(
                f"原卷版与解析版题组数不一致（{len(original.groups)} 对 {len(analysis.groups)}），无法自动配对。"
            )
        merged: List[Dict[str, Any]] = []
        for o_group, a_group in zip(original.groups, analysis.groups):
            note = ""
            if o_group.section_index != a_group.section_index:
                note = "考点序号不一致，按顺序配对"
            elif not _fingerprints_align(o_group, a_group):
                note = "题面指纹不完全一致，已按顺序合并，请复核"
            merged.append(_merge_group(o_group, a_group, note))
        return merged
    source = original or analysis
    if source is None:
        raise DocxValidationError("没有可解析的题库文件。")
    return [_merge_group(group, None, "") for group in source.groups]


def _fingerprints_align(o_group: ParsedGroup, a_group: ParsedGroup) -> bool:
    if len(o_group.questions) != len(a_group.questions):
        return False
    return all(
        _question_fingerprint(o_group.section_title, o_question)
        == _question_fingerprint(a_group.section_title, a_question)
        for o_question, a_question in zip(o_group.questions, a_group.questions)
    )


def _merge_group(o_group: ParsedGroup, a_group: Optional[ParsedGroup], note: str) -> Dict[str, Any]:
    """合并一个题组：题面取原卷版（缺省回退解析版），答案/解析取解析版。"""
    face = o_group or a_group
    answer = a_group or o_group
    answer_questions = list(answer.questions)
    questions = [
        _merge_question(question, answer_questions[index] if index < len(answer_questions) else None)
        for index, question in enumerate(face.questions)
    ]
    # 图片合并：两版本张数一致时直接取原卷版（学生题面所见，且避免同一张图
    # 在两版本中重渲染导致重复）；张数不一致时按内容哈希取并集。
    images: List[Dict[str, Any]] = [img.__dict__ for img in face.images]
    if a_group is not None and o_group is not None and len(o_group.images) != len(a_group.images):
        seen = {img["content_hash"] for img in images}
        for img in a_group.images:
            if img.content_hash not in seen:
                images.append(img.__dict__)
                seen.add(img.content_hash)
    return {
        "group_key": face.group_key,
        "section_index": face.section_index,
        "section_title": face.section_title,
        "material": face.material,
        "year": face.year or (a_group.year if a_group else ""),
        "region": face.region or (a_group.region if a_group else ""),
        "source_paper": face.source_paper or (a_group.source_paper if a_group else ""),
        "is_composite": bool(face.is_composite or (a_group.is_composite if a_group else False)),
        "questions": questions,
        "images": images,
        "tables": face.tables,
        "pairing_note": note,
    }


def _merge_question(face: ParsedQuestion, answer: Optional[ParsedQuestion]) -> Dict[str, Any]:
    source = answer or face
    face_subs = list(face.sub_questions)
    answer_subs = list(source.sub_questions)
    sub_questions: List[Dict[str, Any]] = []
    for index in range(max(len(face_subs), len(answer_subs))):
        face_sub = face_subs[index] if index < len(face_subs) else {}
        answer_sub = answer_subs[index] if index < len(answer_subs) else {}
        sub_questions.append(
            {
                "index": str(face_sub.get("index") or answer_sub.get("index") or index + 1),
                "text": str(face_sub.get("text") or "") or str(answer_sub.get("text") or ""),
                "options": list(face_sub.get("options") or answer_sub.get("options") or []),
                "answer": str(answer_sub.get("answer") or ""),
                "answer_index": answer_sub.get("answer_index"),
                "explanation": str(answer_sub.get("explanation") or ""),
            }
        )
    return {
        "question_key": face.question_key or f"q{face.number}",
        "number": face.number,
        "stem": face.stem,
        "task_text": face.task_text,
        "options": list(face.options),
        "answer": source.answer,
        "answer_letter": source.answer_letter,
        "answer_index": source.answer_index,
        "explanation": source.explanation,
        "sub_questions": sub_questions,
        "answer_complete": _answer_complete(
            source.answer, source.answer_index, sub_questions, bool(face.options)
        ),
    }


def _answer_complete(
    answer: str,
    answer_index: Optional[int],
    sub_questions: List[Dict[str, Any]],
    has_options: bool,
) -> bool:
    if sub_questions:
        return all(str(sub.get("answer") or "").strip() for sub in sub_questions)
    if has_options:
        return answer_index is not None or bool(str(answer).strip())
    return bool(str(answer).strip())
