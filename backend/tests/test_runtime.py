from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.app.config import AppConfig
from backend.app.models import LayerRecord
from backend.app.runtime import WebGISRuntime
from backend.app.store import RuntimeStore


class WebGISRuntimeTest(unittest.TestCase):
    def build_runtime(self) -> tuple[WebGISRuntime, RuntimeStore, str]:
        temp_dir = tempfile.TemporaryDirectory()
        root_dir = Path(__file__).resolve().parents[2]
        config = AppConfig(root_dir=root_dir)
        config.data_dir = Path(temp_dir.name) / "backend" / "data"
        config.state_dir = config.data_dir / "state"
        config.uploads_dir = config.data_dir / "uploads"
        config.outputs_dir = config.data_dir / "outputs"
        config.state_file = config.state_dir / "runtime.json"
        config.knowledge_dir = Path(temp_dir.name) / "backend" / "app" / "data" / "builtin" / "knowledge"
        config.knowledge_dir.mkdir(parents=True, exist_ok=True)
        config.ensure_dirs()
        store = RuntimeStore(config.state_file)
        runtime = WebGISRuntime(config=config, store=store)
        project = runtime.create_project()
        self.addCleanup(temp_dir.cleanup)
        return runtime, store, project["project_id"]

    def test_upload_dataset_marks_job_failed_on_validation_error(self) -> None:
        runtime, store, project_id = self.build_runtime()

        with self.assertRaises(ValueError):
            runtime.upload_dataset(project_id, "broken.csv", b"name,lon,lat\nA,nope,95\n")

        job = next(iter(store.jobs.values()))
        self.assertEqual(job.status, "failed")
        self.assertIn("valid coordinate", job.error)

    def test_export_snapshot_marks_job_failed_on_invalid_data_url(self) -> None:
        runtime, store, project_id = self.build_runtime()

        with self.assertRaises(ValueError):
            runtime.export_snapshot(project_id, "classroom snapshot", "not-a-data-url")

        job = next(iter(store.jobs.values()))
        self.assertEqual(job.status, "failed")
        self.assertIn("data URL", job.error)

    def test_register_layer_to_knowledge_base(self) -> None:
        runtime, store, project_id = self.build_runtime()
        layer = LayerRecord.create(
            layer_id="upload_ports_layer",
            name="Port Distribution",
            kind="vector",
            source="upload",
            geometry_type="Point",
            metadata={"source_file": "ports.csv"},
        )
        store.upsert_layer(project_id, layer)

        result = runtime.kb_register_layer(
            project_id,
            "upload_ports_layer",
            {"topic": "coastal_economy", "region": "china_coast", "keywords": ["port", "location"]},
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["item"]["topic"], "coastal_economy")
        self.assertTrue(result["item"]["dataset_refs"])

    def test_kb_material_link_resource_search_and_lesson_resources(self) -> None:
        runtime, _store, project_id = self.build_runtime()
        item = runtime.kb_upsert_item(
            {
                "id": "coast_demo",
                "title": "Coast Demo",
                "topic": "regional",
                "region": "coast",
                "summary": "Coast teaching content",
            }
        )["item"]

        material = runtime.kb_link_material(
            item["id"],
            "https://example.edu/coast.html",
            title="Coast animation",
            material_type="animation",
            region_binding={"name": "coast"},
        )["material"]

        search = runtime.resource_search("Coast", scope="all", limit=8)
        self.assertEqual(search["status"], "success")
        self.assertTrue(any(row["id"] == f"material:{material['id']}" for row in search["items"]))

        saved = runtime.save_lesson_resource_set(
            project_id,
            {
                "title": "Lesson 1",
                "item_ids": [item["id"]],
                "material_ids": [material["id"]],
                "region_bindings": [{"name": "coast"}],
                "active": True,
            },
        )
        self.assertEqual(saved["item"]["title"], "Lesson 1")
        listed = runtime.list_lesson_resources(project_id)
        self.assertEqual(listed["active_lesson_resource_set_id"], saved["item"]["id"])

    def test_kb_material_upload_rejects_unsupported_suffix(self) -> None:
        runtime, _store, _project_id = self.build_runtime()
        runtime.kb_upsert_item({"id": "upload_demo", "title": "Upload Demo", "summary": "demo"})

        with self.assertRaises(ValueError):
            runtime.kb_upload_material("upload_demo", "script.exe", b"bad")

    def test_health_exposes_backend_gis_workflow_not_qgis_assistant(self) -> None:
        runtime, _store, _project_id = self.build_runtime()

        health = runtime.health()

        self.assertIn("gis_workflow", health)
        self.assertEqual(health["gis_workflow"]["engine"], "pyqgis_worker")
        self.assertNotIn("qgis", health)
        self.assertNotIn("pyqgis_workflow", health)


if __name__ == "__main__":
    unittest.main()
