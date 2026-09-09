from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.app.models import LayerRecord, LessonRecord, ProjectRecord
from backend.app.store import RuntimeStore


class RuntimeStoreTest(unittest.TestCase):
    def test_new_view_does_not_retain_bounds_from_another_scene(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "state.json"
            store = RuntimeStore(path)
            project_id = store.create_project(name="视野同步").project_id
            shanghai = {"center": [121.5, 31.2], "zoom": 12, "extent": [121.4, 31.1, 121.6, 31.3]}
            store.set_view(project_id, shanghai)
            store.set_view(project_id, {"center": [15, 20], "zoom": 2})
            self.assertNotIn("extent", store.get_project(project_id).view)
            self.assertNotIn("extent", RuntimeStore(path).get_project(project_id).view)
            # An explicitly supplied current extent remains authoritative.
            world = [-165, -60, 180, 85]
            store.set_view(project_id, {"center": [15, 20], "extent": world})
            store.set_view(project_id, {})
            self.assertEqual(store.get_project(project_id).view["extent"], world)
            store.set_view(project_id, {"zoom": 3})
            self.assertNotIn("extent", store.get_project(project_id).view)

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


    def test_delete_layer_removes_layer_and_resets_active(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = RuntimeStore(Path(temp_dir) / "state.json")
            project = store.create_project(name="图层删除")
            first = LayerRecord.create(layer_id="layer_a", name="图层A", kind="vector", source="builtin", geometry_type="Point")
            second = LayerRecord.create(layer_id="layer_b", name="图层B", kind="vector", source="builtin", geometry_type="Point")
            store.upsert_layer(project.project_id, first)
            store.upsert_layer(project.project_id, second)
            store.patch_layer(project.project_id, "layer_b", {"active": True})
            self.assertEqual(store.get_project(project.project_id).active_layer_id, "layer_b")

            removed = store.delete_layer(project.project_id, "layer_b")
            self.assertEqual(removed.layer_id, "layer_b")
            remaining = store.get_project(project.project_id)
            self.assertEqual([item.layer_id for item in remaining.layers], ["layer_a"])
            self.assertNotEqual(remaining.active_layer_id, "layer_b")

            with self.assertRaises(KeyError):
                store.delete_layer(project.project_id, "layer_b")

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

    def test_reload_retains_all_projects_without_touching_runtime_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir) / "state" / "runtime.json"
            store = RuntimeStore(state_file)
            created_ids = {store.create_project(name=f"Project {index}").project_id for index in range(9)}

            archive_dir = state_file.parent / "runtime_archive"
            archive_dir.mkdir()
            marker = archive_dir / "existing-archive.json"
            marker.write_text('{"archived": true}', encoding="utf-8")

            reloaded = RuntimeStore(state_file)

            self.assertEqual(set(reloaded.projects), created_ids)
            self.assertEqual(marker.read_text(encoding="utf-8"), '{"archived": true}')

    def test_assign_unowned_records_is_idempotent_and_preserves_builtins(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir) / "state.json"
            store = RuntimeStore(state_file)
            project = store.create_project(name="历史项目")
            manual = LessonRecord.create(title="历史课时", source="manual")
            builtin = LessonRecord.create(title="内置课时", source="builtin")
            store.upsert_lesson(manual)
            store.upsert_lesson(builtin)

            first = store.assign_unowned_records("user_bootstrap")
            second = store.assign_unowned_records("user_other")

            self.assertEqual(first, {"projects": 1, "lessons": 1})
            self.assertEqual(second, {"projects": 0, "lessons": 0})
            self.assertEqual(store.get_project(project.project_id).owner_user_id, "user_bootstrap")
            self.assertEqual(store.get_lesson(manual.lesson_id).owner_user_id, "user_bootstrap")
            self.assertEqual(store.get_lesson(builtin.lesson_id).owner_user_id, "")
