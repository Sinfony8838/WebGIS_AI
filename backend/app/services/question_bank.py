# -*- coding: utf-8 -*-
"""题库服务：DOCX 导入解析入库、SQLite 持久化与教学检索。

数据布局（均为运行时数据，绝不入库 git）：
- SQLite：``backend/data/state/question_bank.sqlite3``
- 图片文件：``backend/data/uploads/question_banks/<bank_id>/images/<hash>.<ext>``
  通过既有 ``/files`` 机制对外提供（见 ``AppConfig.public_url_for_path``）。

检索策略（可离线降级）：
1. 确定性打分——查询的字符二元组在题干/材料/考点/解析/选项等字段上的
   加权覆盖率，得到 ``relevance ∈ [0, 1]``；
2. 取确定性前 12 名交 LLM 复排为前 5 名并给出选用理由——LLM 只能从
   候选中挑选已存在的题目 ID，任何未知 ID 一律忽略；
3. LLM 不可用时回退确定性排序，``generator=rules``；
4. 自动选用条件：``answer_complete`` 且 ``relevance ≥ 0.65``。
"""
from __future__ import annotations

import json
import hashlib
import re
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from ..config import AppConfig
from .minimax_client import LLMClient
from .question_bank_parser import (
    DocxValidationError,
    QuestionBankDocxParser,
    normalize_bank_filename,
    pair_parsed_banks,
    validate_docx_bytes,
    MAX_FILES_PER_IMPORT,
)

# 确定性候选池与最终推荐数量
CANDIDATE_POOL_SIZE = 12
DEFAULT_RESULT_SIZE = 5
# 自动选用的相关度门槛（确定性打分）
AUTO_SELECT_RELEVANCE = 0.65
# 教学目标匹配权重：题目支撑任意一条目标即按“最高单条命中率”加分，
# 目标句不并入主查询，避免长句稀释考点命中率。
OBJECTIVE_BONUS_WEIGHT = 0.15
# 分页保护
MAX_PAGE_SIZE = 100

# 检索字段的二元组权重（越大越优先命中）
FIELD_WEIGHTS: Tuple[Tuple[str, float], ...] = (
    ("knowledge", 1.2),
    ("section", 1.0),
    ("stem", 1.0),
    ("material", 0.8),
    ("explanation", 0.5),
    ("options", 0.4),
)

_CONTENT_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/bmp": "bmp",
    "image/x-emf": "emf",
    "image/x-wmf": "wmf",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS banks (
    bank_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    base_name TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    import_mode TEXT NOT NULL,
    answer_missing INTEGER NOT NULL DEFAULT 0,
    section_count INTEGER NOT NULL DEFAULT 0,
    group_count INTEGER NOT NULL DEFAULT 0,
    question_count INTEGER NOT NULL DEFAULT 0,
    answer_complete_count INTEGER NOT NULL DEFAULT 0,
    answer_coverage REAL NOT NULL DEFAULT 0,
    image_count INTEGER NOT NULL DEFAULT 0,
    pairing_note_count INTEGER NOT NULL DEFAULT 0,
    stats TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_banks_project ON banks(project_id);

CREATE TABLE IF NOT EXISTS questions (
    question_id TEXT PRIMARY KEY,
    bank_id TEXT NOT NULL,
    group_id TEXT NOT NULL,
    group_key TEXT NOT NULL,
    group_index INTEGER NOT NULL DEFAULT 0,
    question_index INTEGER NOT NULL DEFAULT 0,
    number TEXT NOT NULL DEFAULT '',
    type TEXT NOT NULL DEFAULT 'open',
    is_composite INTEGER NOT NULL DEFAULT 0,
    section_index INTEGER NOT NULL DEFAULT 0,
    section_title TEXT NOT NULL DEFAULT '',
    knowledge_points TEXT NOT NULL DEFAULT '[]',
    year TEXT NOT NULL DEFAULT '',
    region TEXT NOT NULL DEFAULT '',
    source_paper TEXT NOT NULL DEFAULT '',
    material TEXT NOT NULL DEFAULT '',
    stem TEXT NOT NULL DEFAULT '',
    task_text TEXT NOT NULL DEFAULT '',
    options TEXT NOT NULL DEFAULT '[]',
    answer TEXT NOT NULL DEFAULT '',
    answer_letter TEXT NOT NULL DEFAULT '',
    answer_index INTEGER,
    explanation TEXT NOT NULL DEFAULT '',
    sub_questions TEXT NOT NULL DEFAULT '[]',
    answer_complete INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_questions_bank ON questions(bank_id);
CREATE INDEX IF NOT EXISTS idx_questions_group ON questions(bank_id, group_key);

CREATE TABLE IF NOT EXISTS images (
    image_id INTEGER PRIMARY KEY AUTOINCREMENT,
    bank_id TEXT NOT NULL,
    group_key TEXT NOT NULL,
    question_id TEXT,
    content_hash TEXT NOT NULL,
    filename TEXT NOT NULL,
    width INTEGER NOT NULL DEFAULT 0,
    height INTEGER NOT NULL DEFAULT 0,
    content_type TEXT NOT NULL DEFAULT '',
    anchor TEXT NOT NULL DEFAULT 'group',
    order_idx INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_images_bank ON images(bank_id);
CREATE INDEX IF NOT EXISTS idx_images_question ON images(question_id);

CREATE TABLE IF NOT EXISTS groups (
    group_id TEXT PRIMARY KEY,
    bank_id TEXT NOT NULL,
    group_key TEXT NOT NULL,
    group_index INTEGER NOT NULL DEFAULT 0,
    section_index INTEGER NOT NULL DEFAULT 0,
    section_title TEXT NOT NULL DEFAULT '',
    material TEXT NOT NULL DEFAULT '',
    year TEXT NOT NULL DEFAULT '',
    region TEXT NOT NULL DEFAULT '',
    source_paper TEXT NOT NULL DEFAULT '',
    is_composite INTEGER NOT NULL DEFAULT 0,
    tables TEXT NOT NULL DEFAULT '[]',
    pairing_note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_groups_bank ON groups(bank_id);
"""


def _utc_now() -> str:
    from ..models import utc_now

    return utc_now()


def _char_bigrams(text: str) -> Set[str]:
    """中文按字符二元组，拉丁/数字按小写词。过滤空白与标点。"""
    grams: Set[str] = set()
    for chunk in re.findall(r"[0-9A-Za-z]+|[一-鿿]+", text or ""):
        if not chunk[0].isascii():
            for index in range(len(chunk) - 1):
                grams.add(chunk[index : index + 2])
        else:
            grams.add(chunk.lower())
    return grams


def _question_type(question: Dict[str, Any]) -> str:
    if question.get("sub_questions"):
        return "composite"
    if question.get("options"):
        return "choice"
    return "open"


def _knowledge_points(section_title: str) -> List[str]:
    """从考点标题提炼知识点（'考点1 人口分布' → ['人口分布']）。"""
    points = [part.strip() for part in re.split(r"考点\s*\d+\s*[、:：.．]?", section_title or "")]
    return [part for part in points if part]


class QuestionBankService:
    """题库导入、存储与检索。所有公开方法线程安全（进程内 RLock）。"""

    def __init__(
        self,
        config: AppConfig,
        minimax_client: Optional[LLMClient] = None,
        db_path: Optional[Path] = None,
    ):
        self.config = config
        self.minimax = minimax_client
        self._db_path = Path(db_path) if db_path is not None else config.state_dir / "question_bank.sqlite3"
        self._lock = threading.RLock()
        self._initialize()

    # ------------------------------------------------------------------
    # SQLite plumbing（与 auth.py 相同的连接纪律）
    # ------------------------------------------------------------------

    @contextmanager
    def _connect(self):
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self._db_path), timeout=15)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(_SCHEMA)

    # ------------------------------------------------------------------
    # 导入
    # ------------------------------------------------------------------

    def import_files(
        self,
        project_id: str,
        owner_user_id: str,
        files: Sequence[Tuple[str, bytes]],
        progress: Optional[Callable[[str, str], None]] = None,
    ) -> List[Dict[str, Any]]:
        """导入一批 DOCX（原卷版+解析版自动配对），返回题库摘要列表。

        ``files`` 为 ``(filename, raw_bytes)``。任何文件校验失败都会中止整批
        导入——避免半个题库入库后教师误以为导入成功。
        """
        if not files:
            raise DocxValidationError("未选择任何文件。")
        if len(files) > MAX_FILES_PER_IMPORT:
            raise DocxValidationError(f"单次导入最多 {MAX_FILES_PER_IMPORT} 个文件。")

        units: Dict[str, Dict[str, Tuple[str, bytes]]] = {}
        for filename, raw in files:
            validate_docx_bytes(raw, filename)
            base, label = normalize_bank_filename(filename)
            if not base:
                raise DocxValidationError(f"文件名无效：{filename}")
            if label == "unknown":
                raise DocxValidationError(
                    f"无法识别 {filename} 的版本（文件名需包含 原卷版 或 解析版）。"
                )
            bucket = units.setdefault(base, {})
            if label in bucket:
                raise DocxValidationError(f"同一题库「{base}」上传了两份{ '原卷版' if label == 'original' else '解析版' }。")
            bucket[label] = (filename, raw)

        if progress:
            progress("validate", f"已校验 {len(files)} 个文件，识别出 {len(units)} 套题库。")

        banks: List[Dict[str, Any]] = []
        for position, (base, bucket) in enumerate(sorted(units.items()), start=1):
            if progress:
                progress("parse", f"正在解析题库 {position}/{len(units)}：{base}")
            banks.append(self._import_unit(project_id, owner_user_id, base, bucket))
        return banks

    def _import_unit(
        self,
        project_id: str,
        owner_user_id: str,
        base_name: str,
        bucket: Dict[str, Tuple[str, bytes]],
    ) -> Dict[str, Any]:
        original: Optional[Any] = None
        analysis: Optional[Any] = None
        if "original" in bucket:
            filename, raw = bucket["original"]
            original = QuestionBankDocxParser(filename, raw).parse()
        if "analysis" in bucket:
            filename, raw = bucket["analysis"]
            analysis = QuestionBankDocxParser(filename, raw).parse()

        if original is None and analysis is None:
            raise DocxValidationError(f"题库「{base_name}」没有可解析的文件。")

        fingerprint = ";".join(
            sorted(
                f"{label}:{hashlib.sha256(raw).hexdigest()}"
                for label, (_name, raw) in bucket.items()
            )
        )

        # 重复上传：同项目同指纹直接复用现有题库，不重复入库。
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM banks WHERE project_id = ? AND fingerprint = ?",
                (project_id, fingerprint),
            ).fetchone()
        if row is not None:
            summary = self.get_bank(str(row["bank_id"]))
            summary["duplicate"] = True
            summary["import_note"] = "题库内容与现有记录完全一致，已复用现有题库，未重复导入。"
            return summary

        if original is not None and analysis is not None:
            import_mode = "paired"
            title = original.title or analysis.title or base_name
        elif analysis is not None:
            import_mode = "analysis_only"
            title = analysis.title or base_name
        else:
            import_mode = "original_only"
            title = original.title or base_name

        groups = pair_parsed_banks(original, analysis)

        bank_id = f"qb_{secrets.token_hex(6)}"
        image_dir = self.config.uploads_dir / "question_banks" / bank_id / "images"
        written_hashes: Dict[str, str] = {}  # content_hash -> filename

        def persist_image(image: Dict[str, Any]) -> Tuple[str, str]:
            content_hash = str(image.get("content_hash") or "")
            blob = image.get("blob") or b""
            if content_hash in written_hashes:
                return content_hash, written_hashes[content_hash]
            ext = _CONTENT_EXT.get(str(image.get("content_type") or ""), "bin")
            filename = f"{content_hash}.{ext}"
            if blob:
                image_dir.mkdir(parents=True, exist_ok=True)
                (image_dir / filename).write_bytes(blob)
            written_hashes[content_hash] = filename
            return content_hash, filename

        section_titles: Dict[int, str] = {}
        question_rows: List[Tuple[Any, ...]] = []
        group_rows: List[Tuple[Any, ...]] = []
        image_rows: List[Tuple[Any, ...]] = []

        for group_index, group in enumerate(groups):
            section_title = str(group.get("section_title") or "")
            section_number = int(group.get("section_index") or 0)
            if section_title and section_number:
                section_titles.setdefault(section_number, section_title)
            group_id = f"{bank_id}_{group.get('group_key')}"
            group_rows.append(
                (
                    group_id,
                    bank_id,
                    str(group.get("group_key") or ""),
                    group_index,
                    int(group.get("section_index") or 0),
                    section_title,
                    str(group.get("material") or ""),
                    str(group.get("year") or ""),
                    str(group.get("region") or ""),
                    str(group.get("source_paper") or ""),
                    1 if group.get("is_composite") else 0,
                    json.dumps(group.get("tables") or [], ensure_ascii=False),
                    str(group.get("pairing_note") or ""),
                )
            )
            for question_index, question in enumerate(group.get("questions") or []):
                question_id = f"{bank_id}_{group.get('group_key')}_{question.get('question_key') or question_index + 1}"
                question_rows.append(
                    (
                        question_id,
                        bank_id,
                        group_id,
                        str(group.get("group_key") or ""),
                        group_index,
                        question_index,
                        str(question.get("number") or ""),
                        _question_type(question),
                        1 if group.get("is_composite") else 0,
                        int(group.get("section_index") or 0),
                        section_title,
                        json.dumps(_knowledge_points(section_title), ensure_ascii=False),
                        str(group.get("year") or ""),
                        str(group.get("region") or ""),
                        str(group.get("source_paper") or ""),
                        str(group.get("material") or ""),
                        str(question.get("stem") or ""),
                        str(question.get("task_text") or ""),
                        json.dumps(question.get("options") or [], ensure_ascii=False),
                        str(question.get("answer") or ""),
                        str(question.get("answer_letter") or ""),
                        question.get("answer_index"),
                        str(question.get("explanation") or ""),
                        json.dumps(question.get("sub_questions") or [], ensure_ascii=False),
                        1 if question.get("answer_complete") else 0,
                    )
                )
            for image in group.get("images") or []:
                anchor = str(image.get("anchor") or "group")
                question_id: Optional[str] = None
                if anchor.startswith("question:"):
                    anchor_key = anchor.split(":", 1)[1]
                    questions = group.get("questions") or []
                    match = next(
                        (
                            index
                            for index, item in enumerate(questions)
                            if str(item.get("question_key") or f"q{item.get('number')}") == anchor_key
                        ),
                        None,
                    )
                    if match is not None:
                        question_id = f"{bank_id}_{group.get('group_key')}_{questions[match].get('question_key') or match + 1}"
                content_hash, filename = persist_image(image)
                image_rows.append(
                    (
                        bank_id,
                        str(group.get("group_key") or ""),
                        question_id,
                        content_hash,
                        filename,
                        int(image.get("width") or 0),
                        int(image.get("height") or 0),
                        str(image.get("content_type") or ""),
                        anchor,
                        int(image.get("order") or 0),
                    )
                )

        question_count = len(question_rows)
        answer_complete_count = sum(1 for row in question_rows if row[-1])
        coverage = round(answer_complete_count / question_count, 4) if question_count else 0.0
        sections = [
            {
                "section_index": section_number,
                "title": title,
                "question_count": sum(1 for row in question_rows if row[9] == section_number),
            }
            for section_number, title in sorted(section_titles.items())
        ]
        stats = {
            "sections": sections,
            "pairing_notes": [
                {"group_key": str(group.get("group_key")), "note": str(group.get("pairing_note") or "")}
                for group in groups
                if str(group.get("pairing_note") or "")
            ],
            "unbound_image_count": sum(
                len(getattr(bank, "unbound_images", []) or [])
                for bank in (original, analysis)
                if bank is not None
            ),
        }
        now = _utc_now()
        with self._lock, self._connect() as connection:
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    INSERT INTO banks (
                        bank_id, project_id, owner_user_id, title, base_name, fingerprint,
                        import_mode, answer_missing, section_count, group_count, question_count,
                        answer_complete_count, answer_coverage, image_count, pairing_note_count,
                        stats, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        bank_id,
                        project_id,
                        owner_user_id,
                        title,
                        base_name,
                        fingerprint,
                        import_mode,
                        1 if import_mode == "original_only" else 0,
                        len(sections),
                        len(groups),
                        question_count,
                        answer_complete_count,
                        coverage,
                        len(image_rows),
                        len(stats["pairing_notes"]),
                        json.dumps(stats, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
                connection.executemany(
                    "INSERT INTO groups VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", group_rows
                )
                connection.executemany(
                    "INSERT INTO questions ("
                    "question_id, bank_id, group_id, group_key, group_index, question_index, number, type,"
                    "is_composite, section_index, section_title, knowledge_points, year, region, source_paper,"
                    "material, stem, task_text, options, answer, answer_letter, answer_index, explanation,"
                    "sub_questions, answer_complete) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    question_rows,
                )
                connection.executemany(
                    "INSERT INTO images ("
                    "bank_id, group_key, question_id, content_hash, filename, width, height, content_type,"
                    "anchor, order_idx) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    image_rows,
                )

        return self.get_bank(bank_id)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def get_bank(self, bank_id: str) -> Dict[str, Any]:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT * FROM banks WHERE bank_id = ?", (bank_id,)).fetchone()
            if row is None:
                raise KeyError(f"Unknown question bank: {bank_id}")
            return self._bank_summary(row)

    def list_banks(self, project_id: str) -> List[Dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM banks WHERE project_id = ? ORDER BY created_at DESC, bank_id",
                (project_id,),
            ).fetchall()
        return [self._bank_summary(row) for row in rows]

    def delete_bank(self, bank_id: str) -> Dict[str, Any]:
        bank = self.get_bank(bank_id)
        with self._lock, self._connect() as connection:
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                for table in ("images", "questions", "groups", "banks"):
                    connection.execute(f"DELETE FROM {table} WHERE bank_id = ?", (bank_id,))
        bank_dir = self.config.uploads_dir / "question_banks" / bank_id
        if bank_dir.exists():
            import shutil

            shutil.rmtree(bank_dir, ignore_errors=True)
        return {"status": "success", "bank_id": bank_id, "title": bank.get("title", "")}

    def list_questions(
        self,
        bank_id: str,
        section: str = "",
        qtype: str = "",
        answer_complete: Optional[bool] = None,
        search: str = "",
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        self.get_bank(bank_id)  # 404/KeyError when unknown
        page = max(1, int(page or 1))
        page_size = min(MAX_PAGE_SIZE, max(1, int(page_size or 20)))
        clauses = ["bank_id = ?"]
        params: List[Any] = [bank_id]
        if section.strip():
            clauses.append("section_title LIKE ?")
            params.append(f"%{section.strip()}%")
        if qtype.strip() in {"choice", "composite", "open"}:
            clauses.append("type = ?")
            params.append(qtype.strip())
        if answer_complete is True:
            clauses.append("answer_complete = 1")
        elif answer_complete is False:
            clauses.append("answer_complete = 0")
        # 关键词过滤必须在 LIMIT/OFFSET 之前作用于全量候选——否则只在
        # 当前页内过滤，跨页检索会漏掉大部分匹配题。
        if search.strip():
            grams = _char_bigrams(search)
            with self._lock, self._connect() as connection:
                candidates = connection.execute(
                    f"SELECT * FROM questions WHERE {' AND '.join(clauses)} ORDER BY group_index, question_index",
                    params,
                ).fetchall()
            matched_rows = [
                row
                for row in candidates
                if grams
                & _char_bigrams(
                    " ".join(
                        [
                            str(row["material"] or ""),
                            str(row["stem"] or ""),
                            str(row["task_text"] or ""),
                            str(row["section_title"] or ""),
                            " ".join(str(option) for option in json.loads(str(row["options"]) or "[]")),
                        ]
                    )
                )
            ]
            total = len(matched_rows)
            page_rows = matched_rows[(page - 1) * page_size : (page - 1) * page_size + page_size]
            with self._lock, self._connect() as connection:
                images_by_question = self._images_for_questions(
                    connection, [str(row["question_id"]) for row in page_rows]
                )
            items = [self._question_payload(row, images_by_question) for row in page_rows]
            return {
                "status": "success",
                "bank_id": bank_id,
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
            }
        where = " AND ".join(clauses)
        with self._lock, self._connect() as connection:
            total = int(
                connection.execute(f"SELECT COUNT(*) FROM questions WHERE {where}", params).fetchone()[0]
            )
            rows = connection.execute(
                f"SELECT * FROM questions WHERE {where} ORDER BY group_index, question_index LIMIT ? OFFSET ?",
                (*params, page_size, (page - 1) * page_size),
            ).fetchall()
            images_by_question = self._images_for_questions(connection, [str(row["question_id"]) for row in rows])
        items = [self._question_payload(row, images_by_question) for row in rows]
        return {
            "status": "success",
            "bank_id": bank_id,
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def get_group(self, bank_id: str, group_key: str) -> Dict[str, Any]:
        self.get_bank(bank_id)
        group_id = f"{bank_id}_{group_key}"
        with self._lock, self._connect() as connection:
            group = connection.execute(
                "SELECT * FROM groups WHERE bank_id = ? AND group_key = ?",
                (bank_id, group_key),
            ).fetchone()
            if group is None:
                raise KeyError(f"Unknown question group: {group_key}")
            rows = connection.execute(
                "SELECT * FROM questions WHERE bank_id = ? AND group_key = ? ORDER BY question_index",
                (bank_id, group_key),
            ).fetchall()
            images = connection.execute(
                "SELECT * FROM images WHERE bank_id = ? AND group_key = ? ORDER BY order_idx",
                (bank_id, group_key),
            ).fetchall()
            images_by_question = self._images_for_questions(connection, [str(row["question_id"]) for row in rows])
        return {
            "status": "success",
            "group": {
                "group_id": group_id,
                "bank_id": bank_id,
                "group_key": group_key,
                "group_index": int(group["group_index"]),
                "section_index": int(group["section_index"]),
                "section_title": str(group["section_title"]),
                "material": str(group["material"]),
                "year": str(group["year"]),
                "region": str(group["region"]),
                "source_paper": str(group["source_paper"]),
                "is_composite": bool(group["is_composite"]),
                "tables": json.loads(str(group["tables"]) or "[]"),
                "pairing_note": str(group["pairing_note"]),
                "images": [self._image_payload(image) for image in images],
                "questions": [self._question_payload(row, images_by_question) for row in rows],
            },
        }

    def get_questions_by_ids(
        self,
        question_ids: Sequence[str],
        project_id: str = "",
    ) -> List[Dict[str, Any]]:
        """按 ID 批量取题（教案快照、候选替换等场景）。

        ``project_id`` 用于服务层的归属校验，避免调用方绕过题库列表/检索
        接口后，仅凭另一个项目的 ``question_id`` 把私有题目复制进当前教案。
        未知或不属于当前项目的 ID 均静默跳过。
        """
        if not question_ids:
            return []
        ids = [str(item) for item in question_ids]
        with self._lock, self._connect() as connection:
            placeholders = ",".join("?" for _ in ids)
            if project_id:
                rows = connection.execute(
                    f"""
                    SELECT q.* FROM questions q
                    JOIN banks b ON q.bank_id = b.bank_id
                    WHERE q.question_id IN ({placeholders}) AND b.project_id = ?
                    ORDER BY q.bank_id, q.group_index, q.question_index
                    """,
                    [*ids, project_id],
                ).fetchall()
            else:
                rows = connection.execute(
                    f"SELECT * FROM questions WHERE question_id IN ({placeholders}) ORDER BY bank_id, group_index, question_index",
                    ids,
                ).fetchall()
            images_by_question = self._images_for_questions(connection, [str(row["question_id"]) for row in rows])
        return [self._question_payload(row, images_by_question) for row in rows]

    def snapshot_question(self, question_id: str, project_id: str = "") -> Dict[str, Any]:
        """从题库取单题并压平成教案/模拟测试共用的不可变题目快照。"""
        items = self.get_questions_by_ids([question_id], project_id=project_id)
        if not items:
            raise KeyError(f"Unknown question: {question_id}")
        return self.normalize_snapshot_question(items[0])

    @staticmethod
    def normalize_snapshot_question(question: Dict[str, Any]) -> Dict[str, Any]:
        """把题库检索结果压平成教案环节内的题目快照格式（含材料/题图/答案/解析）。"""
        return {
            "question_id": str(question.get("question_id") or ""),
            "type": str(question.get("type") or "open"),
            "source": "question_bank",
            "text": str(question.get("stem") or question.get("text") or ""),
            "task_text": str(question.get("task_text") or ""),
            "material": str(question.get("material") or ""),
            "options": [str(item) for item in question.get("options") or []],
            "answer": str(question.get("answer") or ""),
            "answer_letter": str(question.get("answer_letter") or ""),
            "answer_index": question.get("answer_index") if isinstance(question.get("answer_index"), int) else None,
            "explanation": str(question.get("explanation") or ""),
            "sub_questions": [
                {
                    "index": str(sub.get("index") or index + 1),
                    "text": str(sub.get("text") or ""),
                    "options": [str(item) for item in sub.get("options") or []],
                    "answer": str(sub.get("answer") or ""),
                    "answer_index": sub.get("answer_index") if isinstance(sub.get("answer_index"), int) else None,
                    "explanation": str(sub.get("explanation") or ""),
                }
                for index, sub in enumerate(question.get("sub_questions") or [])
                if isinstance(sub, dict)
            ],
            "images": [
                {
                    "url": str(image.get("url") or ""),
                    "width": int(image.get("width") or 0),
                    "height": int(image.get("height") or 0),
                    "content_type": str(image.get("content_type") or ""),
                    "anchor": str(image.get("anchor") or "group"),
                    "order": int(image.get("order") or 0),
                }
                for image in question.get("images") or []
                if isinstance(image, dict)
            ],
            "answer_complete": bool(question.get("answer_complete")),
            "knowledge_points": [str(item) for item in question.get("knowledge_points") or []],
            "year": str(question.get("year") or ""),
            "region": str(question.get("region") or ""),
            "source_paper": str(question.get("source_paper") or ""),
            "bank_id": str(question.get("bank_id") or ""),
            "group_key": str(question.get("group_key") or ""),
            "number": str(question.get("number") or ""),
            "suggested_seconds": 120,
            "expected_points": [str(item) for item in question.get("knowledge_points") or []],
            "misconceptions": [],
            "explanation_source": "official",
        }

    @staticmethod
    def build_manual_question(manual: Dict[str, Any], stage_id: str, index: int) -> Dict[str, Any]:
        """把教师手动录入的题目规范化成题目快照格式（来源标记 teacher_manual）。"""
        text = str(manual.get("text") or "").strip()
        if not text:
            raise ValueError("手动题目不能没有题干。")
        options = [str(item) for item in manual.get("options") or [] if str(item).strip()]
        sub_questions = [
            {
                "index": str(sub.get("index") or sub_index + 1),
                "text": str(sub.get("text") or ""),
                "options": [str(item) for item in sub.get("options") or []],
                "answer": str(sub.get("answer") or ""),
                "answer_index": sub.get("answer_index") if isinstance(sub.get("answer_index"), int) else None,
                "explanation": str(sub.get("explanation") or ""),
            }
            for sub_index, sub in enumerate(manual.get("sub_questions") or [])
            if isinstance(sub, dict)
        ]
        qtype = str(manual.get("type") or "").strip()
        if sub_questions:
            qtype = "composite"
        elif options:
            qtype = "choice"
        elif qtype not in {"choice", "open", "composite"}:
            qtype = "open"
        return {
            "question_id": str(manual.get("question_id") or f"{stage_id}m{index}"),
            "type": qtype,
            "source": "teacher_manual",
            "text": text,
            "task_text": str(manual.get("task_text") or ""),
            "material": str(manual.get("material") or ""),
            "options": options,
            "answer": str(manual.get("answer") or ""),
            "answer_letter": str(manual.get("answer_letter") or ""),
            "answer_index": manual.get("answer_index") if isinstance(manual.get("answer_index"), int) else None,
            "explanation": str(manual.get("explanation") or ""),
            "sub_questions": sub_questions,
            "images": [
                {
                    "url": str(image.get("url") or ""),
                    "width": int(image.get("width") or 0),
                    "height": int(image.get("height") or 0),
                    "content_type": str(image.get("content_type") or ""),
                    "anchor": str(image.get("anchor") or "group"),
                    "order": int(image.get("order") or 0),
                }
                for image in manual.get("images") or []
                if isinstance(image, dict)
            ],
            "answer_complete": bool(str(manual.get("answer") or "").strip() or (
                isinstance(manual.get("answer_index"), int)
            ) or all(str(sub.get("answer") or "").strip() for sub in sub_questions)),
            "knowledge_points": [str(item) for item in manual.get("knowledge_points") or []],
            "year": "", "region": "", "source_paper": "",
            "bank_id": "", "group_key": "", "number": str(manual.get("number") or ""),
            "suggested_seconds": int(manual.get("suggested_seconds") or 120),
            "expected_points": [str(item) for item in manual.get("expected_points") or []],
            "misconceptions": [
                {"tag": str(item.get("tag") or ""), "description": str(item.get("description") or "")}
                for item in manual.get("misconceptions") or [] if isinstance(item, dict)
            ],
            "explanation_source": "teacher",
        }

    # ------------------------------------------------------------------
    # 检索
    # ------------------------------------------------------------------

    def search(
        self,
        project_id: str = "",
        bank_ids: Optional[Sequence[str]] = None,
        topic: str = "",
        knowledge: str = "",
        objectives: Optional[Sequence[str]] = None,
        qtype: str = "",
        exclude_ids: Optional[Sequence[str]] = None,
        limit: int = DEFAULT_RESULT_SIZE,
        use_llm: bool = True,
    ) -> Dict[str, Any]:
        objectives = [str(item).strip() for item in objectives or [] if str(item).strip()]
        query_text = " ".join(part for part in [topic.strip(), knowledge.strip(), *objectives] if part)
        exclude = {str(item) for item in (exclude_ids or [])}
        limit = max(1, min(10, int(limit or DEFAULT_RESULT_SIZE)))

        candidates = self._scored_candidates(
            project_id=project_id,
            bank_ids=bank_ids,
            topic=topic.strip(),
            knowledge=knowledge.strip(),
            objectives=objectives,
            qtype=qtype,
            exclude=exclude,
        )

        if not candidates:
            return {
                "status": "success",
                "items": [],
                "candidates_count": 0,
                "generator": "rules",
                "query": {"topic": topic.strip(), "knowledge": knowledge.strip(), "objectives": objectives},
            }

        pool = candidates[:CANDIDATE_POOL_SIZE]
        ranked, reasons, generator = (self._rerank(query_text, pool, limit)
                                      if use_llm else (pool[:limit], {}, "rules"))
        items = []
        for question in ranked:
            item = dict(question)
            item.pop("_score_fields", None)
            item["auto_selectable"] = bool(item.get("answer_complete") and item.get("relevance", 0) >= AUTO_SELECT_RELEVANCE)
            item["selection_reason"] = reasons.get(str(item["question_id"]), "")
            items.append(item)
        return {
            "status": "success",
            "items": items,
            "candidates_count": len(candidates),
            "generator": generator,
            "query": {"topic": topic.strip(), "knowledge": knowledge.strip(), "objectives": objectives},
        }

    def _scored_candidates(
        self,
        project_id: str,
        bank_ids: Optional[Sequence[str]],
        topic: str,
        knowledge: str,
        objectives: Sequence[str],
        qtype: str,
        exclude: Set[str],
    ) -> List[Dict[str, Any]]:
        """考点/知识点命中为主，教学目标按“最高单条命中”加分。"""
        base_grams = _char_bigrams(" ".join(part for part in [topic, knowledge] if part))
        objective_gram_sets = [
            grams for grams in (_char_bigrams(item) for item in objectives) if grams
        ]
        if not base_grams and objective_gram_sets:
            # 只有教学目标时退化为目标并集，避免空查询直接返回空结果
            base_grams = set().union(*objective_gram_sets)
            objective_gram_sets = []
        if not base_grams:
            return []

        with self._lock, self._connect() as connection:
            if bank_ids:
                placeholders = ",".join("?" for _ in bank_ids)
                rows = connection.execute(
                    f"SELECT * FROM questions WHERE bank_id IN ({placeholders})",
                    [str(item) for item in bank_ids],
                ).fetchall()
            elif project_id:
                rows = connection.execute(
                    """
                    SELECT q.* FROM questions q JOIN banks b ON q.bank_id = b.bank_id
                    WHERE b.project_id = ?
                    """,
                    (project_id,),
                ).fetchall()
            else:
                rows = connection.execute("SELECT * FROM questions").fetchall()
            images_by_question = self._images_for_questions(
                connection, [str(row["question_id"]) for row in rows]
            )

        scored: List[Dict[str, Any]] = []
        for row in rows:
            question_id = str(row["question_id"])
            if question_id in exclude:
                continue
            if qtype.strip() in {"choice", "composite", "open"} and str(row["type"]) != qtype.strip():
                continue
            payload = self._question_payload(row, images_by_question)
            fields = {
                "knowledge": " ".join(payload["knowledge_points"]),
                "section": payload["section_title"],
                "stem": f"{payload['stem']} {payload['task_text']}",
                "material": payload["material"],
                "explanation": payload["explanation"],
                "options": " ".join(payload["options"]),
            }
            # 每个查询二元组取其命中的最高权重字段，覆盖率 = 加权命中 / 查询二元组数
            field_gram_sets = {
                field: _char_bigrams(fields[field]) for field, _ in FIELD_WEIGHTS
            }
            matched: Dict[str, float] = {}
            for field, weight in FIELD_WEIGHTS:
                for gram in field_gram_sets[field] & base_grams:
                    if weight > matched.get(gram, 0.0):
                        matched[gram] = weight
            relevance = sum(matched.values()) / len(base_grams)
            # 教学目标匹配：支撑任意一条目标即加分（单条单独计分取最高）
            if objective_gram_sets:
                best_objective = 0.0
                for grams in objective_gram_sets:
                    obj_matched: Dict[str, float] = {}
                    for field, weight in FIELD_WEIGHTS:
                        for gram in field_gram_sets[field] & grams:
                            if weight > obj_matched.get(gram, 0.0):
                                obj_matched[gram] = weight
                    if grams:
                        best_objective = max(best_objective, sum(obj_matched.values()) / len(grams))
                relevance += OBJECTIVE_BONUS_WEIGHT * best_objective
            relevance = min(1.0, round(relevance, 4))
            # 考点/知识点精确命中给确定性加分（封顶 1.0）
            if topic and (
                any(topic in point for point in payload["knowledge_points"])
                or topic in payload["section_title"]
            ):
                relevance = min(1.0, relevance + 0.1)
            payload["relevance"] = relevance
            scored.append(payload)

        scored.sort(key=lambda item: (-item["relevance"], not bool(item["answer_complete"]), str(item["question_id"])))
        return scored

    def _rerank(
        self, query_text: str, pool: List[Dict[str, Any]], limit: int
    ) -> Tuple[List[Dict[str, Any]], Dict[str, str], str]:
        """LLM 复排前 N 名；失败时确定性排序降级。"""
        ranked = pool[:limit]
        if self.minimax is None or not self.config.llm_enabled():
            return ranked, {}, "rules"
        try:
            ordered_ids, reasons = self._llm_rerank(query_text, pool, limit)
        except Exception:
            return ranked, {}, "rules"
        by_id = {str(item["question_id"]): item for item in pool}
        ordered = [by_id[qid] for qid in ordered_ids if qid in by_id]
        # LLM 少选或漏选的用确定性顺序补齐
        for item in ranked:
            if len(ordered) >= limit:
                break
            if item not in ordered:
                ordered.append(item)
        return ordered[:limit], reasons, "minimax"

    def _llm_rerank(
        self, query_text: str, pool: List[Dict[str, Any]], limit: int
    ) -> Tuple[List[str], Dict[str, str]]:
        lines = []
        for item in pool:
            stem = (item.get("stem") or item.get("task_text") or "")[:160]
            material = str(item.get("material") or "")[:200]
            lines.append(
                "- ID: {qid} | 考点: {section} | {year} {region} {source} | 题型: {qtype} | 答案完备: {complete} | 题干: {stem} | 材料: {material}".format(
                    qid=item["question_id"],
                    section=item["section_title"],
                    year=item.get("year", ""),
                    region=item.get("region", ""),
                    source=item.get("source_paper", ""),
                    qtype=item.get("type", ""),
                    complete="是" if item.get("answer_complete") else "否",
                    stem=stem,
                    material=material,
                )
            )
        prompt = (
            "你是地理教研员，正在为教学目标挑选最匹配的高考真题。\n"
            f"教学检索需求：{query_text}\n\n"
            "候选题目（只能从中选择，不得编造新 ID）：\n" + "\n".join(lines) + "\n\n"
            f"请选出最匹配的至多 {limit} 道题，按匹配度从高到低排序，"
            '仅输出 JSON：{"selection": [{"question_id": "...", "reason": "20字以内选用理由"}]}'
        )
        raw = self.minimax.chat_completion(
            [{"role": "user", "content": prompt}],
            temperature=0.1,
            timeout=30.0,
        )
        match = re.search(r"\{.*\}", raw or "", re.DOTALL)
        if not match:
            raise ValueError("LLM rerank response is not JSON")
        parsed = json.loads(match.group(0))
        valid_ids = {str(item["question_id"]) for item in pool}
        ordered: List[str] = []
        reasons: Dict[str, str] = {}
        for entry in parsed.get("selection") or []:
            if not isinstance(entry, dict):
                continue
            qid = str(entry.get("question_id") or "")
            if qid in valid_ids and qid not in ordered:
                ordered.append(qid)
                reasons[qid] = str(entry.get("reason") or "")[:120]
        if not ordered:
            raise ValueError("LLM rerank selected no valid question")
        return ordered, reasons

    # ------------------------------------------------------------------
    # 序列化
    # ------------------------------------------------------------------

    def _bank_summary(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "bank_id": str(row["bank_id"]),
            "project_id": str(row["project_id"]),
            "owner_user_id": str(row["owner_user_id"] or ""),
            "title": str(row["title"]),
            "base_name": str(row["base_name"]),
            "import_mode": str(row["import_mode"]),
            "answer_missing": bool(row["answer_missing"]),
            "section_count": int(row["section_count"]),
            "group_count": int(row["group_count"]),
            "question_count": int(row["question_count"]),
            "answer_complete_count": int(row["answer_complete_count"]),
            "answer_coverage": float(row["answer_coverage"]),
            "image_count": int(row["image_count"]),
            "pairing_note_count": int(row["pairing_note_count"]),
            "stats": json.loads(str(row["stats"]) or "{}"),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    def _question_payload(self, row: sqlite3.Row, images_by_question: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        question_id = str(row["question_id"])
        return {
            "question_id": question_id,
            "bank_id": str(row["bank_id"]),
            "group_id": str(row["group_id"]),
            "group_key": str(row["group_key"]),
            "number": str(row["number"]),
            "type": str(row["type"]),
            "is_composite": bool(row["is_composite"]),
            "section_index": int(row["section_index"]),
            "section_title": str(row["section_title"]),
            "knowledge_points": json.loads(str(row["knowledge_points"]) or "[]"),
            "year": str(row["year"]),
            "region": str(row["region"]),
            "source_paper": str(row["source_paper"]),
            "material": str(row["material"]),
            "stem": str(row["stem"]),
            "task_text": str(row["task_text"]),
            "options": json.loads(str(row["options"]) or "[]"),
            "answer": str(row["answer"]),
            "answer_letter": str(row["answer_letter"]),
            "answer_index": row["answer_index"],
            "explanation": str(row["explanation"]),
            "sub_questions": json.loads(str(row["sub_questions"]) or "[]"),
            "answer_complete": bool(row["answer_complete"]),
            "images": images_by_question.get(question_id, []),
            "source": "question_bank",
            "explanation_source": "official",
        }

    def _image_payload(self, row: sqlite3.Row) -> Dict[str, Any]:
        path = self.config.uploads_dir / "question_banks" / str(row["bank_id"]) / "images" / str(row["filename"])
        url = ""
        try:
            url = self.config.public_url_for_path(path)
        except ValueError:
            url = ""
        return {
            "url": url,
            "width": int(row["width"]),
            "height": int(row["height"]),
            "content_type": str(row["content_type"]),
            "anchor": str(row["anchor"]),
            "order": int(row["order_idx"]),
            "group_key": str(row["group_key"]),
            "question_id": str(row["question_id"]) if row["question_id"] else "",
        }

    def _images_for_questions(
        self, connection: sqlite3.Connection, question_ids: List[str]
    ) -> Dict[str, List[Dict[str, Any]]]:
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        if not question_ids:
            return grouped
        placeholders = ",".join("?" for _ in question_ids)
        rows = connection.execute(
            f"""SELECT i.*, q.question_id AS target_question_id
                FROM questions q JOIN images i ON i.bank_id = q.bank_id AND (
                    i.question_id = q.question_id OR (
                        (i.question_id IS NULL OR i.question_id = '')
                        AND i.anchor = 'group' AND i.group_key = q.group_key
                    )
                )
                WHERE q.question_id IN ({placeholders}) ORDER BY i.order_idx, i.image_id""",
            question_ids,
        ).fetchall()
        for row in rows:
            grouped.setdefault(str(row["target_question_id"]), []).append(self._image_payload(row))
        return grouped
