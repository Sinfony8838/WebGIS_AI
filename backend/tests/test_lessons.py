from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.app.config import AppConfig
from backend.app.runtime import WebGISRuntime
from backend.app.services.lessons import LESSON_ANNOTATION_LAYER_ID
from backend.app.store import RuntimeStore


BUILTIN_LESSON_ID = "lesson_builtin_population_distribution"


class LessonServiceTest(unittest.TestCase):
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

    def test_builtin_lesson_is_seeded(self) -> None:
        runtime, store, _ = self.build_runtime()

        lesson = store.get_lesson(BUILTIN_LESSON_ID)
        self.assertIsNotNone(lesson)
        self.assertEqual(lesson.source, "builtin")
        self.assertGreaterEqual(len(lesson.stages), 8)
        self.assertEqual(sum(int(stage.get("minutes") or 0) for stage in lesson.stages), 40)
        self.assertEqual(lesson.find_stage("s7")["title"], "当堂复盘：证据链定格")
        self.assertEqual(lesson.find_stage("s8")["title"], "当堂巩固：四步法检测")
        self.assertEqual(lesson.metadata.get("builtin_version"), "8")
        listing = runtime.classroom.list_lessons()
        self.assertTrue(any(item["lesson_id"] == BUILTIN_LESSON_ID for item in listing["items"]))

        for stage in lesson.stages:
            self.assertTrue(stage["script"], stage["stage_id"])
            self.assertTrue(stage["brainstorm"], stage["stage_id"])
            self.assertEqual(len(stage["brainstorm"]["regions"]), 5, stage["stage_id"])
            self.assertTrue(stage["brainstorm"]["prompt"], stage["stage_id"])

    def test_shanghai_stage_replaces_national_thematic_layers(self) -> None:
        runtime, store, project_id = self.build_runtime()
        runtime.classroom.apply_lesson_scene(project_id, BUILTIN_LESSON_ID, "s4")
        runtime.add_catalog_dataset_layer(project_id, "china_aging_rate_province")
        runtime.classroom.apply_lesson_scene(project_id, BUILTIN_LESSON_ID, "s6")
        project = store.get_project(project_id)
        visible = {layer.layer_id: layer for layer in project.layers if layer.visible}
        self.assertNotIn("builtin_population_regions", visible)
        self.assertNotIn("builtin_population_density", visible)
        self.assertNotIn("generated_hu_line", visible)
        self.assertNotIn("one_map_china_aging_rate_province", visible)
        layer = visible["one_map_shanghai_population_density"]
        self.assertEqual(len(layer.data["features"]), 16)
        self.assertEqual(layer.opacity, 1.0)
        self.assertEqual(sum(f["properties"]["population"] for f in layer.data["features"]), 24870895)
        for feature in layer.data["features"]:
            props = feature["properties"]
            self.assertAlmostEqual(props["density"], props["population"] / props["area_km2"], places=2)
        self.assertEqual(project.view["center"], [121.47, 31.23])
        runtime.classroom.apply_lesson_scene(project_id, BUILTIN_LESSON_ID, "s4")
        self.assertFalse(next(item for item in store.get_project(project_id).layers if item.layer_id == layer.layer_id).visible)

    def test_legacy_lesson_without_brainstorm_remains_readable(self) -> None:
        runtime, _store, _project_id = self.build_runtime()

        created = runtime.classroom.create_lesson(
            {
                "title": "旧课时",
                "stages": [{"stage_id": "s1", "title": "旧环节", "scene": {}, "script": ["旧知识"]}],
            }
        )

        self.assertEqual(created["stages"][0]["brainstorm"], {})

    def test_apply_stage_scene_sets_layers_view_and_basemap(self) -> None:
        runtime, store, project_id = self.build_runtime()

        result = runtime.classroom.apply_lesson_scene(project_id, BUILTIN_LESSON_ID, "s1")

        self.assertEqual(result["status"], "success")
        self.assertIn("population_distribution", result["applied_templates"])
        project = store.get_project(project_id)
        layer_map = {layer.layer_id: layer for layer in project.layers}
        self.assertIn("builtin_population_regions", layer_map)
        self.assertTrue(layer_map["builtin_population_regions"].visible)
        self.assertEqual(project.base_map.get("id"), "amap_light")
        self.assertEqual(project.view.get("zoom"), 4)

    def test_apply_stage_scene_switches_between_stages(self) -> None:
        runtime, store, project_id = self.build_runtime()

        runtime.classroom.apply_lesson_scene(project_id, BUILTIN_LESSON_ID, "s1")
        result = runtime.classroom.apply_lesson_scene(project_id, BUILTIN_LESSON_ID, "s4")

        project = store.get_project(project_id)
        layer_map = {layer.layer_id: layer for layer in project.layers}
        self.assertIn("generated_hu_line", layer_map)
        self.assertTrue(layer_map["generated_hu_line"].visible)
        self.assertTrue(layer_map["builtin_population_regions"].visible)
        annotations = layer_map.get(LESSON_ANNOTATION_LAYER_ID)
        self.assertIsNotNone(annotations)
        names = [feature["properties"]["name"] for feature in annotations.data["features"]]
        self.assertIn("黑河", names)
        self.assertIn("腾冲", names)
        # 已启用过的模板不重复应用
        self.assertNotIn("population_distribution", result["applied_templates"])

    def test_builtin_population_lesson_declares_2d_and_3d_stage_intent(self) -> None:
        runtime, _store, project_id = self.build_runtime()

        s1 = runtime.classroom.apply_lesson_scene(project_id, BUILTIN_LESSON_ID, "s1")
        s4 = runtime.classroom.apply_lesson_scene(project_id, BUILTIN_LESSON_ID, "s4")
        s5 = runtime.classroom.apply_lesson_scene(project_id, BUILTIN_LESSON_ID, "s5")
        s7 = runtime.classroom.apply_lesson_scene(project_id, BUILTIN_LESSON_ID, "s7")
        s8 = runtime.classroom.apply_lesson_scene(project_id, BUILTIN_LESSON_ID, "s8")

        self.assertEqual(s1["globe"], {"enabled": False})
        self.assertEqual(s4["globe"]["themes"], ["density_fill", "hu_line"])
        self.assertEqual(s5["globe"]["themes"], ["density_fill", "climate_zones"])
        self.assertEqual(s7["globe"]["themes"], ["density_3d", "hu_line"])
        self.assertEqual(s8["globe"], {"enabled": False})

    def test_apply_stage_scene_runs_visual_query(self) -> None:
        runtime, store, project_id = self.build_runtime()

        result = runtime.classroom.apply_lesson_scene(project_id, BUILTIN_LESSON_ID, "s3")

        self.assertIsNotNone(result["visualization"])
        project = store.get_project(project_id)
        self.assertTrue(any(layer.layer_id.startswith("visual_query_") for layer in project.layers))

    def test_stage_switch_clears_previous_visual_query_layers(self) -> None:
        runtime, store, project_id = self.build_runtime()

        runtime.classroom.apply_lesson_scene(project_id, BUILTIN_LESSON_ID, "s3")
        project = store.get_project(project_id)
        self.assertTrue(any(layer.layer_id.startswith("visual_query_") for layer in project.layers))

        runtime.classroom.apply_lesson_scene(project_id, BUILTIN_LESSON_ID, "s4")
        project = store.get_project(project_id)
        self.assertFalse(any(layer.layer_id.startswith("visual_query_") for layer in project.layers))

    def test_capture_stage_scene_updates_scene(self) -> None:
        runtime, store, _ = self.build_runtime()

        snapshot = {
            "basemap_id": "amap_vector",
            "view": {"center": [120.0, 30.0], "zoom": 7},
            "layer_visibility": {"builtin_population_regions": False},
        }
        result = runtime.classroom.capture_lesson_scene(BUILTIN_LESSON_ID, "s1", snapshot)

        self.assertEqual(result["scene"]["basemap_id"], "amap_vector")
        lesson = store.get_lesson(BUILTIN_LESSON_ID)
        stage = lesson.find_stage("s1")
        self.assertEqual(stage["scene"]["view"]["zoom"], 7)
        self.assertFalse(stage["scene"]["layer_visibility"]["builtin_population_regions"])

    def test_scene_globe_is_normalized_for_legacy_apply_and_capture(self) -> None:
        runtime, store, project_id = self.build_runtime()
        lesson = runtime.classroom.lesson_service.create_lesson(
            {
                "title": "globe scene test",
                "stages": [
                    {"stage_id": "legacy", "title": "legacy scene", "scene": {}},
                    {
                        "stage_id": "globe",
                        "title": "globe scene",
                        "scene": {
                            "globe": {
                                "enabled": True,
                                "themes": ["population_density", 7],
                                "camera": {"lon": 104, "lat": 35.5, "altitudeMeters": 12000000, "pitchDeg": -35, "ignored": "x"},
                            }
                        },
                    },
                ],
            }
        )

        legacy = runtime.classroom.apply_lesson_scene(project_id, lesson.lesson_id, "legacy")
        applied = runtime.classroom.apply_lesson_scene(project_id, lesson.lesson_id, "globe")
        captured = runtime.classroom.capture_lesson_scene(
            lesson.lesson_id,
            "globe",
            {"globe": {"enabled": False, "themes": ["ignored"]}},
        )

        self.assertEqual(legacy["globe"], {})
        self.assertEqual(applied["globe"], {
            "enabled": True,
            "themes": ["population_density", "7"],
            "camera": {"lon": 104.0, "lat": 35.5, "altitudeMeters": 12000000.0, "pitchDeg": -35.0},
        })
        self.assertEqual(captured["scene"]["globe"], {"enabled": False})
        stored_stage = store.get_lesson(lesson.lesson_id).find_stage("globe")
        self.assertEqual(stored_stage["scene"]["globe"], {"enabled": False})

    def test_import_from_text_heuristic_fallback(self) -> None:
        runtime, store, _ = self.build_runtime()
        runtime.classroom.lesson_service.minimax_client = None

        text = "\n".join(
            [
                "# 中国的气候课",
                "## 一、课堂导入（5分钟）",
                "展示气候类型图。",
                "中国的气候类型有哪些？",
                "## 二、探究活动（15分钟）",
                "小组讨论季风的影响。",
                "为什么东部地区夏季多雨？",
            ]
        )
        result = runtime.classroom.lesson_service.import_from_text(text)

        self.assertEqual(result["parser"], "heuristic")
        lesson = result["lesson"]
        self.assertEqual(lesson["source"], "imported")
        self.assertGreaterEqual(len(lesson["stages"]), 2)
        first_questions = lesson["stages"][0]["questions"]
        self.assertTrue(any("气候类型" in question["text"] for question in first_questions))

    def test_store_loads_legacy_state_without_lessons(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        state_file = Path(temp_dir.name) / "runtime.json"
        state_file.write_text(
            json.dumps({"projects": {}, "jobs": {}, "artifacts": {}}),
            encoding="utf-8",
        )

        store = RuntimeStore(state_file)

        self.assertEqual(store.lessons, {})
        self.assertEqual(store.class_sessions, {})

    def test_apply_stage_scene_opens_declared_catalog_layers(self) -> None:
        runtime, store, project_id = self.build_runtime()
        lesson = runtime.classroom.lesson_service.create_lesson(
            {
                "title": "catalog scene test",
                "stages": [
                    {
                        "stage_id": "s1",
                        "title": "open catalog",
                        "scene": {
                            "basemap_id": "amap_light",
                            "catalog_layers": ["china_climate_types"],
                        },
                    }
                ],
            }
        )

        result = runtime.classroom.apply_lesson_scene(project_id, lesson.lesson_id, "s1")

        self.assertEqual(result["catalog_layers"], ["china_climate_types"])
        project = store.get_project(project_id)
        catalog_layers = [
            layer
            for layer in project.layers
            if (layer.metadata or {}).get("catalog_id") == "china_climate_types"
        ]
        self.assertTrue(catalog_layers)
        self.assertTrue(catalog_layers[0].visible)

    def test_stage_scene_preloads_catalog_layers_but_shows_only_declared_focus(self) -> None:
        runtime, store, project_id = self.build_runtime()
        lesson = runtime.classroom.lesson_service.create_lesson(
            {
                "title": "catalog evidence focus test",
                "stages": [
                    {
                        "stage_id": "s1",
                        "title": "focus climate",
                        "scene": {
                            "catalog_layers": ["china_climate_types", "china_terrain_steps"],
                            "catalog_layer_focus": "china_climate_types",
                        },
                    }
                ],
            }
        )

        result = runtime.classroom.apply_lesson_scene(project_id, lesson.lesson_id, "s1")

        self.assertEqual(result["catalog_layer_focus"], "china_climate_types")
        project = store.get_project(project_id)
        visibility = {
            str((layer.metadata or {}).get("catalog_id") or ""): layer.visible
            for layer in project.layers
            if str((layer.metadata or {}).get("catalog_id") or "")
            in {"china_climate_types", "china_terrain_steps"}
        }
        self.assertEqual(visibility, {"china_climate_types": True, "china_terrain_steps": False})

    def test_stage_switch_hides_undeclared_catalog_layers(self) -> None:
        runtime, store, project_id = self.build_runtime()
        lesson = runtime.classroom.lesson_service.create_lesson(
            {
                "title": "catalog hide test",
                "stages": [
                    {"stage_id": "s1", "title": "with catalog", "scene": {"catalog_layers": ["china_climate_types"]}},
                    {"stage_id": "s2", "title": "without catalog", "scene": {"catalog_layers": []}},
                ],
            }
        )

        runtime.classroom.apply_lesson_scene(project_id, lesson.lesson_id, "s1")
        project = store.get_project(project_id)
        layer = next(
            layer
            for layer in project.layers
            if (layer.metadata or {}).get("catalog_id") == "china_climate_types"
        )
        self.assertTrue(layer.visible)

        runtime.classroom.apply_lesson_scene(project_id, lesson.lesson_id, "s2")
        project = store.get_project(project_id)
        layer = next(
            layer
            for layer in project.layers
            if (layer.metadata or {}).get("catalog_id") == "china_climate_types"
        )
        self.assertFalse(layer.visible)

    def test_catalog_layer_persists_across_stages_declaring_it(self) -> None:
        runtime, store, project_id = self.build_runtime()
        lesson = runtime.classroom.lesson_service.create_lesson(
            {
                "title": "catalog persist test",
                "stages": [
                    {"stage_id": "s1", "title": "a", "scene": {"catalog_layers": ["china_climate_types"]}},
                    {"stage_id": "s2", "title": "b", "scene": {"catalog_layers": ["china_climate_types"]}},
                ],
            }
        )

        runtime.classroom.apply_lesson_scene(project_id, lesson.lesson_id, "s1")
        runtime.classroom.apply_lesson_scene(project_id, lesson.lesson_id, "s2")
        project = store.get_project(project_id)
        layer = next(
            layer
            for layer in project.layers
            if (layer.metadata or {}).get("catalog_id") == "china_climate_types"
        )
        self.assertTrue(layer.visible)


if __name__ == "__main__":
    unittest.main()
