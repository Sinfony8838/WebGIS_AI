"""Only synthetic tmp roots and child processes created by these tests."""
import gc
import json
import os
import queue
import select
import subprocess
import sys
import threading
import time
import weakref
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.app.models import LayerRecord
from backend.app.state_writer import StateWriterAlreadyActive
from backend.app.store import InvalidRuntimeState, RuntimeStore
from backend.tests.test_store_recovery import legacy_project


CHILD = """
import sys
from pathlib import Path
from backend.app.store import RuntimeStore
from backend.app.state_writer import StateWriterAlreadyActive
sys.stdin.readline()
try:
    store = RuntimeStore(Path(sys.argv[1]))
except StateWriterAlreadyActive:
    print("BUSY", flush=True)
    sys.exit(3)
print("OWN", flush=True)
sys.stdin.readline()
store.close()
"""


@contextmanager
def child_writer(path):
    proc = subprocess.Popen(
        [sys.executable, "-u", "-c", CHILD, str(path)],
        cwd=Path(__file__).resolve().parents[2],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    lines = queue.Queue()
    def collect():
        for line in proc.stdout:
            lines.put(line.strip())
        lines.put("EOF")
    reader = threading.Thread(target=collect, daemon=True)
    reader.start()
    try:
        yield proc, lines
    finally:
        if proc.poll() is None:
            proc.kill()  # This test's own child only.
        proc.wait(timeout=10)
        reader.join(timeout=10)
        proc.stdin.close()
        proc.stdout.close()
        proc.stderr.close()


def send(proc):
    proc.stdin.write("continue\n")
    proc.stdin.flush()


def result(lines):
    return lines.get(timeout=10)


def test_second_writer_rejected_before_loading_or_effects(tmp_path):
    path = tmp_path / "runtime.json"
    store = RuntimeStore(path)
    project = store.create_project("retained")
    before = path.read_bytes()
    with patch.object(Path, "read_text", side_effect=AssertionError("must reject before reading")):
        with pytest.raises(StateWriterAlreadyActive):
            RuntimeStore(path)
    assert path.read_bytes() == before
    assert store.get_project(project.project_id) is project
    # A different snapshot filename still shares this data root.
    with pytest.raises(StateWriterAlreadyActive):
        RuntimeStore(tmp_path / "other.json")
    assert not (tmp_path / "other.json").exists()
    store.close()


def test_separate_process_rejected_without_changing_bytes(tmp_path):
    path = tmp_path / "runtime.json"
    store = RuntimeStore(path)
    store.create_project("retained")
    before = path.read_bytes()
    with child_writer(path) as (proc, lines):
        send(proc)
        assert result(lines) == "BUSY"
        assert proc.wait(timeout=10) == 3
    assert path.read_bytes() == before
    store.close()


def test_racing_processes_have_exactly_one_writer(tmp_path):
    path = tmp_path / "runtime.json"
    with child_writer(path) as (first, first_lines), child_writer(path) as (second, second_lines):
        send(first)
        send(second)
        outcomes = [result(first_lines), result(second_lines)]
        assert sorted(outcomes) == ["BUSY", "OWN"]
        owner = first if outcomes[0] == "OWN" else second
        send(owner)
        assert owner.wait(timeout=10) == 0
    with_store = RuntimeStore(path)
    with_store.close()


def test_process_death_releases_lease_without_data_restore(tmp_path):
    path = tmp_path / "runtime.json"
    store = RuntimeStore(path)
    project = store.create_project("retained")
    store.close()
    before = path.read_bytes()
    with child_writer(path) as (proc, lines):
        send(proc)
        assert result(lines) == "OWN"
        proc.kill()
        proc.wait(timeout=10)
        replacement = RuntimeStore(path)
        assert replacement.get_project(project.project_id).name == "retained"
        assert path.read_bytes() == before
        replacement.close()


def test_close_from_another_thread_and_closed_writes_rejected(tmp_path):
    path = tmp_path / "runtime.json"
    store = RuntimeStore(path)
    project = store.create_project("retained")
    before = path.read_bytes()
    closer = threading.Thread(target=store.close)
    closer.start()
    closer.join(timeout=5)
    assert not closer.is_alive()
    store.close()
    replacement = RuntimeStore(path)
    with pytest.raises(RuntimeError, match="closed"):
        store.create_project("must not appear")
    assert list(store.projects) == [project.project_id]
    assert path.read_bytes() == before
    replacement.close()


def test_failed_startup_releases_lease(tmp_path):
    path = tmp_path / "runtime.json"
    path.write_text('{"projects": []}', encoding="utf-8")
    with pytest.raises(InvalidRuntimeState):
        RuntimeStore(path)
    path.write_text("{}", encoding="utf-8")
    store = RuntimeStore(path)
    store.close()


def test_garbage_collection_releases_unreferenced_store(tmp_path):
    path = tmp_path / "runtime.json"
    store = RuntimeStore(path)
    ref = weakref.ref(store)
    del store
    gc.collect()
    assert ref() is None
    replacement = RuntimeStore(path)
    replacement.close()


@pytest.mark.parametrize("operation", ["create", "patch", "delete", "save", "batch"])
def test_readonly_snapshot_rejects_mutation_before_memory_or_disk_changes(tmp_path, operation):
    path = tmp_path / "runtime.json"
    writer = RuntimeStore(path)
    project = writer.create_project("retained")
    layer = LayerRecord.create(name="retained layer", kind="vector", source="test", geometry_type="Point")
    writer.upsert_layer(project.project_id, layer)
    reader = RuntimeStore(path, read_only=True)
    before = path.read_bytes()
    snapshot = reader.get_project(project.project_id).to_dict()
    def mutate():
        if operation == "create":
            reader.create_project("forbidden")
        elif operation == "patch":
            reader.patch_layer(project.project_id, layer.layer_id, {"opacity": 0})
        elif operation == "delete":
            reader.delete_layer(project.project_id, layer.layer_id)
        elif operation == "save":
            reader._save()
        else:
            with reader.batch():
                raise AssertionError("must not enter")
    with pytest.raises(RuntimeError, match="read-only"):
        mutate()
    assert reader.get_project(project.project_id).to_dict() == snapshot
    assert list(reader.projects) == [project.project_id]
    assert path.read_bytes() == before
    writer.close()


def test_readonly_migration_and_bad_json_never_write(tmp_path):
    path = tmp_path / "runtime.json"
    project = legacy_project()
    path.write_text(json.dumps({"projects": {project.project_id: project.to_dict()}}), encoding="utf-8")
    before = path.read_bytes()
    reader = RuntimeStore(path, read_only=True)
    assert reader.get_project(project.project_id).layers == []
    assert path.read_bytes() == before
    path.write_text("{bad synthetic json", encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(InvalidRuntimeState):
        RuntimeStore(path, read_only=True)
    assert path.read_bytes() == before
    assert not list(tmp_path.glob("runtime.corrupt_*"))


def test_readonly_new_root_does_not_create_directories(tmp_path):
    root = tmp_path / "absent"
    reader = RuntimeStore(root / "runtime.json", read_only=True)
    assert reader.projects == {}
    assert not root.exists()


def test_physical_directory_alias_cannot_acquire_second_writer(tmp_path):
    root = tmp_path / "physical"
    root.mkdir()
    alias = tmp_path / "alias"
    assert alias.parent.resolve() == tmp_path.resolve()
    if os.name == "nt":
        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(alias), str(root)],
                              capture_output=True, text=True, timeout=10,
                              creationflags=subprocess.CREATE_NO_WINDOW)
        assert made.returncode == 0, made.stderr
    else:
        alias.symlink_to(root, target_is_directory=True)
    try:
        writer = RuntimeStore(root / "runtime.json")
        with pytest.raises(StateWriterAlreadyActive):
            RuntimeStore(alias / "runtime.json")
        writer.close()
        successor = RuntimeStore(alias / "runtime.json")
        assert successor.state_file.parent == root.resolve()
        successor.close()
    finally:
        if os.name == "nt":
            alias.rmdir()  # Remove only this verified test Junction.
        else:
            alias.unlink()


@pytest.mark.skipif(not hasattr(os, "fork"), reason="POSIX fork inheritance")
def test_fork_child_cannot_write_or_retain_parent_lease(tmp_path):
    path = tmp_path / "runtime.json"
    store = RuntimeStore(path)
    store.create_project("retained")
    held = threading.Event()
    release = threading.Event()
    def hold_store_lock():
        with store._lock:
            held.set()
            release.wait(timeout=15)
    locker = threading.Thread(target=hold_store_lock)
    locker.start()
    assert held.wait(timeout=5)
    ready_read, ready_write = os.pipe()
    stop_read, stop_write = os.pipe()
    child = os.fork()
    if child == 0:
        os.close(ready_read)
        os.close(stop_write)
        try:
            store.close()
            try:
                store.create_project("forbidden inherited writer")
            except RuntimeError:
                os.write(ready_write, b"OK")
            else:
                os.write(ready_write, b"FAIL")
            os.read(stop_read, 1)
        finally:
            os._exit(0)
    release.set()
    locker.join(timeout=5)
    os.close(ready_write)
    os.close(stop_read)
    try:
        assert select.select([ready_read], [], [], 10)[0]
        assert os.read(ready_read, 4) == b"OK"
        with pytest.raises(StateWriterAlreadyActive):
            RuntimeStore(path)
        store.close()
        # Child is still alive: inherited flock descriptors must be gone.
        replacement = RuntimeStore(path)
        assert len(replacement.projects) == 1
        replacement.close()
    finally:
        os.write(stop_write, b"x")
        os.close(stop_write)
        os.close(ready_read)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if os.waitpid(child, os.WNOHANG)[0]:
                break
            time.sleep(0.01)
        else:
            os.kill(child, 9)
            os.waitpid(child, 0)
