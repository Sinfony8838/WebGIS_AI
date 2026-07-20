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

        self.assertEqual(items[0]["template_id"], "population_classroom_pack")
        self.assertEqual(items[0]["chapter_title"], "人口专题")
        self.assertEqual(items[0]["unit_title"], "人口空间格局")
        self.assertIn("template_order", items[0])
        self.assertNotIn("generic_classroom_pack", {item["template_id"] for item in items})

    def test_population_classroom_pack_contains_only_provenanced_demo_layers(self) -> None:
        _config, _store, service, project_id = self.build_service()
        result = service.apply_template(project_id, "population_classroom_pack")
        layer_names = [layer["name"] for layer in result["layers"]]
        self.assertIn("人口分布（省级）", layer_names)
        self.assertIn("人口密度（省级）", layer_names)
        self.assertNotIn("人口迁移", layer_names)
        self.assertIn("胡焕庸线对比", layer_names)

    def test_population_migration_template_is_disabled_without_flow_provenance(self) -> None:
        _config, _store, service, project_id = self.build_service()

        with self.assertRaisesRegex(ValueError, "temporarily disabled"):
            service.apply_template(project_id, "population_migration")

    def test_population_distribution_uses_real_province_boundaries(self) -> None:
        _config, store, service, project_id = self.build_service()
        service.apply_template(project_id, "population_distribution")
        layer = next(
            item for item in store.get_project(project_id).layers
            if item.layer_id == "builtin_population_regions"
        )
        features = layer.data["features"]
        # 34 real provinces instead of the 7 old rectangular region blocks
        self.assertGreaterEqual(len(features), 30)
        names = {feature["properties"].get("name") for feature in features}
        self.assertIn("河南省", names)

    def test_population_density_uses_polygon_choropleth_with_fixed_breaks(self) -> None:
        _config, store, service, project_id = self.build_service()
        service.apply_template(project_id, "population_density")
        layer = next(
            item for item in store.get_project(project_id).layers
            if item.layer_id == "builtin_population_density"
        )

        self.assertEqual(layer.geometry_type, "MultiPolygon")
        self.assertIn("固定阈值", layer.metadata["classification"])
        self.assertTrue(all("density_class" in feature["properties"] for feature in layer.data["features"]))

    def test_template_report_path_is_unique_across_repeated_runs(self) -> None:
        _config, _store, service, project_id = self.build_service()
        first = service.apply_template(project_id, "population_classroom_pack")
        second = service.apply_template(project_id, "population_classroom_pack")

        self.assertNotEqual(first["artifacts"][0]["path"], second["artifacts"][0]["path"])
