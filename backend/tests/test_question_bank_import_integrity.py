from __future__ import annotations

import hashlib
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.app.config import AppConfig
from backend.app.services.question_bank import QuestionBankService


def service_at(root: Path) -> QuestionBankService:
    config = AppConfig(root_dir=root)
    config.minimax_api_key = ""
    config.minimax_token_plan_key = ""
    return QuestionBankService(config)


def fixture_groups():
    blob = b"synthetic image bytes"
    return [{
        "group_key": "group_1", "section_index": 1, "section_title": "Population",
        "questions": [{"question_key": "q1", "stem": "Fixture question", "answer": "Fixture answer", "answer_complete": True}],
        "images": [{"content_hash": hashlib.sha256(blob).hexdigest(), "blob": blob, "content_type": "image/png"}],
    }]


def run_import(service: QuestionBankService, project_id: str = "fixture_project"):
    return service._import_unit(project_id, "fixture_teacher", "fixture_bank", {"analysis": ("fixture.docx", b"same fixture document")})


@pytest.fixture
def parsed_document():
    parsed = SimpleNamespace(title="Fixture bank", unbound_images=[])
    with patch("backend.app.services.question_bank.run_document", return_value=parsed):
        yield


def test_parallel_imports_share_one_bank_across_service_instances(tmp_path, parsed_document):
    services = [service_at(tmp_path) for _ in range(4)]
    barrier = threading.Barrier(len(services))

    def paired(*args):
        # All requests have passed the nonauthoritative fast check before
        # any one enters the final write transaction.
        barrier.wait(timeout=10)
        return fixture_groups()

    with patch("backend.app.services.question_bank.pair_parsed_banks", side_effect=paired):
        with ThreadPoolExecutor(max_workers=len(services)) as executor:
            results = list(executor.map(run_import, services))

    assert len({row["bank_id"] for row in results}) == 1
    assert sum(bool(row.get("duplicate")) for row in results) == 3
    assert len(services[0].list_banks("fixture_project")) == 1
    root = services[0].config.uploads_dir / "question_banks"
    assert len(list(root.iterdir())) == 1
    assert len(list(root.glob("*/images/*"))) == 1


def test_matching_content_in_different_projects_is_not_deduplicated(tmp_path, parsed_document):
    service = service_at(tmp_path)
    with patch("backend.app.services.question_bank.pair_parsed_banks", side_effect=lambda *a: fixture_groups()):
        first = run_import(service, "first_project")
        second = run_import(service, "second_project")
    assert first["bank_id"] != second["bank_id"]
    assert len(service.list_banks("first_project")) == len(service.list_banks("second_project")) == 1


def test_historical_duplicates_and_image_references_are_preserved(tmp_path, parsed_document):
    service = service_at(tmp_path)
    with patch("backend.app.services.question_bank.pair_parsed_banks", side_effect=lambda *a: fixture_groups()):
        first = run_import(service)
        with service._connect() as connection, connection:
            row = dict(connection.execute("SELECT * FROM banks WHERE bank_id = ?", (first["bank_id"],)).fetchone())
            row.update(bank_id="qb_historical", created_at="2000-01-01T00:00:00+00:00")
            columns = ",".join(row)
            connection.execute(f"INSERT INTO banks ({columns}) VALUES ({','.join('?' for _ in row)})", tuple(row.values()))
        images_before = {path: path.read_bytes() for path in service.config.uploads_dir.glob("question_banks/*/images/*")}
        result = run_import(service)
    assert result["duplicate"] is True
    assert result["bank_id"] == "qb_historical"
    assert {row["bank_id"] for row in service.list_banks("fixture_project")} == {first["bank_id"], "qb_historical"}
    assert {path: path.read_bytes() for path in images_before} == images_before


def test_database_failure_rolls_back_only_current_import_files(tmp_path, parsed_document):
    service = service_at(tmp_path)
    existing = service.config.uploads_dir / "question_banks" / "existing_bank" / "images" / "keep.png"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"keep historical file")
    with service._connect() as connection, connection:
        connection.execute("CREATE TRIGGER fixture_fail BEFORE INSERT ON questions BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END")
    with patch("backend.app.services.question_bank.pair_parsed_banks", side_effect=lambda *a: fixture_groups()):
        with pytest.raises(sqlite3.IntegrityError, match="synthetic failure"):
            run_import(service)
    assert service.list_banks("fixture_project") == []
    assert existing.read_bytes() == b"keep historical file"
    assert list(existing.parents[2].iterdir()) == [existing.parents[1]]


def test_image_write_failure_rolls_back_metadata_and_partial_file(tmp_path, parsed_document):
    service = service_at(tmp_path)
    real_write = Path.write_bytes

    def fail_image(path, data):
        if path.suffix == ".png":
            real_write(path, b"partial")
            raise OSError("synthetic full disk")
        return real_write(path, data)

    with patch("backend.app.services.question_bank.pair_parsed_banks", side_effect=lambda *a: fixture_groups()), patch.object(Path, "write_bytes", fail_image):
        with pytest.raises(OSError, match="synthetic full disk"):
            run_import(service)
    assert service.list_banks("fixture_project") == []
    assert list((service.config.uploads_dir / "question_banks").iterdir()) == []


def test_all_file_sizes_checked_before_any_bank_is_imported(tmp_path, monkeypatch):
    from backend.app.services import question_bank
    service = service_at(tmp_path)
    monkeypatch.setattr(question_bank, "MAX_FILE_BYTES", 3)
    with patch.object(question_bank, "run_document"), patch.object(service, "_import_unit") as import_unit:
        with pytest.raises(question_bank.DocxBudgetError):
            service.import_files("p", "teacher", [("first原卷版.docx", b"ok"), ("second解析版.docx", b"long")])
    import_unit.assert_not_called()
