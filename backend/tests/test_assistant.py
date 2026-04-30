from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend.app.config import AppConfig
from backend.app.models import LayerRecord, ProjectRecord
from backend.app.services.assistant import ASSISTANT_TOOL_SCHEMA, AssistantService


class AssistantServiceTest(unittest.TestCase):
    def build_project(self, config: AppConfig | None = None) -> ProjectRecord:
        project = ProjectRecord.create(base_map=(config or AppConfig()).default_basemap())
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
            "切换到卫星底图，搜索当前区域内港口并解释区位优势",
            project,
            {"center": [104, 35], "zoom": 5, "extent": [100, 20, 125, 40]},
        )
        tool_names = [item["tool_name"] for item in plan["actions"]]
        self.assertIn("switch_basemap", tool_names)
        self.assertIn("search_poi", tool_names)
        self.assertIn("explain_current_view", tool_names)

    def test_plan_actions_can_switch_to_weather_basemap_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.dict(
            os.environ,
            {"WEBGIS_AI_OPENWEATHERMAP_API_KEY": "demo-weather-key"},
            clear=True,
        ):
            config = AppConfig(root_dir=Path(temp_dir))
            service = AssistantService(config)
            project = self.build_project(config)
            plan = service.plan_actions("\u5207\u6362\u5230\u5929\u6c14\u5730\u56fe", project)

            self.assertEqual(plan["actions"][0]["tool_name"], "switch_basemap")
            self.assertEqual(plan["actions"][0]["tool_params"]["basemap_id"], "weather_precipitation")

    def test_plan_actions_can_switch_to_specific_weather_basemap(self) -> None:
        service = AssistantService(AppConfig())
        project = self.build_project()

        cloud_plan = service.plan_actions("\u5207\u6362\u5230\u4e91\u56fe", project)
        wind_plan = service.plan_actions("\u5207\u6362\u5230\u98ce\u901f\u5929\u6c14\u56fe", project)

        self.assertEqual(cloud_plan["actions"][0]["tool_params"]["basemap_id"], "weather_clouds")
        self.assertEqual(wind_plan["actions"][0]["tool_params"]["basemap_id"], "weather_wind")

    def test_plan_actions_can_focus_existing_search_result(self) -> None:
        service = AssistantService(AppConfig())
        project = self.build_project()
        plan = service.plan_actions("定位到宁波港", project, {"zoom": 7, "extent": [100, 20, 125, 40]})
        tool_names = [item["tool_name"] for item in plan["actions"]]
        self.assertIn("set_view", tool_names)

    def test_voice_actions_can_focus_builtin_anchor(self) -> None:
        service = AssistantService(AppConfig())
        project = self.build_project()
        plan = service.plan_voice_actions("我们把目光转向上海区域", project, {"zoom": 4, "extent": [78, 18, 132, 50]})
        self.assertEqual(plan["actions"][0]["tool_name"], "set_view")
        self.assertEqual(plan["actions"][0]["tool_params"]["center"], [121.47, 31.23])
        self.assertEqual(plan["actions"][0]["tool_params"]["zoom"], 8)

    def test_voice_actions_can_switch_population_distribution_template(self) -> None:
        service = AssistantService(AppConfig())
        project = self.build_project()
        plan = service.plan_voice_actions("来看人口分布图", project)
        self.assertEqual(plan["actions"][0]["tool_name"], "apply_template")
        self.assertEqual(plan["actions"][0]["tool_params"]["template_id"], "population_distribution")

    def test_voice_actions_can_request_explanation(self) -> None:
        service = AssistantService(AppConfig())
        project = self.build_project()
        plan = service.plan_voice_actions("为什么人口分布呈现这种样式", project)
        self.assertEqual(plan["actions"][0]["tool_name"], "explain_current_view")

    def test_voice_actions_return_clarification_for_unmatched_input(self) -> None:
        service = AssistantService(AppConfig())
        project = self.build_project()
        plan = service.plan_voice_actions("嗯这个那个", project)
        self.assertEqual(plan["actions"], [])
        self.assertIn("没听清", plan["assistant_message"])

    def test_compose_measurement_scales_width_by_latitude(self) -> None:
        service = AssistantService(AppConfig())
        equator = service.compose_measurement([100, -1, 110, 1])
        high_lat = service.compose_measurement([100, 59, 110, 61])

        self.assertIn("东西约 1113 千米", equator)
        self.assertIn("东西约 557 千米", high_lat)


if __name__ == "__main__":
    unittest.main()
