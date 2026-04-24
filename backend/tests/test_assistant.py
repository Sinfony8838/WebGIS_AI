from __future__ import annotations

import unittest

from backend.app.config import AppConfig
from backend.app.models import LayerRecord, ProjectRecord
from backend.app.services.assistant import ASSISTANT_TOOL_SCHEMA, AssistantService


class AssistantServiceTest(unittest.TestCase):
    def build_project(self) -> ProjectRecord:
        project = ProjectRecord.create(base_map=AppConfig().default_basemap())
        project.layers = [
            LayerRecord.create(
                layer_id="builtin_population_regions",
                name="人口分布",
                kind="vector",
                source="builtin",
                geometry_type="Polygon",
                visible=True,
            ),
            LayerRecord.create(
                layer_id="poi_search_results",
                name="POI：港口",
                kind="vector",
                source="search",
                geometry_type="Point",
                visible=True,
                data={
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {"name": "宁波港", "district": "浙江"},
                            "geometry": {"type": "Point", "coordinates": [121.8, 29.9]},
                        }
                    ],
                },
                metadata={"keyword": "港口"},
            ),
        ]
        project.active_layer_id = "builtin_population_regions"
        return project

    def test_tool_schema_contains_required_tools(self) -> None:
        tool_names = {tool["name"] for tool in ASSISTANT_TOOL_SCHEMA}
        self.assertIn("style_layer", tool_names)
        self.assertIn("apply_template", tool_names)
        self.assertIn("explain_current_view", tool_names)
        self.assertIn("switch_basemap", tool_names)
        self.assertIn("search_poi", tool_names)

    def test_plan_actions_prefers_template_and_explanation(self) -> None:
        service = AssistantService(AppConfig())
        project = self.build_project()
        plan = service.plan_actions("切换到人口迁移模板并解释当前地图", project, {"center": [104, 35], "extent": [78, 18, 132, 50]})
        tool_names = [item["tool_name"] for item in plan["actions"]]
        self.assertIn("apply_template", tool_names)
        self.assertIn("explain_current_view", tool_names)

    def test_plan_actions_can_style_active_layer(self) -> None:
        service = AssistantService(AppConfig())
        project = self.build_project()
        plan = service.plan_actions("把当前图层改成黄色", project)
        self.assertEqual(plan["actions"][0]["tool_name"], "style_layer")

    def test_plan_actions_can_switch_basemap_and_search_poi(self) -> None:
        service = AssistantService(AppConfig())
        project = self.build_project()
        plan = service.plan_actions(
            "切换到卫星底图，搜索当前区域内港口并解释区位价值",
            project,
            {"center": [104, 35], "zoom": 5, "extent": [100, 20, 125, 40]},
        )
        tool_names = [item["tool_name"] for item in plan["actions"]]
        self.assertIn("switch_basemap", tool_names)
        self.assertIn("search_poi", tool_names)
        self.assertIn("explain_current_view", tool_names)

    def test_plan_actions_can_focus_existing_search_result(self) -> None:
        service = AssistantService(AppConfig())
        project = self.build_project()
        plan = service.plan_actions("定位到宁波港", project, {"zoom": 7, "extent": [100, 20, 125, 40]})
        tool_names = [item["tool_name"] for item in plan["actions"]]
        self.assertIn("set_view", tool_names)

    def test_compose_measurement_scales_width_by_latitude(self) -> None:
        service = AssistantService(AppConfig())
        equator = service.compose_measurement([100, -1, 110, 1])
        high_lat = service.compose_measurement([100, 59, 110, 61])

        self.assertIn("东西约 1113 千米", equator)
        self.assertIn("东西约 557 千米", high_lat)
