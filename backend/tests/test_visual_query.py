from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.app.config import AppConfig
from backend.app.models import LayerRecord, ProjectRecord
from backend.app.runtime import WebGISRuntime
from backend.app.services.visual_query import VisualQueryError, VisualQueryService
from backend.app.store import RuntimeStore


class VisualQueryServiceTest(unittest.TestCase):
    def build_service(self) -> VisualQueryService:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root_dir = Path(__file__).resolve().parents[2]
        config = AppConfig(root_dir=root_dir)
        config.data_dir = Path(temp_dir.name) / "backend" / "data"
        config.state_dir = config.data_dir / "state"
        config.uploads_dir = config.data_dir / "uploads"
        config.outputs_dir = config.data_dir / "outputs"
        config.state_file = config.state_dir / "runtime.json"
        config.ensure_dirs()
        return VisualQueryService(config)

    def test_prefecture_population_top_20(self) -> None:
        service = self.build_service()
        result = service.run(
            "project-test",
            {
                "dataset": "prefecture_population",
                "year": 2020,
                "geo_level": "prefecture",
                "metric": "population",
                "operation": "top",
                "limit": 20,
                "order": "desc",
            },
        )
        items = result["items"]
        self.assertEqual(len(items), 20)
        self.assertEqual(items[0]["name"], "重庆市")
        self.assertEqual(items[0]["value"], 32054159)
        # items must be sorted by population desc
        populations = [item["value"] for item in items]
        self.assertEqual(populations, sorted(populations, reverse=True))
        layer_dict = result["layer"]
        self.assertEqual(layer_dict["layer_id"], "visual_query_prefecture_population_2020_topd20")
        self.assertEqual(layer_dict["geometry_type"], "MultiPolygon")
        features = layer_dict["data"]["features"]
        self.assertEqual(len(features), 20)
        # Visualization metadata
        visualization = result["visualization"]
        self.assertEqual(visualization["type"], "bar")
        self.assertEqual(visualization["unit"], "人")
        self.assertEqual(visualization["items"][0]["value"], 32054159)
        # Each feature carries rank + value + style
        for feature in features:
            properties = feature["properties"]
            self.assertIn("rank", properties)
            self.assertIn("value", properties)
            self.assertIn("__fillColor", properties)
            self.assertIn("__strokeColor", properties)
            self.assertIn("unit", properties)

    def test_layer_name_and_id_include_year_and_limit(self) -> None:
        service = self.build_service()
        result = service.run(
            "project-test",
            {
                "dataset": "prefecture_population",
                "year": 2020,
                "metric": "population",
                "operation": "top",
                "limit": 20,
            },
        )
        self.assertIn("2020", result["layer"]["name"])
        self.assertIn("Top20", result["layer"]["name"])
        self.assertEqual(result["layer"]["z_index"], 80)
        self.assertEqual(result["layer"]["kind"], "vector")
        self.assertEqual(result["layer"]["source"], "generated")

    def test_unsupported_dataset_raises(self) -> None:
        service = self.build_service()
        with self.assertRaises(VisualQueryError):
            service.run(
                "project-test",
                {
                    "dataset": "unknown_dataset",
                    "metric": "population",
                    "operation": "top",
                },
            )

    def test_invalid_limit_raises(self) -> None:
        service = self.build_service()
        with self.assertRaises(VisualQueryError):
            service.run(
                "project-test",
                {
                    "dataset": "prefecture_population",
                    "metric": "population",
                    "operation": "top",
                    "limit": 0,
                },
            )

    def test_layer_record_round_trips_with_visualization_metadata(self) -> None:
        service = self.build_service()
        result = service.run(
            "project-test",
            {
                "dataset": "prefecture_population",
                "year": 2020,
                "metric": "population",
                "operation": "top",
                "limit": 20,
            },
        )
        project = ProjectRecord.create()
        layer = LayerRecord.create(
            layer_id=result["layer"]["layer_id"],
            name=result["layer"]["name"],
            kind=result["layer"]["kind"],
            source=result["layer"]["source"],
            geometry_type=result["layer"]["geometry_type"],
            data=result["layer"]["data"],
            metadata=result["layer"]["metadata"],
            style=result["layer"]["style"],
            z_index=result["layer"]["z_index"],
        )
        project.layers.append(layer)
        serialized = project.to_dict()
        visualization = serialized["layers"][0]["metadata"].get("visualization")
        self.assertIsNotNone(visualization)
        self.assertEqual(visualization["type"], "bar")
        self.assertEqual(len(visualization["items"]), 20)

    def test_runtime_executes_visual_query_end_to_end(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
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
        project_id = runtime.create_project()["project_id"]
        project = store.get_project(project_id)
        plan = runtime.assistant_service.plan_actions(
            "查询2020年地级市人口Top20", project
        )
        actions = plan["actions"]
        self.assertTrue(any(a["tool_name"] == "run_visual_query" for a in actions))
        action = next(a for a in actions if a["tool_name"] == "run_visual_query")
        result = runtime._execute_assistant_action(project_id, action, {})
        layer_dict = result["layer"]
        self.assertEqual(layer_dict["layer_id"], "visual_query_prefecture_population_2020_topd20")
        self.assertEqual(layer_dict["geometry_type"], "MultiPolygon")
        self.assertEqual(len(layer_dict["data"]["features"]), 20)
        self.assertEqual(layer_dict["data"]["features"][0]["properties"]["value"], 32054159)
        visualization = result["visualization"]
        self.assertEqual(visualization["type"], "bar")
        self.assertEqual(visualization["items"][0]["name"], "重庆市")
        persisted = [layer for layer in store.get_project(project_id).layers if layer.layer_id == layer_dict["layer_id"]]
        self.assertEqual(len(persisted), 1)
