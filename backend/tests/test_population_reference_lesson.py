import unittest


class PopulationReferenceLessonTest(unittest.TestCase):
    def build_runtime(self):
        from tests.test_lessons import LessonServiceTest
        return LessonServiceTest.build_runtime(self)

    def test_reference_sequence_and_actual_scene_transitions(self):
        runtime, store, project_id = self.build_runtime()
        lesson = store.get_lesson("lesson_builtin_population_shanghai_world")
        self.assertEqual(runtime.classroom.list_lessons()["items"][0]["lesson_id"], lesson.lesson_id)
        self.assertEqual([stage["stage_id"] for stage in lesson.stages], ["shanghai_intro", "concept", "shanghai_inquiry", "shanghai_verify", "china_inquiry", "china_explain", "world_inquiry", "summary"])
        self.assertEqual(sum(stage["minutes"] for stage in lesson.stages), 40)
        for stage in lesson.stages:
            result = runtime.classroom.apply_lesson_scene(project_id, lesson.lesson_id, stage["stage_id"])
            self.assertEqual(result["status"], "success")
            project = store.get_project(project_id)
            self.assertEqual(project.base_map["id"], stage["scene"]["basemap_id"])
            visible = {layer.layer_id for layer in project.layers if layer.visible}
            if stage["stage_id"].startswith("shanghai"):
                self.assertNotIn("builtin_population_regions", visible)
            if stage["stage_id"] == "china_inquiry":
                self.assertNotIn("generated_hu_line", visible)
            if stage["stage_id"] == "china_explain":
                self.assertIn("generated_hu_line", visible)
            if stage["stage_id"] in {"concept", "world_inquiry"}:
                self.assertFalse(any(layer.visible and layer.source == "one_map_catalog" for layer in project.layers))
        self.assertTrue(lesson.plan["homework"]["basic"])

    def test_scientific_maps_have_explicit_service_resolution_limits(self):
        runtime, _, _ = self.build_runtime()
        for name, maximum in [("nasa_nightlights_2016", 8), ("nasa_population_2020", 7)]:
            descriptor = runtime.config.basemap_by_id(name)["layers"][0]
            self.assertEqual(descriptor["max_zoom"], maximum)
            self.assertFalse(descriptor["usable_in_3d"])
            self.assertIn("gibs.earthdata.nasa.gov", descriptor["urls"][0])

    def test_classroom_returns_recorded_stage_and_reference_answers(self):
        runtime, store, project_id = self.build_runtime()
        lesson = store.get_lesson("lesson_builtin_population_shanghai_world")
        created = runtime.classroom.create_class_session(lesson.lesson_id, project_id)["session"]
        entered = runtime.classroom.enter_session_stage(created["session_id"], "shanghai_inquiry")
        self.assertEqual(entered["session"]["current_stage_id"], "shanghai_inquiry")
        self.assertTrue(any(event["type"] == "stage_enter" for event in entered["session"]["events"]))
        question = lesson.find_stage("shanghai_inquiry")["questions"][0]
        self.assertIn("32357", question["answer"])
        self.assertIn("538", question["answer"])
        self.assertIn("tjj.sh.gov.cn", question["material"])
        self.assertTrue(all(q.get("answer") for stage in lesson.stages for q in stage["questions"]))

    def test_previous_assistant_annotations_are_hidden_without_deletion(self):
        from backend.app.models import LayerRecord
        runtime, store, project_id = self.build_runtime()
        annotation = LayerRecord(layer_id="assistant_annotations", name="课堂标注", kind="annotation", source="generated", geometry_type="Point", data={"type": "FeatureCollection", "features": []})
        store.upsert_layer(project_id, annotation)
        runtime.classroom.apply_lesson_scene(project_id, "lesson_builtin_population_shanghai_world", "world_inquiry")
        saved = next(layer for layer in store.get_project(project_id).layers if layer.layer_id == "assistant_annotations")
        self.assertFalse(saved.visible)
        runtime.classroom.lesson_service.apply_stage_scene_data(project_id, {"stage_id": "manual", "scene": {"layer_visibility": {"assistant_annotations": True}}})
        self.assertTrue(next(layer for layer in store.get_project(project_id).layers if layer.layer_id == "assistant_annotations").visible)
