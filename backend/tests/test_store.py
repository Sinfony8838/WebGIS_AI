from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.app.models import LayerRecord, ProjectRecord
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

    def test_restored_legacy_region_demo_is_removed_with_its_stale_visual_query(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir) / "state.json"
            project = ProjectRecord.create(name="Legacy map")
            project.enabled_templates = ["population_distribution", "population_density"]
            project.active_layer_id = "visual_query_prefecture_population_2020_topd20"
            project.layers = [
                LayerRecord.create(
                    layer_id="builtin_population_regions",
                    name="Legacy regions",
                    kind="vector",
                    source="builtin",
                    geometry_type="Polygon",
                    data={
                        "type": "FeatureCollection",
                        "features": [
                            {
                                "type": "Feature",
                                "properties": {"name": "Legacy region"},
                                "geometry": {
                                    "type": "Polygon",
                                    "coordinates": [[[80, 35], [110, 35], [110, 46], [80, 46], [80, 35]]],
                                },
                            }
                        ],
                    },
                ),
                LayerRecord.create(
                    layer_id="visual_query_prefecture_population_2020_topd20",
                    name="Population Top20",
                    kind="vector",
                    source="visual_query",
                    geometry_type="Polygon",
                ),
                LayerRecord.create(
                    layer_id="kept_layer",
                    name="Keep me",
                    kind="vector",
                    source="builtin",
                    geometry_type="Point",
                ),
            ]
            state_file.write_text(
                json.dumps(
                    {
                        "projects": {project.project_id: project.to_dict()},
                        "jobs": {},
                        "artifacts": {},
                    }
                ),
                encoding="utf-8",
            )

            store = RuntimeStore(state_file)
            restored = store.get_project(project.project_id)

            self.assertEqual([layer.layer_id for layer in restored.layers], ["kept_layer"])
            self.assertNotIn("population_distribution", restored.enabled_templates)
            self.assertIn("population_density", restored.enabled_templates)
            self.assertEqual(restored.active_layer_id, "")
            persisted = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertEqual(
                [layer["layer_id"] for layer in persisted["projects"][project.project_id]["layers"]],
                ["kept_layer"],
            )
