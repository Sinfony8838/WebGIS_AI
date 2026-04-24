from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.app.config import AppConfig
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
            runtime.export_snapshot(project_id, "课堂导图", "not-a-data-url")

        job = next(iter(store.jobs.values()))
        self.assertEqual(job.status, "failed")
        self.assertIn("data URL", job.error)
