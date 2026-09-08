import sqlite3
from pathlib import Path

from backend.app.config import AppConfig
from backend.app.services.question_bank import QuestionBankService


def test_shared_images_follow_questions_without_cross_group_or_bank_leaks(tmp_path: Path):
    service = QuestionBankService(AppConfig(root_dir=tmp_path))
    with service._connect() as conn:
        for qid, bank, group in [("q1", "a", "g"), ("q2", "a", "g"), ("q3", "a", "other"), ("q4", "b", "g")]:
            conn.execute("INSERT INTO questions (question_id, bank_id, group_id, group_key) VALUES (?, ?, ?, ?)", (qid, bank, group, group))
        for bank, group, qid, anchor, filename in [("a", "g", None, "group", "shared.png"), ("a", "g", "q1", "question:q1", "own.png"), ("a", "g", None, "question:missing", "orphan.png"), ("b", "g", None, "group", "other-bank.png")]:
            conn.execute("INSERT INTO images (bank_id, group_key, question_id, content_hash, filename, anchor) VALUES (?, ?, ?, ?, ?, ?)", (bank, group, qid, filename, filename, anchor))
        result = service._images_for_questions(conn, ["q1", "q2", "q3", "q4"])
    names = {qid: [image["url"].rsplit("/", 1)[-1] for image in images] for qid, images in result.items()}
    assert names == {"q1": ["shared.png", "own.png"], "q2": ["shared.png"], "q4": ["other-bank.png"]}
