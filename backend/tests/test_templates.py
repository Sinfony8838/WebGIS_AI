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

    def test_population_classroom_pack_contains_four_demo_layers(self) -> None:
        _config, _store, service, project_id = self.build_service()
        result = service.apply_template(project_id, "population_classroom_pack")
        layer_names = [layer["name"] for layer in result["layers"]]
        self.assertIn("人口分布（省级）", layer_names)
        self.assertIn("人口密度（省级）", layer_names)
        self.assertIn("人口迁移", layer_names)
        self.assertIn("胡焕庸线对比", layer_names)

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

    def test_template_report_path_is_unique_across_repeated_runs(self) -> None:
        _config, _store, service, project_id = self.build_service()
        first = service.apply_template(project_id, "population_classroom_pack")
        second = service.apply_template(project_id, "population_classroom_pack")

        self.assertNotEqual(first["artifacts"][0]["path"], second["artifacts"][0]["path"])

    def test_population_colors_encode_density_and_symbols_stay_inside_provinces(self) -> None:
        from shapely.geometry import shape
        _, store, service, project_id = self.build_service()
        service.apply_template(project_id, "population_classroom_pack")
        layers = {layer.layer_id: layer for layer in store.get_project(project_id).layers}
        regions = layers["builtin_population_regions"]
        by_name = {f["properties"]["short_name"]: f for f in regions.data["features"]}
        self.assertEqual(regions.metadata["metric"], "density")
        # A populous but sparse province must not receive the dark high-density colour.
        for feature in regions.data["features"]:
            props = feature["properties"]
            if props["density"] is None:
                self.assertEqual(props["__fillColor"], "#dbe1e6")
                continue
            if props["density"] < 10:
                self.assertEqual(props["__fillColor"], "#e8f4f2")
            if props["density"] >= 800:
                self.assertEqual(props["__fillColor"], "#07575f")
        points = layers["builtin_population_density"].data["features"]
        self.assertGreater(len(points), 30)
        for point in points:
            region = by_name[point["properties"]["name"]]
            self.assertTrue(shape(region["geometry"]).covers(shape(point["geometry"])))
        self.assertGreater(len({f["properties"]["__radius"] for f in points}), 3)
