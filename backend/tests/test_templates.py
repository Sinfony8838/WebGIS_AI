from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.app.config import AppConfig
from backend.app.services.templates import TemplateService
from backend.app.store import RuntimeStore


class TemplateServiceTest(unittest.TestCase):
    def build_service(self) -> tuple[AppConfig, RuntimeStore, TemplateService, str]:
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
        project = store.create_project(base_map=config.default_basemap())
        service = TemplateService(config, store)
        self.addCleanup(temp_dir.cleanup)
        return config, store, service, project.project_id

    def test_list_templates_contains_course_metadata_and_stable_order(self) -> None:
        _config, _store, service, _project_id = self.build_service()

        items = service.list_templates()["items"]

        self.assertEqual(items[0]["template_id"], "generic_classroom_pack")
        self.assertEqual(items[0]["chapter_title"], "通用课堂")
        self.assertEqual(items[0]["unit_title"], "区域认知基础")
        self.assertEqual(items[1]["template_id"], "population_classroom_pack")
        self.assertEqual(items[1]["chapter_title"], "人口专题")
        self.assertEqual(items[1]["unit_title"], "人口空间格局")
        self.assertIn("template_order", items[1])

    def test_population_classroom_pack_contains_four_demo_layers(self) -> None:
        _config, _store, service, project_id = self.build_service()
        result = service.apply_template(project_id, "population_classroom_pack")
        layer_names = [layer["name"] for layer in result["layers"]]
        self.assertIn("人口分布", layer_names)
        self.assertIn("人口密度", layer_names)
        self.assertIn("人口迁移", layer_names)
        self.assertIn("胡焕庸线对比", layer_names)

    def test_template_report_path_is_unique_across_repeated_runs(self) -> None:
        _config, _store, service, project_id = self.build_service()
        first = service.apply_template(project_id, "generic_classroom_pack")
        second = service.apply_template(project_id, "generic_classroom_pack")

        self.assertNotEqual(first["artifacts"][0]["path"], second["artifacts"][0]["path"])
