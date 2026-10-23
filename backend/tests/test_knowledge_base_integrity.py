from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

import pytest

from backend.app.config import AppConfig
from backend.app.services.knowledge_base import KnowledgeBaseService, KnowledgeBaseStorageError


@pytest.fixture
def service(tmp_path):
    config = AppConfig()
    config.knowledge_dir = tmp_path / "knowledge"
    return KnowledgeBaseService(config)


def seed(service, item_id="original", owner="teacher"):
    return service.upsert_item(
        {
            "id": item_id,
            "title": "Population teaching material",
            "summary": "Population density distribution",
            "keywords": ["population"],
            "dataset_refs": [{"metadata": {"label": "original"}}],
            "related_templates": [{"settings": {"label": "original"}}],
        },
        owner_user_id=owner,
    )


def warm_caches(service):
    service.search("population", owner_user_id="teacher")
    return (
        deepcopy(service._cached_manifest),
        service._manifest_fingerprint,
        dict(service._engine_cache),
        deepcopy(service._result_cache),
    )


def assert_caches_unchanged(service, before):
    assert service._cached_manifest == before[0]
    assert service._manifest_fingerprint == before[1]
    assert service._engine_cache == before[2]
    assert service._result_cache == before[3]


def test_all_missing_manifest_reads_are_side_effect_free_and_first_mutation_creates(service):
    assert service.get_manifest()["items"] == []
    assert service.search()["items"] == []
    assert service.topics()["items"] == []
    assert service.build_engine_units() == []
    assert service.engine_units_fingerprint() == ((0, 0), (0, 0))
    assert not service.knowledge_dir.exists()
    seed(service)
    assert service.manifest_path.is_file()
    assert service._manifest_fingerprint == service._fingerprint()


@pytest.mark.parametrize("invalid", [b"{broken", b"[]", b'{"items": {}}', b'{"items": null}', b'{"items": [17]}', b"\xff"])
def test_invalid_manifest_never_gets_replaced_or_published(service, invalid):
    seed(service)
    before = warm_caches(service)
    service.manifest_path.write_bytes(invalid)
    for operation in (
        lambda: service.get_manifest(owner_user_id="teacher"),
        lambda: service.search("population", owner_user_id="teacher"),
        lambda: seed(service, "new"),
        lambda: service.delete_item("original", owner_user_id="teacher"),
        lambda: service.add_material_to_item("original", {"id": "new", "title": "New"}, owner_user_id="teacher"),
    ):
        with pytest.raises(KnowledgeBaseStorageError):
            operation()
        assert service.manifest_path.read_bytes() == invalid
        assert_caches_unchanged(service, before)


@pytest.mark.parametrize("operation", ["read", "stat"])
def test_manifest_io_error_fails_closed_without_overwrite(service, operation):
    seed(service)
    warm_caches(service)
    service._manifest_fingerprint = None  # force a disk refresh after warming derived caches
    before = (
        deepcopy(service._cached_manifest), None, dict(service._engine_cache), deepcopy(service._result_cache)
    )
    original = service.manifest_path.read_bytes()
    method = Path.read_text if operation == "read" else Path.stat

    def fail_manifest(path, *args, **kwargs):
        if path == service.manifest_path:
            raise PermissionError("storage temporarily inaccessible")
        return method(path, *args, **kwargs)

    with patch.object(Path, "read_text" if operation == "read" else "stat", fail_manifest):
        with pytest.raises(KnowledgeBaseStorageError):
            seed(service, "new")
    assert service.manifest_path.read_bytes() == original
    assert_caches_unchanged(service, before)


@pytest.mark.parametrize("failure", ["partial_write", "flush", "fsync", "replace"])
@pytest.mark.parametrize("mutation", ["upsert", "material", "delete"])
def test_failed_commit_preserves_bytes_and_all_caches(service, failure, mutation):
    seed(service)
    before = warm_caches(service)
    original = service.manifest_path.read_bytes()
    real_open = Path.open

    class FailingOutput:
        def __init__(self, output):
            self.output = output

        def __enter__(self):
            self.output.__enter__()
            return self

        def __exit__(self, *args):
            return self.output.__exit__(*args)

        def write(self, value):
            if failure == "partial_write":
                self.output.write(value[:30])
                raise OSError(28, "No space left")
            return self.output.write(value)

        def flush(self):
            if failure == "flush":
                raise OSError(28, "No space left")
            return self.output.flush()

        def fileno(self):
            return self.output.fileno()

    def fail_write(path, *args, **kwargs):
        output = real_open(path, *args, **kwargs)
        if path.suffix == ".tmp" and failure in {"partial_write", "flush"}:
            return FailingOutput(output)
        return output

    with patch.object(Path, "open", fail_write), patch(
        "backend.app.services.knowledge_base.os.fsync",
        side_effect=OSError("fsync failed") if failure == "fsync" else os.fsync,
    ), patch(
        "backend.app.services.knowledge_base.os.replace",
        side_effect=PermissionError("replace failed") if failure == "replace" else os.replace,
    ):
        with pytest.raises(KnowledgeBaseStorageError, match="write failed"):
            if mutation == "upsert":
                seed(service, "uncommitted")
            elif mutation == "material":
                service.add_material_to_item("original", {"id": "uncommitted", "title": "Uncommitted"}, owner_user_id="teacher")
            else:
                service.delete_item("original", owner_user_id="teacher")
    assert service.manifest_path.read_bytes() == original
    assert_caches_unchanged(service, before)
    assert list(service.knowledge_dir.glob("*.tmp")) == []
    assert service.get_manifest(owner_user_id="teacher")["items"][0]["id"] == "original"


def test_failed_first_commit_leaves_no_manifest_or_published_item(service):
    service.get_manifest()
    before = warm_caches(service)
    with patch("backend.app.services.knowledge_base.os.replace", side_effect=OSError("disk unavailable")):
        with pytest.raises(KnowledgeBaseStorageError):
            seed(service)
    assert not service.manifest_path.exists()
    assert_caches_unchanged(service, before)
    assert service.get_manifest()["items"] == []


@pytest.mark.skipif(os.name != "nt", reason="Windows sharing violation recovery")
def test_replace_retries_windows_sharing_violation_and_publishes_once(service):
    seed(service)
    original_replace = os.replace
    calls = []

    def transient_lock(source, target):
        calls.append((source, target))
        if len(calls) < 3:
            raise PermissionError("temporary sharing violation")
        return original_replace(source, target)

    with patch("backend.app.services.knowledge_base.os.replace", transient_lock):
        seed(service, "committed")
    assert len(calls) == 3
    assert {row["id"] for row in service.get_manifest(owner_user_id="teacher")["items"]} == {"original", "committed"}


def test_concurrent_item_additions_keep_every_successful_write(service):
    count = 16
    barrier = Barrier(count)

    def add(index):
        barrier.wait(timeout=10)
        return seed(service, f"item-{index}")["id"]

    with ThreadPoolExecutor(max_workers=count) as pool:
        expected = set(pool.map(add, range(count)))
    persisted = json.loads(service.manifest_path.read_text(encoding="utf-8"))
    assert {row["id"] for row in persisted["items"]} == expected
    assert {row["id"] for row in service.get_manifest(owner_user_id="teacher")["items"]} == expected


def test_concurrent_material_additions_and_other_item_deletions_do_not_lose_updates(service):
    seed(service, "retained")
    count = 8
    for index in range(count):
        seed(service, f"delete-{index}")
    barrier = Barrier(count * 2)

    def mutate(index):
        barrier.wait(timeout=10)
        if index < count:
            return service.add_material_to_item(
                "retained", {"id": f"material-{index}", "title": "Chart", "url": f"/files/{index}.png"},
                owner_user_id="teacher",
            )
        return service.delete_item(f"delete-{index - count}", owner_user_id="teacher")

    with ThreadPoolExecutor(max_workers=count * 2) as pool:
        list(pool.map(mutate, range(count * 2)))
    items = service.get_manifest(owner_user_id="teacher")["items"]
    assert [row["id"] for row in items] == ["retained"]
    assert {row["id"] for row in items[0]["materials"]} == {f"material-{index}" for index in range(count)}
    assert json.loads(service.manifest_path.read_text(encoding="utf-8"))["items"] == service._cached_manifest["items"]


def test_mutation_results_and_payloads_do_not_alias_published_cache(service):
    raw = {"id": "private", "title": "Population", "dataset_refs": [{"metadata": {"value": "safe"}}]}
    created = service.upsert_item(raw, owner_user_id="teacher")
    raw["dataset_refs"][0]["metadata"]["value"] = "changed input"
    created["dataset_refs"][0]["metadata"]["value"] = "changed result"
    material = service.add_material_to_item(
        "private", {"id": "chart", "title": "Chart", "region_binding": {"name": "safe"}}, owner_user_id="teacher"
    )
    material["region_binding"]["name"] = "changed result"
    item = service.get_manifest(owner_user_id="teacher")["items"][0]
    assert item["dataset_refs"][0]["metadata"]["value"] == "safe"
    assert item["materials"][0]["region_binding"]["name"] == "safe"


@pytest.mark.parametrize("cached", [False, True])
def test_nested_manifest_and_search_results_are_isolated(service, cached):
    seed(service)
    service.add_material_to_item(
        "original", {"id": "chart", "title": "Chart", "region_binding": {"name": "original"}}, owner_user_id="teacher"
    )
    if cached:
        service.search("population", owner_user_id="teacher")
    manifest = service.get_manifest(owner_user_id="teacher")
    result = service.search("population", owner_user_id="teacher")
    for item in (manifest["items"][0], result["items"][0]):
        item["dataset_refs"][0]["metadata"]["label"] = "mutated"
        item["related_templates"][0]["settings"]["label"] = "mutated"
        item["materials"][0]["region_binding"]["name"] = "mutated"
    for item in (
        service.get_manifest(owner_user_id="teacher")["items"][0],
        service.search("population", owner_user_id="teacher")["items"][0],
    ):
        assert item["dataset_refs"][0]["metadata"]["label"] == "original"
        assert item["related_templates"][0]["settings"]["label"] == "original"
        assert item["materials"][0]["region_binding"]["name"] == "original"


def test_admin_update_preserves_owner_and_creation_ignores_payload_owner(service):
    created = service.upsert_item(
        {"id": "private", "title": "Population", "owner_user_id": "victim"}, owner_user_id="teacher"
    )
    assert created["owner_user_id"] == "teacher"
    updated = service.upsert_item(
        {"id": "private", "title": "Population updated", "owner_user_id": "other"},
        owner_user_id="admin", include_all=True,
    )
    assert updated["owner_user_id"] == "teacher"
    assert service.get_manifest(owner_user_id="teacher")["items"][0]["title"] == "Population updated"
    assert service.get_manifest(owner_user_id="admin")["items"] == []
    assert service.get_manifest(owner_user_id="other")["items"] == []
    public = service.upsert_item({"id": "built-in", "title": "Population", "owner_user_id": "victim"})
    assert public["owner_user_id"] == ""
    material = service.add_material_to_item(
        "private", {"id": "chart", "title": "Chart", "owner_user_id": "victim"}, owner_user_id="teacher"
    )
    assert material["owner_user_id"] == "teacher"


def test_owner_isolation_and_all_derived_caches_refresh_after_material_and_external_edit(service):
    seed(service, "private-a", owner="teacher-a")
    seed(service, "private-b", owner="teacher-b")
    for _ in range(2):
        for owner, expected in (("teacher-a", "private-a"), ("teacher-b", "private-b")):
            assert [row["id"] for row in service.search("population", owner_user_id=owner)["items"]] == [expected]
    service.add_material_to_item(
        "private-a", {"id": "new", "title": "Population material", "url": "/files/new.png"}, owner_user_id="teacher-a"
    )
    assert service.search("population", owner_user_id="teacher-a")["items"][0]["materials"][0]["id"] == "new"
    assert service.search("population", owner_user_id="teacher-b")["items"][0]["materials"] == []
    service.delete_item("private-a", owner_user_id="teacher-a")
    assert service.search("population", owner_user_id="teacher-a")["items"] == []
    persisted = json.loads(service.manifest_path.read_text(encoding="utf-8"))
    persisted["items"][0]["title"] = "Population external replacement title"
    service.manifest_path.write_text(json.dumps(persisted), encoding="utf-8")
    assert service.search("population", owner_user_id="teacher-b")["items"][0]["title"] == "Population external replacement title"
