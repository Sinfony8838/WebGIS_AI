import asyncio
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from PIL import Image

from backend.app.config import AppConfig
from backend.app.services.project_presentations import ProjectPresentations
from backend.app.services import ppt_renderer


@pytest.fixture
def library(tmp_path):
    config = AppConfig(root_dir=tmp_path)
    config.ensure_dirs()
    project = SimpleNamespace(owner_user_id="teacher", metadata={})
    lessons = []
    store = SimpleNamespace(get_project=lambda pid: project if pid == "project_test" else None,
                            list_lessons=lambda: lessons)
    return ProjectPresentations(config, store), project, lessons


def exported_lesson(library):
    service, project, lessons = library
    root = service.config.uploads_dir / "project_test" / "imported"
    root.mkdir(parents=True)
    source = root / "class.pptx"
    source.write_bytes(b"original presentation")
    pages = []
    for i in range(3):
        path = root / f"slide{i + 1}.png"
        Image.new("RGB", (160, 90), (i * 80, 40, 10)).save(path)
        pages.append({"number": i + 1, "file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest = {"slide_count": 3, "slides": pages, "source_sha256": digest}
    (root / "render_manifest.json").write_text(json.dumps(manifest))
    lesson = SimpleNamespace(lesson_id="one", title="Existing class", owner_user_id="teacher",
                             metadata={"project_id": "project_test", "source_file_name": source.name,
                                       "source_sha256": digest, "source_url": service.config.public_url_for_path(source),
                                       "slide_count": 3, "preview_renderer": "Microsoft PowerPoint"})
    lessons.append(lesson)
    return root, lesson


def test_registered_native_lesson_is_reused_without_conversion_or_writes(library):
    service, _, _ = library
    root, _ = exported_lesson(library)
    before = {p: p.read_bytes() for p in root.iterdir()}
    with patch("backend.app.services.project_presentations.render_pptx_to_images") as render:
        row = service.list("project_test")["items"][0]
        assert row["page_count"] == 3
        assert row["status"] == "ready"
        assert "source_url" not in row
        detail = service.get("project_test", row["id"])
        assert [p["index"] for p in detail["slides"]] == [0, 1, 2]
        render.assert_not_called()
    assert {p: p.read_bytes() for p in root.iterdir()} == before
    assert not service._registry("project_test").exists()


@pytest.mark.parametrize("failure", ["missing", "hash", "order", "source", "count", "traversal"])
def test_rejects_corrupt_incomplete_or_unowned_lesson_exports(library, failure):
    service, _, _ = library
    root, lesson = exported_lesson(library)
    path = root / "render_manifest.json"
    manifest = json.loads(path.read_text())
    if failure == "missing": (root / "slide2.png").unlink()
    if failure == "hash": (root / "slide2.png").write_bytes(b"not a PNG")
    if failure == "order": manifest["slides"][0]["number"] = 2
    if failure == "source": lesson.metadata["source_url"] = "/files/uploads/another/private.pptx"
    if failure == "count": manifest["slide_count"] = 4
    if failure == "traversal": manifest["slides"][0]["file"] = "../outside.png"
    path.write_text(json.dumps(manifest))
    row = service.get("project_test", "lesson_one")
    assert row["status"] == "failed" and row["slides"] == []


def test_other_owner_and_orphan_cache_are_not_discovered(library):
    service, _, _ = library
    _, lesson = exported_lesson(library)
    lesson.owner_user_id = "other"
    orphan = service.config.outputs_dir / "ppt_previews" / "old"
    orphan.mkdir(parents=True)
    (orphan / "private.pptx").write_bytes(b"not registered")
    assert service.list("project_test")["items"] == []
    with pytest.raises(KeyError): service.get("project_other", "lesson_one")
    with pytest.raises(KeyError): service.get("project_test", "../private")


def test_import_is_persistent_and_idempotent_per_project_hash(library):
    service, _, _ = library
    one = service.import_file("project_test", "A.pptx", b"same", "request_123")
    two = service.import_file("project_test", "B.pptx", b"same", "request_456")
    assert one == two
    restarted = ProjectPresentations(service.config, service.store)
    assert len(restarted.list("project_test")["items"]) == 1
    assert restarted.get("project_test", one)["status"] == "pending"
    with pytest.raises(ValueError): service.import_file("project_test", "C.pptx", b"different", "request_123")
    with pytest.raises(ValueError): service.import_file("project_test", "bad.txt", b"x", "request_789")


def test_only_project_linked_accessible_kb_material_is_available(library):
    service, project, _ = library
    root = service.config.uploads_dir / "kb_materials"
    root.mkdir(exist_ok=True)
    (root / "linked.pptx").write_bytes(b"linked")
    project.metadata["lesson_resource_sets"] = [{"material_ids": ["linked", "foreign"], "item_ids": []}]
    seen = []
    def manifest(**kwargs):
        seen.append(kwargs)
        return {"items": [{"id": "item", "materials": [
            {"id": "linked", "title": "Linked", "url": "/files/uploads/kb_materials/linked.pptx"},
            {"id": "unlinked", "title": "Hidden", "url": "/files/uploads/kb_materials/linked.pptx"},
            {"id": "foreign", "title": "Outside", "url": "/files/uploads/other/private.pptx"}]}]}
    service.knowledge = SimpleNamespace(get_manifest=manifest)
    assert [r["id"] for r in service.list("project_test")["items"]] == ["material_linked"]
    assert seen == [{"owner_user_id": "teacher", "include_all": False}]


def test_native_only_path_never_silently_calls_libreoffice(tmp_path):
    config = AppConfig(root_dir=tmp_path)
    with patch.object(ppt_renderer.sys, "platform", "win32"), patch.object(ppt_renderer, "_attempt_powerpoint", return_value=None), patch.object(ppt_renderer, "_attempt_libreoffice") as fallback:
        with pytest.raises(ppt_renderer.PptRenderError):
            ppt_renderer.render_pptx_to_images(config, "one.ppt", b"data", powerpoint_only=True)
        fallback.assert_not_called()


def test_duplicate_prepare_is_single_job_and_refresh_does_not_submit(library):
    async def run():
        service, _, _ = library
        key = service.import_file("project_test", "A.pptx", b"source", "request_123")
        gate = asyncio.Event()
        calls = []
        class Executor:
            async def run(self, work):
                calls.append(1)
                await gate.wait()
                root = service.config.outputs_dir / "project_test" / "presentations" / key
                root.mkdir(parents=True, exist_ok=True)
                image = root / "one.png"
                Image.new("RGB", (160, 90)).save(image)
                return {"renderer": "powerpoint-worker", "slides": [{"index": 0,
                    "image_url": service.config.public_url_for_path(image), "width": 160 * 9525, "height": 90 * 9525}]}
        executor = Executor()
        one = service.start("project_test", key, executor)
        two = service.start("project_test", key, executor)
        assert one["job_id"] == two["job_id"]
        await asyncio.sleep(0)
        for _ in range(10): assert service.get("project_test", key)["status"] == "running"
        assert len(calls) == 1
        gate.set()
        await service.close()
        assert service.get("project_test", key)["status"] == "ready"
        assert service.start("project_test", key, executor)["job_id"] == one["job_id"]
        assert len(calls) == 1
    asyncio.run(run())


def test_failed_conversion_requires_explicit_retry_and_restart_never_replays(library):
    async def run():
        service, _, _ = library
        key = service.import_file("project_test", "A.pptx", b"source", "request_123")
        class Executor:
            async def run(self, work): raise TimeoutError("native timeout")
        first = service.start("project_test", key, Executor())
        await service.close()
        assert service.get("project_test", key)["status"] == "failed"
        assert service.start("project_test", key, Executor())["job_id"] == first["job_id"]
        rows = service._read("project_test"); rows[key]["status"] = "running"; service._write("project_test", rows)
        restarted = ProjectPresentations(service.config, service.store)
        assert restarted.get("project_test", key)["status"] == "failed"
        assert not restarted.tasks
        restarted.start("project_test", key, Executor(), retry=True)
        await restarted.close()
    asyncio.run(run())


def test_all_new_routes_check_project_access_before_read_or_write(library):
    from fastapi import HTTPException, Request
    from backend.app import main
    service, _, _ = library
    request = Request({"type": "http", "app": main.app})
    with patch.object(main, "_require_project_access", side_effect=HTTPException(404)), patch.object(main, "_presentation_library") as getter:
        with pytest.raises(HTTPException): main.list_project_presentations("other", request)
        with pytest.raises(HTTPException): main.get_project_presentation("other", "id", request)
        with pytest.raises(HTTPException): asyncio.run(main.prepare_project_presentation("other", "id", request))
        with pytest.raises(HTTPException): asyncio.run(main.import_project_presentation("other", request, None, "request_123"))
        getter.assert_not_called()


def test_font_dependencies_are_recorded_without_reconstructing_slide_content(tmp_path):
    import zipfile
    source = tmp_path / "fonts.pptx"
    with zipfile.ZipFile(source, "w") as package:
        package.writestr("ppt/slides/slide1.xml", '<slide><latin typeface="Arial"/><latin typeface="+mn-lt"/><eastAsian typeface="宋体"/></slide>')
        package.writestr("ppt/theme/theme1.xml", '<theme><latin typeface="Arial"/></theme>')
    original = source.read_bytes()
    assert ppt_renderer._font_dependencies(source) == ["Arial", "宋体"]
    assert source.read_bytes() == original


def test_lost_cached_pages_are_listed_as_failed_so_explicit_retry_is_available(library):
    service, _, _ = library
    key = service.import_file("project_test", "A.pptx", b"source", "request_123")
    rows = service._read("project_test")
    rows[key].update(status="ready", slides=[{"index": 0, "width": 160 * 9525, "height": 90 * 9525,
        "image_url": "/files/outputs/project_test/presentations/missing.png"}])
    service._write("project_test", rows)
    row = service.list("project_test")["items"][0]
    assert row["status"] == "failed" and row["page_count"] == 0
    assert service.get("project_test", key)["status"] == "failed"


def test_manifest_write_failure_releases_owned_task_without_replaying_it(library):
    async def run():
        service, _, _ = library
        key = service.import_file("project_test", "A.pptx", b"source", "request_123")
        root = service.config.outputs_dir / "project_test" / "slides"
        root.mkdir(parents=True)
        image = root / "one.png"; Image.new("RGB", (160, 90)).save(image)
        class Executor:
            async def run(self, work):
                return {"renderer": "powerpoint-worker", "slides": [{"index": 0,
                    "image_url": service.config.public_url_for_path(image), "width": 160 * 9525, "height": 90 * 9525}]}
        write = service._write
        def fail_ready(project_id, rows):
            if rows[key]["status"] == "ready": raise OSError("synthetic disk full")
            write(project_id, rows)
        with patch.object(service, "_write", side_effect=fail_ready):
            service.start("project_test", key, Executor())
            await service.close()
        assert not service.tasks
        assert service.get("project_test", key)["status"] == "failed"
    asyncio.run(run())
