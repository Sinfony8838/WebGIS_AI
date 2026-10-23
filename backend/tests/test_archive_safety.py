"""Synthetic bounded ZIPs; no production data, model or native Office calls."""
import asyncio
import io
import stat
import zipfile
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from backend.app.services import archive_safety, ppt_renderer, question_bank_parser
from backend.app.services.archive_safety import ArchiveLimitError, ArchiveValidationError, ZipLimits, validate_office_bytes, validate_zip
from backend.app.services.datasets import DatasetService
from backend.app.services.lesson_docx_import import parse_lesson_docx
from backend.app.services.timeline_service import TimelineService


def package(entries, *, compression=zipfile.ZIP_DEFLATED):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression) as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return buffer.getvalue()


def office(kind="docx", extra=()):
    main = "word/document.xml" if kind == "docx" else "ppt/presentation.xml"
    return package([("[Content_Types].xml", "<Types/>"), ("_rels/.rels", "<Relationships/>"),
                    (main, "<document/>"), *extra])


def validate(raw, limits=ZipLimits(2048, 1024, 10)):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        return validate_zip(archive, limits)


@pytest.mark.parametrize("name", ["../evil", "x/../evil", "x\\..\\evil", "/evil", "C:/evil",
                                  "//host/path", "a:stream", "CON.txt", "a.", "a ", "a?.txt"])
def test_unsafe_names_rejected(name):
    with pytest.raises(ArchiveValidationError):
        validate(package([(name, b"x")]))


@pytest.mark.parametrize("names", [("A.txt", "a.txt"), ("a/b", "a\\b"), ("a", "./a"), ("a", "a/b")])
def test_duplicate_aliases_and_file_directory_conflicts_rejected(names):
    with pytest.raises(ArchiveValidationError):
        validate(package([(name, b"x") for name in names]))


def test_symlink_rejected():
    info = zipfile.ZipInfo("link")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with pytest.raises(ArchiveValidationError):
        validate(package([(info, b"target")]))


@pytest.mark.parametrize("entries,limits", [
    ([("a", b"x"), ("b", b"x")], ZipLimits(32, 32, 1)),
    ([("a", b"x" * 17)], ZipLimits(32, 16, 2)),
    ([("a", b"x" * 17), ("b", b"x" * 16)], ZipLimits(32, 32, 2)),
])
def test_metadata_budgets_reject_before_open(entries, limits):
    with zipfile.ZipFile(io.BytesIO(package(entries))) as archive:
        archive.open = Mock(side_effect=AssertionError("no decompression after rejected metadata"))
        with pytest.raises(ArchiveLimitError):
            validate_zip(archive, limits)
        archive.open.assert_not_called()


def test_actual_reads_are_bounded_even_for_dishonest_metadata():
    info = zipfile.ZipInfo("data")
    info.file_size = 1
    info.compress_size = 1
    sizes = []

    class Stream(io.BytesIO):
        def read(self, size=-1):
            sizes.append(size)
            return super().read(size)

    archive = SimpleNamespace(infolist=lambda: [info], open=lambda member: Stream(b"x" * 33))
    with pytest.raises(ArchiveLimitError):
        validate_zip(archive, ZipLimits(32, 32))
    assert sizes == [33]


def test_crc_and_declared_size_mismatch_rejected():
    raw = package([("data", b"CORRUPTME")], compression=zipfile.ZIP_STORED)
    damaged = raw.replace(b"CORRUPTME", b"XORRUPTME", 1)
    with pytest.raises(ArchiveValidationError, match="CRC"):
        validate(damaged)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        archive.infolist()[0].file_size += 1
        with pytest.raises(ArchiveValidationError, match="大小"):
            validate_zip(archive, ZipLimits(1024, 1024))


def test_geodata_crc_failure_happens_before_any_extraction(tmp_path):
    raw = package([("data.shp", b"CORRUPTME")], compression=zipfile.ZIP_STORED)
    raw = raw.replace(b"CORRUPTME", b"XORRUPTME", 1)
    target = tmp_path / "extracted"
    with zipfile.ZipFile(io.BytesIO(raw)) as archive, pytest.raises(ArchiveValidationError):
        DatasetService.__new__(DatasetService)._safe_extract_zip(archive, target)
    assert not target.exists()


def test_legal_nested_geodata_and_existing_limits(tmp_path):
    from backend.app.services import datasets
    assert (datasets.MAX_ZIP_UNCOMPRESSED_BYTES, datasets.MAX_SINGLE_ENTRY_BYTES, datasets.MAX_ZIP_ENTRIES) == (
        512 * 1024 * 1024, 256 * 1024 * 1024, 2000)
    raw = package([("nested/", b""), ("nested/data.shp", b"content")])
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        DatasetService.__new__(DatasetService)._safe_extract_zip(archive, tmp_path / "out")
    assert (tmp_path / "out/nested/data.shp").read_bytes() == b"content"


@pytest.mark.parametrize("kind", ["docx", "pptx"])
def test_office_validates_required_parts_and_unreferenced_media(kind):
    validate_office_bytes(office(kind), kind)
    with pytest.raises(ArchiveValidationError):
        validate_office_bytes(package([("[Content_Types].xml", b"x")]), kind)
    with pytest.raises(ArchiveLimitError):
        validate_office_bytes(office(kind, [("unreferenced.bin", b"x" * 2048)]), kind,
                              limits=ZipLimits(1024, 1024))


def test_high_compression_text_within_budget_is_accepted():
    raw = office(extra=[("word/text.xml", b"x" * 100_000)])
    assert len(raw) < 2000
    validate_office_bytes(raw, "docx")


@pytest.mark.parametrize("entry", ["lesson", "question_bank", "timeline_docx", "timeline_pptx", "ppt"])
def test_all_public_office_parsers_reject_before_heavy_parsing(entry, monkeypatch, tmp_path):
    # Valid package metadata but one unreferenced member exceeds the tiny test budget.
    monkeypatch.setattr(archive_safety, "OFFICE_ZIP_LIMITS", ZipLimits(128, 128))
    monkeypatch.setattr(question_bank_parser, "MAX_UNCOMPRESSED_BYTES", 128)
    kind = "pptx" if entry in {"ppt", "timeline_pptx"} else "docx"
    raw = office(kind, [("unused.bin", b"x" * 129)])
    forbidden = Mock(side_effect=AssertionError("heavy parser must not run"))
    monkeypatch.setattr("backend.app.services.lesson_docx_import.Document", forbidden)
    monkeypatch.setattr("docx.Document", forbidden)
    monkeypatch.setattr("pptx.Presentation", forbidden)
    monkeypatch.setattr(ppt_renderer, "_attempt_powerpoint", forbidden)
    monkeypatch.setattr(ppt_renderer, "_attempt_libreoffice", forbidden)
    if entry == "ppt":
        config = SimpleNamespace(ensure_dirs=forbidden, outputs_dir=tmp_path / "outputs")
        with pytest.raises(ppt_renderer.PptRenderError) as caught:
            ppt_renderer.render_pptx_to_images(config, "historical.pptx", raw, output_root=tmp_path / "retry")
        assert caught.value.status_code == 413
        assert not (tmp_path / "retry").exists()
    else:
        with pytest.raises(ArchiveLimitError):
            if entry == "lesson":
                parse_lesson_docx(raw)
            elif entry == "question_bank":
                question_bank_parser.QuestionBankDocxParser("bank.docx", raw).parse()
            else:
                TimelineService(None).extract_text("lesson." + kind, raw)
    forbidden.assert_not_called()


def test_legacy_doc_remains_unsupported_and_legacy_ppt_is_not_treated_as_zip(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match=".docx"):
        TimelineService(None).extract_text("old.doc", b"legacy")
    from backend.app.config import AppConfig
    config = AppConfig(root_dir=tmp_path)
    called = Mock(return_value=None)
    monkeypatch.setattr(ppt_renderer.sys, "platform", "win32")
    monkeypatch.setattr(ppt_renderer, "_attempt_powerpoint", called)
    with pytest.raises(ppt_renderer.PptRenderError) as caught:
        ppt_renderer.render_pptx_to_images(config, "old.ppt", b"legacy", powerpoint_only=True)
    assert caught.value.code == "PPT_RENDERER_UNAVAILABLE"
    called.assert_called_once()


def test_stored_project_ppt_preparation_and_retry_reject_archive_before_converter(tmp_path, monkeypatch):
    from backend.app.config import AppConfig
    from backend.app.services.project_presentations import ProjectPresentations
    config = AppConfig(root_dir=tmp_path)
    config.ensure_dirs()
    project = SimpleNamespace(owner_user_id="teacher", metadata={})
    store = SimpleNamespace(get_project=lambda pid: project, list_lessons=lambda: [])
    library = ProjectPresentations(config, store)
    # Represents an already-stored pre-fix source; import_file intentionally has
    # no new validation in this batch. Preparation must guard legacy sources too.
    presentation_id = library.import_file("project", "stored.pptx", b"not a zip", "historical_123")
    forbidden = Mock(side_effect=AssertionError("native converter must not run"))
    monkeypatch.setattr(ppt_renderer, "_attempt_powerpoint", forbidden)
    monkeypatch.setattr(ppt_renderer, "_attempt_libreoffice", forbidden)

    class Executor:
        async def run(self, fn):
            return fn()

    async def exercise():
        for retry in (False, True):
            library.start("project", presentation_id, Executor(), retry=retry)
            await asyncio.gather(*list(library.tasks.values()))
            assert library.get("project", presentation_id)["status"] == "failed"

    asyncio.run(exercise())
    forbidden.assert_not_called()
