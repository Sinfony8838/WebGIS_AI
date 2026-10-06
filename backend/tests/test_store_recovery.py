"""Recovery failure injection uses synthetic snapshots in temporary directories."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.app.models import LayerRecord, ProjectRecord
from backend.app.store import InvalidRuntimeState, RuntimeStore


@pytest.fixture
def snapshot(tmp_path):
    path = tmp_path / "runtime.json"
    store = RuntimeStore(path)
    project = store.create_project("retained synthetic project")
    return path, store, project


def assert_preserved(path, before):
    assert path.read_bytes() == before
    assert not list(path.parent.glob("runtime.corrupt_*"))


@pytest.mark.parametrize("failure", [PermissionError, OSError])
@pytest.mark.parametrize("reload", [False, True])
def test_read_failure_does_not_quarantine_or_clear(snapshot, failure, reload):
    path, store, project = snapshot
    before = path.read_bytes()
    with patch.object(Path, "read_text", side_effect=failure("synthetic read failure")):
        with pytest.raises(failure):
            store._load() if reload else RuntimeStore(path)
    assert store.get_project(project.project_id) is project
    assert_preserved(path, before)


def test_unsupported_encoding_is_not_misclassified_as_schema(snapshot):
    path, store, project = snapshot
    path.write_bytes(b"\xff\xfe unsupported snapshot")
    before = path.read_bytes()
    with pytest.raises(UnicodeDecodeError):
        store._load()
    assert store.get_project(project.project_id) is project
    assert_preserved(path, before)


@pytest.mark.parametrize("case", ["root", "collection", "record", "missing_field", "future_field", "layers", "late_collection"])
def test_unsupported_schema_preserves_bytes_and_active_collections(snapshot, case):
    path, store, project = snapshot
    payload = json.loads(path.read_text(encoding="utf-8"))
    if case == "root":
        payload = []
    elif case == "collection":
        payload["projects"] = None
    elif case == "record":
        payload["projects"][project.project_id] = []
    elif case == "missing_field":
        del payload["projects"][project.project_id]["name"]
    elif case == "future_field":
        payload["projects"][project.project_id]["future_version_field"] = True
    elif case == "layers":
        payload["projects"][project.project_id]["layers"] = {}
    else:
        payload["projects"][project.project_id]["name"] = "must not partly commit"
        payload["workflows"] = []
    path.write_text(json.dumps(payload), encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(InvalidRuntimeState):
        store._load()
    assert store.get_project(project.project_id) is project
    assert project.name == "retained synthetic project"
    assert_preserved(path, before)


@pytest.mark.parametrize("failure", [TypeError, ValueError, RuntimeError])
def test_decoder_programming_error_is_not_corrupt_data(snapshot, failure):
    path, store, project = snapshot
    before = path.read_bytes()
    with patch.object(store, "_decode_record", side_effect=failure("synthetic decoder bug")):
        with pytest.raises(failure):
            store._load()
    assert store.get_project(project.project_id) is project
    assert_preserved(path, before)


def test_bad_json_quarantine_failure_aborts_without_overwrite(snapshot):
    path, store, project = snapshot
    path.write_text("{invalid synthetic json", encoding="utf-8")
    before = path.read_bytes()
    with patch.object(Path, "replace", side_effect=PermissionError("synthetic quarantine denial")):
        with pytest.raises(PermissionError):
            RuntimeStore(path)
    assert store.get_project(project.project_id) is project
    assert_preserved(path, before)


def legacy_project():
    project = ProjectRecord.create("synthetic legacy migration")
    project.layers = [LayerRecord.create(
        layer_id="builtin_population_regions", name="retired", kind="vector", source="builtin",
        geometry_type="Polygon", data={"features": [{"geometry": {"type": "Polygon",
        "coordinates": [[[80, 35], [110, 35], [110, 46], [80, 46], [80, 35]]]}}]},
    )]
    return project


@pytest.mark.parametrize("failure", ["migration", "temporary_write", "atomic_replace"])
def test_migration_failure_keeps_valid_snapshot_and_loaded_records(tmp_path, failure):
    path = tmp_path / "runtime.json"
    store = RuntimeStore(path)
    project = legacy_project()
    path.write_text(json.dumps({"projects": {project.project_id: project.to_dict()}}), encoding="utf-8")
    before = path.read_bytes()
    if failure == "migration":
        target = patch.object(store, "_remove_legacy_region_demo_layers", side_effect=ValueError("synthetic migration bug"))
        error = ValueError
    elif failure == "temporary_write":
        target = patch.object(Path, "write_text", side_effect=OSError("synthetic full disk"))
        error = OSError
    else:
        target = patch.object(Path, "replace", side_effect=PermissionError("synthetic replacement denial"))
        error = PermissionError
    with target:
        with pytest.raises(error):
            store._load()
    if failure != "migration":
        assert store.get_project(project.project_id).name == project.name
        assert store.get_project(project.project_id).layers == []
    assert_preserved(path, before)
    assert not list(tmp_path.glob("*.tmp"))
    # A later clean restart completes the same migration using the old bytes.
    restored = RuntimeStore(path)
    assert restored.get_project(project.project_id).layers == []
    assert not list(tmp_path.glob("runtime.corrupt_*"))


@pytest.mark.parametrize("failure", [PermissionError, OSError])
def test_external_layer_io_failure_does_not_publish_partial_load(snapshot, failure):
    path, store, project = snapshot
    layer = LayerRecord.create(name="synthetic large", kind="vector", source="test", geometry_type="Point",
        data={"type": "FeatureCollection", "features": [{"properties": {"synthetic": "x" * 300000}}]})
    store.upsert_layer(project.project_id, layer)
    before = path.read_bytes()
    read_text = Path.read_text

    def read_with_failure(file, *args, **kwargs):
        if file.parent.name == "layer_data":
            raise failure("synthetic external-file read denial")
        return read_text(file, *args, **kwargs)

    with patch.object(Path, "read_text", read_with_failure):
        with pytest.raises(failure):
            store._load()
    assert store.get_project(project.project_id) is project
    assert project.layers[0] is layer
    assert_preserved(path, before)


def test_legacy_conversation_defaults_and_null_lesson_plan_remain_readable(tmp_path):
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps({
        "conversations": {"c": {"conversation_id": "c", "project_id": "p", "created_at": "historical"}},
        "lessons": {"l": {"lesson_id": "l", "title": "synthetic old lesson", "plan": None}},
    }), encoding="utf-8")
    before = path.read_bytes()
    store = RuntimeStore(path)
    assert store.get_conversation("c").assistant_mode == "tool"
    assert store.get_conversation("c").updated_at == "historical"
    assert store.get_lesson("l").plan == {}
    assert_preserved(path, before)
