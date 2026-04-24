from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.app.models import LayerRecord
from backend.app.store import RuntimeStore


class RuntimeStoreTest(unittest.TestCase):
    def test_project_layer_and_artifact_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = RuntimeStore(Path(temp_dir) / "state.json")
            project = store.create_project(name="课堂演示")
            layer = LayerRecord.create(
                layer_id="layer_demo",
                name="演示图层",
                kind="vector",
                source="builtin",
                geometry_type="Point",
            )
            store.upsert_layer(project.project_id, layer)
            patched = store.patch_layer(project.project_id, layer.layer_id, {"visible": False, "style": {"fillColor": "#facc15"}})
            self.assertFalse(patched.visible)
            self.assertEqual(patched.style["fillColor"], "#facc15")

            job = store.create_job(project.project_id, "assistant", "测试任务")
            artifact = store.register_artifact(project.project_id, job.job_id, "assistant_note", "说明", "C:/tmp/note.md")
            self.assertEqual(store.get_artifact(artifact.artifact_id).title, "说明")
            self.assertEqual(len(store.list_outputs(project.project_id)), 1)

    def test_corrupt_state_file_is_quarantined_and_store_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir) / "state.json"
            state_file.write_text("{broken json", encoding="utf-8")

            store = RuntimeStore(state_file)
            self.assertEqual(store.projects, {})
            self.assertEqual(store.jobs, {})
            self.assertEqual(store.artifacts, {})
            self.assertFalse(state_file.exists())

            quarantined = list(Path(temp_dir).glob("state.corrupt_*"))
            self.assertTrue(quarantined)

            project = store.create_project(name="Recovered")
            self.assertTrue(state_file.exists())
            self.assertEqual(store.get_project(project.project_id).name, "Recovered")
