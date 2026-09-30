"""Word (.docx) lesson-plan import: map paragraphs/tables/images to draft fields.

解析原则（与设计文档一致）：
- 表格优先：表头含「环节/阶段」的表映射为教学环节；两列键值表映射基础信息。
- 段落按标题关键词归字段；标量字段只取标题后第一段，其余段落进入「待归类」，
  宁可让教师校对，也不把无法识别的内容悄悄并进字段。
- 图片原样提取为待归类素材，不自动进入环节。
"""
from __future__ import annotations

import re
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

FIELD_LABELS: Dict[str, str] = {
    "title": "课题", "subject": "学科", "grade": "年级", "duration_minutes": "课时",
    "objectives": "教学目标", "key_difficulties": "教学重难点", "methods": "教学方法",
    "knowledge_structure": "知识结构", "core_questions": "核心问题与问题链",
    "board_design": "板书设计", "homework": "课后作业", "design_thinking": "设计思路",
    "reflection": "教学反思", "references": "参考资料",
    "curriculum_interpretation": "课标解读", "student_analysis": "学情分析",
    "textbook_analysis": "教材分析", "stages": "教学过程",
}

LIST_FIELDS = frozenset({"objectives", "methods", "references", "knowledge_structure", "homework"})

# 标题/行内关键词 → 字段（按序首个命中）。
KEYWORD_TARGETS: Tuple[Tuple[str, str], ...] = (
    ("课题", "title"), ("标题", "title"), ("学科", "subject"),
    ("年级", "grade"), ("课时", "duration_minutes"),
    ("教学目标", "objectives"), ("学习目标", "objectives"),
    ("教学重难点", "key_difficulties"), ("教学重点", "kd_key"), ("重点", "kd_key"),
    ("教学难点", "kd_difficult"), ("难点", "kd_difficult"),
    ("教学方法", "methods"), ("教学策略", "methods"),
    ("课标解读", "curriculum_interpretation"), ("课标要求", "curriculum_interpretation"),
    ("学情分析", "student_analysis"), ("教材分析", "textbook_analysis"),
    ("核心问题", "core_questions"), ("问题链", "core_questions"),
    ("知识结构", "knowledge_structure"),
    ("设计思路", "design_thinking"), ("板书设计", "board_design"),
    ("作业", "homework"), ("教学反思", "reflection"), ("参考资料", "references"),
    ("教学过程", "stages"), ("教学环节", "stages"),
)

INLINE_KEY_PATTERN = re.compile(
    r"^(?:[一二三四五六七八九十\d]+\s*[、\.．]?\s*)?"
    r"(?P<key>课题|标题|学科|年级|课时|教学目标|教学重点|重点|教学难点|难点|教学方法|"
    r"课标解读|课标要求|学情分析|教材分析|核心问题|知识结构|设计思路|板书设计|作业|教学反思|参考资料)"
    r"\s*[:：]\s*(?P<value>.*)$"
)
NUMBERING_PREFIX = re.compile(r"^[一二三四五六七八九十\d]+\s*[、\.．]\s*")
BULLET_PREFIX = re.compile(r"^[•·\-–—*\d]+[、\.．\)）]?\s*")
TERMINAL_PUNCT = ("。", "！", "？", "；")

STAGE_COLUMN_ALIASES: Tuple[Tuple[str, str], ...] = (
    ("环节名称", "title"), ("教学环节", "title"), ("环节", "title"), ("阶段", "title"), ("名称", "title"),
    ("环节时长", "minutes"), ("时长", "minutes"), ("时间", "minutes"), ("分钟", "minutes"),
    ("知识点", "knowledge_point"), ("知识单元", "knowledge_point"),
    ("教师活动", "teacher_activities"), ("教师行为", "teacher_activities"),
    ("学生活动", "student_activities"), ("学生行为", "student_activities"),
    ("材料", "material"), ("素材", "material"), ("资源", "material"), ("教学材料", "material"),
    ("问题链", "question_chain"), ("问题设计", "question_chain"), ("问题", "question_chain"),
    ("知识结论", "knowledge_conclusion"), ("结论", "knowledge_conclusion"), ("小结", "knowledge_conclusion"),
    ("设计意图", "design_intent"), ("意图", "design_intent"),
)

SCALAR_TABLE_KEYS = ("课题", "标题", "学科", "年级", "课时", "课型")

MIME_EXTENSIONS = {
    "image/png": "png", "image/jpeg": "jpg", "image/jpg": "jpg",
    "image/gif": "gif", "image/webp": "webp", "image/bmp": "bmp",
}


def _normalize_header(text: str) -> str:
    return re.sub(r"[\s（）()【】]", "", str(text or ""))


def _match_keyword(text: str) -> Optional[str]:
    stripped = NUMBERING_PREFIX.sub("", str(text or "").strip()).strip()
    for keyword, target in KEYWORD_TARGETS:
        if stripped.startswith(keyword):
            return target
    return None


def _is_heading(paragraph: Paragraph) -> bool:
    text = paragraph.text.strip()
    if not text:
        return False
    style_name = str(getattr(paragraph.style, "name", "") or "")
    if "Heading" in style_name or "标题" in style_name:
        return True
    if len(text) > 30 or "：" in text or ":" in text:
        return False
    if NUMBERING_PREFIX.match(text):
        return True
    runs = paragraph.runs
    return bool(runs) and all(run.bold for run in runs) and len(text) <= 20


def _split_items(text: str) -> List[str]:
    items = []
    for line in re.split(r"[\n；;]", str(text or "")):
        cleaned = BULLET_PREFIX.sub("", line.strip()).strip("。；;，,")
        if cleaned:
            items.append(cleaned)
    return items


def _assign(draft: Dict[str, Any], field: str, text: str) -> None:
    value = str(text or "").strip()
    if not value:
        return
    if field == "title":
        if not str(draft.get("title") or "").strip():
            draft["title"] = value
    elif field == "grade":
        if not draft.get("grade"):
            draft["grade"] = value
    elif field == "duration_minutes":
        if not draft.get("duration_minutes"):
            digits = re.sub(r"[^0-9]", "", value)
            if digits:
                draft["duration_minutes"] = int(digits)
    elif field == "subject":
        if not draft.get("subject") or draft.get("subject") == "地理":
            draft["subject"] = value
    elif field in {"objectives", "methods", "references", "knowledge_structure"}:
        draft[field] = (draft.get(field) or []) + _split_items(value)
    elif field == "homework":
        homework = draft.setdefault("homework", {"basic": [], "inquiry": []})
        target = "inquiry" if value.startswith(("探究", "开放")) else "basic"
        homework[target] = homework.get(target, []) + _split_items(value)
    elif field == "core_questions":
        core = draft.setdefault("core_questions", {"core": "", "sub_questions": []})
        if not core.get("core"):
            core["core"] = value
        else:
            core.setdefault("sub_questions", []).extend(_split_items(value))
    elif field == "kd_key":
        key = draft.setdefault("key_difficulties", {"key": [], "difficult": []})
        key["key"] = key.get("key", []) + _split_items(value)
    elif field == "kd_difficult":
        difficult = draft.setdefault("key_difficulties", {"key": [], "difficult": []})
        difficult["difficult"] = difficult.get("difficult", []) + _split_items(value)
    elif field == "key_difficulties":
        key = draft.setdefault("key_difficulties", {"key": [], "difficult": []})
        for line in _split_items(value):
            if line.startswith(("重点", "难点")):
                bucket = "key" if line.startswith("重点") else "difficult"
                key[bucket] = key.get(bucket, []) + _split_items(line.split("：", 1)[-1])
            else:
                key["key"] = key.get("key", []) + [line]
    else:
        # 标量文本字段：仅首段生效（其余进待归类）。
        if not str(draft.get(field) or "").strip():
            draft[field] = value


def _stage_table_to_stages(table: Table, unclassified: Optional[List[Dict[str, Any]]] = None) -> Tuple[List[Dict[str, Any]], List[str]]:
    rows = list(table.rows)
    if not rows:
        return [], []
    header_cells = [_normalize_header(cell.text) for cell in rows[0].cells]
    column_field: Dict[int, str] = {}
    for index, header in enumerate(header_cells):
        for alias, field in STAGE_COLUMN_ALIASES:
            if header.startswith(alias) or alias in header:
                column_field.setdefault(index, field)
                break
    if not any(field == "title" for field in column_field.values()):
        return [], []
    stages: List[Dict[str, Any]] = []
    for row in rows[1:]:
        values = [cell.text.strip() for cell in row.cells]
        if not any(values):
            continue
        stage: Dict[str, Any] = {
            "stage_id": f"import_{uuid4().hex[:6]}_{len(stages) + 1}",
            "kind": "presentation",
            "scene": {},
        }
        for index, value in enumerate(values):
            field = column_field.get(index)
            if not field:
                if value and unclassified is not None:
                    unclassified.append({"kind": "table", "heading": "教学过程未识别列",
                                         "text": f"{values[0]}｜{header_cells[index]}：{value}"})
                continue
            if field == "minutes":
                digits = re.sub(r"[^0-9]", "", value)
                stage["minutes"] = int(digits) if digits else 0
            elif field in {"teacher_activities", "student_activities", "question_chain"}:
                stage[field] = _split_items(value)
            elif field == "material":
                stage["material"] = "；".join(part for part in value.splitlines() if part.strip())
            elif field in {"title", "knowledge_point", "knowledge_conclusion", "design_intent"}:
                stage[field] = value
        if str(stage.get("title") or "").strip():
            stages.append(stage)
        elif unclassified is not None:
            unclassified.append({"kind": "table", "heading": "教学过程未识别行", "text": "｜".join(values)})
    return stages, header_cells


def _scalar_table_pairs(table: Table) -> Dict[str, str]:
    pairs: Dict[str, str] = {}
    for row in list(table.rows)[0:]:
        cells = [cell.text.strip() for cell in row.cells]
        if len(cells) >= 2 and cells[0] in SCALAR_TABLE_KEYS:
            pairs[cells[0]] = cells[1]
    return pairs


def parse_lesson_docx(data: bytes) -> Dict[str, Any]:
    """解析 .docx 字节流 → {draft, mapping, unclassified}。

    unclassified 图片项带 ``data`` 字节，由调用方落盘后替换为 ``url``。
    """
    try:
        document = Document(BytesIO(data))
    except Exception as exc:  # noqa: BLE001 - 任何解析失败都按无法识别处理
        raise ValueError("无法解析该 Word 文档，请确认文件为 .docx 格式且未损坏。") from exc

    draft: Dict[str, Any] = {}
    mapping: List[Dict[str, Any]] = []
    unclassified: List[Dict[str, Any]] = []
    heading = ""
    pending_field: Optional[str] = None

    def record(field: str, origin: str, preview: str) -> None:
        mapping.append({"field": field, "label": FIELD_LABELS.get(field, field),
                        "content": preview[:160], "origin": origin})

    for element in document.element.body.iterchildren():
        if element.tag == qn("w:p"):
            paragraph = Paragraph(element, document)
            text = paragraph.text.strip()
            if not text:
                continue
            inline = INLINE_KEY_PATTERN.match(text)
            if _is_heading(paragraph):
                heading = text
                target = _match_keyword(text)
                if target == "stages":
                    # 教学过程标题本身不入字段，等待后续表格或段落归类。
                    pending_field = None
                    continue
                pending_field = target
                continue
            if inline:
                key = inline.group("key")
                value = inline.group("value").strip()
                target = _match_keyword(key)
                if target:
                    if target == "stages":
                        unclassified.append({"kind": "text", "heading": key, "text": text})
                        continue
                    _assign(draft, target, value)
                    record(target, f"inline:{key}", value or text)
                    pending_field = target if not value else None
                    heading = key
                    continue
            if pending_field:
                if pending_field in LIST_FIELDS or pending_field == "core_questions":
                    _assign(draft, pending_field, text)
                    record(pending_field, f"paragraph:{heading}", text)
                    continue
                if not _has_scalar_value(draft, pending_field):
                    _assign(draft, pending_field, text)
                    record(pending_field, f"paragraph:{heading}", text)
                    continue
                # 标量字段已有内容：后续段落进入待归类，不悄悄合并。
                unclassified.append({"kind": "text", "heading": heading, "text": text})
                continue
            unclassified.append({"kind": "text", "heading": heading, "text": text})
            continue
        if element.tag == qn("w:tbl"):
            table = Table(element, document)
            stages, _ = _stage_table_to_stages(table, unclassified)
            if stages:
                draft["stages"] = (draft.get("stages") or []) + stages
                record("stages", f"table:{heading or '教学过程表'}", f"{len(stages)} 个环节")
                pending_field = None
                continue
            # Key/value lesson tables may contain every section, mixed unknown
            # rows and more than two columns. Keep every unrecognized cell.
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                if not any(cells):
                    continue
                target = _match_keyword(cells[0]) if len(cells) >= 2 else None
                if target and target != "stages" and cells[1] and not _has_scalar_value(draft, target):
                    _assign(draft, target, cells[1])
                    record(target, f"table:{cells[0]}", cells[1])
                    if any(cells[2:]):
                        unclassified.append({"kind": "table", "heading": cells[0], "text": "｜".join(cells[2:])})
                else:
                    unclassified.append({"kind": "table", "heading": heading, "text": "｜".join(cells)})
            pending_field = None

    seen_parts = set()
    for part in document.part.package.iter_parts():
        content_type = str(getattr(part, "content_type", "") or "")
        partname = str(getattr(part, "partname", "") or "")
        if not content_type.startswith("image/"):
            continue
        if "docProps" in partname or "thumbnail" in partname or partname in seen_parts:
            continue
        blob = getattr(part, "blob", None)
        if not blob:
            continue
        seen_parts.add(partname)
        extension = MIME_EXTENSIONS.get(content_type, "bin")
        unclassified.append({
            "kind": "image", "name": f"image_{len([i for i in unclassified if i['kind'] == 'image']) + 1}.{extension}",
            "content_type": content_type, "data": blob,
        })

    return {"draft": draft, "mapping": mapping, "unclassified": unclassified}


def _has_scalar_value(draft: Dict[str, Any], field: str) -> bool:
    if field == "kd_key":
        return bool((draft.get("key_difficulties") or {}).get("key"))
    if field == "kd_difficult":
        return bool((draft.get("key_difficulties") or {}).get("difficult"))
    return bool(str(draft.get(field) or "").strip())
