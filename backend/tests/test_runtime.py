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

    def test_list_projects_returns_existing_projects(self) -> None:
        runtime, _store, project_id = self.build_runtime()

        result = runtime.list_projects()

        self.assertEqual(result["status"], "success")
        self.assertTrue(any(project["project_id"] == project_id for project in result["items"]))

    def test_dataset_catalog_exposes_one_map_assets(self) -> None:
        runtime, _store, _project_id = self.build_runtime()

        catalog = runtime.list_dataset_catalog()

        self.assertEqual(catalog["status"], "success")
        ids = {item["id"] for item in catalog["items"]}
        self.assertIn("china_province_population_density", ids)
        china = next(item for item in catalog["items"] if item["id"] == "china_province_population_density")
        self.assertTrue(china["source"].startswith("builtin:one_map/"))
        self.assertTrue(china["includes_taiwan"])
        self.assertIn("density", china["fields"])
        world_csv = next(item for item in catalog["items"] if item["id"] == "world_population_by_country")
        self.assertEqual(world_csv["format"], "csv")
        self.assertEqual(world_csv["geometry_source"], "world_countries")
        self.assertEqual(world_csv["join_key"], "region_code")

    def test_get_catalog_dataset_data_serves_geojson_without_store_writes(self) -> None:
        runtime, store, project_id = self.build_runtime()
        layers_before = len(store.get_project(project_id).layers)  # type: ignore[union-attr]

        result = runtime.get_catalog_dataset_data("china_province_population_density")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["dataset"]["id"], "china_province_population_density")
        self.assertEqual(result["data"]["type"], "FeatureCollection")
        self.assertGreater(len(result["data"]["features"]), 30)
        self.assertEqual(len(store.get_project(project_id).layers), layers_before)  # type: ignore[union-attr]

    def test_get_catalog_dataset_data_exposes_migration_flows(self) -> None:
        runtime, _store, _project_id = self.build_runtime()

        result = runtime.get_catalog_dataset_data("china_migration_flows")

        features = result["data"]["features"]
        self.assertEqual(len(features), 4)
        self.assertTrue(all("migrants" in feature["properties"] for feature in features))

    def test_get_catalog_dataset_data_rejects_unknown_dataset(self) -> None:
        runtime, _store, _project_id = self.build_runtime()

        with self.assertRaises(KeyError):
            runtime.get_catalog_dataset_data("no_such_dataset")

    def test_add_catalog_dataset_layer_materializes_geojson_layer(self) -> None:
        runtime, store, project_id = self.build_runtime()

        result = runtime.add_catalog_dataset_layer(project_id, "china_province_population_density")

        self.assertEqual(result["status"], "success")
        layer = result["layer"]
        self.assertEqual(layer["source"], "one_map_catalog")
        self.assertEqual(layer["metadata"]["catalog_id"], "china_province_population_density")
        self.assertTrue(layer["visible"])
        self.assertGreater(len(layer["data"]["features"]), 0)
        self.assertEqual(store.get_project(project_id).active_layer_id, layer["layer_id"])  # type: ignore[union-attr]
        taiwan = next(
            feature
            for feature in layer["data"]["features"]
            if str(feature.get("properties", {}).get("adcode")) == "710000"
        )
        self.assertEqual(taiwan["properties"]["population"], 23561236)

    def test_missing_taiwan_metrics_use_neutral_no_data_style(self) -> None:
        runtime, _store, project_id = self.build_runtime()

        for dataset_id, field in (
            ("china_aging_rate_province", "aging_rate"),
            ("china_province_gdp_per_capita", "gdp_per_capita_2020"),
        ):
            layer = runtime.add_catalog_dataset_layer(project_id, dataset_id)["layer"]
            taiwan = next(
                feature
                for feature in layer["data"]["features"]
                if feature.get("properties", {}).get("name") == "台湾省"
            )
            self.assertIsNone(taiwan["properties"][field])
            self.assertEqual(taiwan["properties"]["__fillColor"], "#94a3b8")
            self.assertEqual(taiwan["properties"].get("data_status"), "同口径数据暂缺")

    def test_world_population_labels_taiwan_as_china_province(self) -> None:
        runtime, _store, project_id = self.build_runtime()

        layer = runtime.add_catalog_dataset_layer(project_id, "world_population_by_country")["layer"]
        taiwan = next(
            feature
            for feature in layer["data"]["features"]
            if feature.get("properties", {}).get("region_code") == "TWN"
        )
        self.assertEqual(taiwan["properties"]["name"], "中国台湾省")
        self.assertEqual(taiwan["properties"]["name_en"], "Taiwan, China")

    def test_add_catalog_dataset_layer_materializes_joined_csv_layer(self) -> None:
        runtime, store, project_id = self.build_runtime()

        result = runtime.add_catalog_dataset_layer(project_id, "world_population_by_country")

        self.assertEqual(result["status"], "success")
        layer = result["layer"]
        self.assertEqual(layer["source"], "one_map_catalog")
        self.assertEqual(layer["metadata"]["catalog_id"], "world_population_by_country")
        self.assertTrue(layer["metadata"]["materialized_from_csv"])
        self.assertEqual(layer["metadata"]["geometry_source"], "world_countries")
        self.assertEqual(layer["metadata"]["join_key"], "region_code")
        self.assertEqual(layer["geometry_type"], "MultiPolygon")
        self.assertGreater(len(layer["data"]["features"]), 0)
        canada = next(
            feature
            for feature in layer["data"]["features"]
            if str(feature.get("properties", {}).get("region_code")) == "CAN"
        )
        self.assertEqual(canada["properties"]["population"], 37589262)
        self.assertEqual(store.get_project(project_id).active_layer_id, layer["layer_id"])  # type: ignore[union-attr]

    def test_add_catalog_dataset_layer_rejects_unjoined_csv_layer(self) -> None:
        runtime, _store, project_id = self.build_runtime()

        with self.assertRaisesRegex(ValueError, "geometry_source and join_key"):
            runtime.add_catalog_dataset_layer(project_id, "china_city_population_2020")

    def test_builtin_world_population_csv_has_join_defaults_without_catalog_metadata(self) -> None:
        runtime, _store, _project_id = self.build_runtime()
        item = runtime.one_map_catalog_service.get_item("world_population_by_country")
        legacy_item = {key: value for key, value in item.items() if key not in {"geometry_source", "join_key"}}

        payload = runtime._materialize_csv_catalog_payload(legacy_item)

        self.assertEqual(payload["type"], "FeatureCollection")
        self.assertGreater(len(payload["features"]), 0)
        canada = next(
            feature
            for feature in payload["features"]
            if str(feature.get("properties", {}).get("region_code")) == "CAN"
        )
        self.assertEqual(canada["properties"]["population"], 37589262)

    def test_catalog_layer_statistics_sums_population_in_selection(self) -> None:
        runtime, _store, project_id = self.build_runtime()
        runtime.add_catalog_dataset_layer(project_id, "china_province_population_density")
        selection = {
            "type": "Polygon",
            "coordinates": [[[-180, -80], [180, -80], [180, 80], [-180, 80], [-180, -80]]],
        }

        result = runtime.summarize_catalog_layers(project_id, geometry=selection)

        self.assertEqual(result["status"], "success")
        self.assertTrue(result["geometry_used"])
        self.assertGreater(result["totals"]["matched_count"], 0)
        self.assertGreater(result["totals"]["total_population"], 0)
        self.assertEqual(result["layers"][0]["method"], "area_weighted_intersection")
        rows = result["layers"][0]["rows"]
        self.assertTrue(any(row["region_code"] == "710000" and row["population"] for row in rows))
        self.assertTrue(all("coverage_ratio" in row for row in rows))

    def test_joined_csv_layer_statistics_use_area_weighted_population(self) -> None:
        runtime, _store, project_id = self.build_runtime()
        runtime.add_catalog_dataset_layer(project_id, "world_population_by_country")
        selection = {
            "type": "Polygon",
            "coordinates": [[[-100, 45], [-52, 45], [-52, 70], [-100, 70], [-100, 45]]],
        }

        result = runtime.summarize_catalog_layers(project_id, geometry=selection)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["layers"][0]["method"], "area_weighted_intersection")
        self.assertGreater(result["totals"]["total_population"], 0)
        rows = result["layers"][0]["rows"]
        canada = next(row for row in rows if row["region_code"] == "CAN")
        self.assertGreater(canada["population"], 0)
        self.assertLess(canada["population"], canada["source_population"])
        self.assertGreater(canada["coverage_ratio"], 0)
        self.assertLess(canada["coverage_ratio"], 1)


if __name__ == "__main__":
    unittest.main()
