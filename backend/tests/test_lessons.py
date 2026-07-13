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
        listing = runtime.classroom.list_lessons()
        self.assertTrue(any(item["lesson_id"] == BUILTIN_LESSON_ID for item in listing["items"]))

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


if __name__ == "__main__":
    unittest.main()
