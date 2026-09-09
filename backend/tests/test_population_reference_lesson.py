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

    def test_previous_poi_results_are_hidden_but_explicit_scene_can_restore_them(self):
        from backend.app.models import LayerRecord
        runtime, store, project_id = self.build_runtime()
        data = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [121.5, 31.2]}, "properties": {"name": "原检索地点"}}]}
        store.upsert_layer(project_id, LayerRecord(layer_id="poi_search_results", name="旧检索", kind="vector", source="poi", geometry_type="Point", data=data))
        runtime.classroom.apply_lesson_scene(project_id, "lesson_builtin_population_shanghai_world", "china_explain")
        layer = next(item for item in store.get_project(project_id).layers if item.layer_id == "poi_search_results")
        self.assertFalse(layer.visible)
        self.assertEqual(layer.data, data)
        hu = next(item for item in store.get_project(project_id).layers if item.layer_id == "generated_hu_line")
        self.assertIn("黑河与腾冲", hu.metadata["reference_description"])
        self.assertIn("预设94%", hu.metadata["fitted_description"])
        runtime.classroom.lesson_service.apply_stage_scene_data(project_id, {"stage_id": "manual", "scene": {"layer_visibility": {"poi_search_results": True}}})
        self.assertTrue(layer.visible)

    def test_inquiry_regions_follow_the_current_geographical_scale(self):
        runtime, store, _ = self.build_runtime()
        lesson = store.get_lesson("lesson_builtin_population_shanghai_world")
        self.assertEqual(lesson.metadata["builtin_version"], "4")
        for stage_id in ("shanghai_inquiry", "shanghai_verify"):
            self.assertEqual(lesson.find_stage(stage_id)["brainstorm"]["regions"], ["黄浦区", "崇明区"])
        self.assertIn("塔里木盆地", lesson.find_stage("china_explain")["brainstorm"]["regions"])
        self.assertIn("欧洲", lesson.find_stage("world_inquiry")["brainstorm"]["regions"])
        # Do not interrupt the student-first line-drawing activity with AI answers.
        self.assertEqual(lesson.find_stage("china_inquiry")["brainstorm"], {})
        self.assertEqual(sum(len(stage["questions"]) for stage in lesson.stages), 11)

    def test_invalid_brainstorm_regions_do_not_become_characters_or_labels(self):
        from backend.app.services.lessons import normalize_brainstorm
        for regions in ("上海", None, 2, {"name": "上海"}, [None, 5, " "]):
            with self.subTest(regions=regions):
                self.assertEqual(normalize_brainstorm({"prompt": "比较", "regions": regions}), {})
        self.assertEqual(normalize_brainstorm({"prompt": "比较", "regions": [" 黄浦区 ", "黄浦区", "崇明区"]})["regions"], ["黄浦区", "崇明区"])

    def test_presentation_uses_snapshot_without_reentering_stage_or_changing_question(self):
        from copy import deepcopy
        runtime, store, project_id = self.build_runtime()
        response = runtime.classroom.create_class_session("lesson_builtin_population_shanghai_world", project_id)
        session_id = response["session"]["session_id"]
        runtime.classroom.enter_session_stage(session_id, "shanghai_intro")
        runtime.classroom.launch_session_question(session_id, stage_id="shanghai_intro", question_id="sh_intro_q")
        session = store.get_class_session(session_id)
        before = deepcopy(session.to_dict())
        # A later edit to the reusable lesson must not alter this classroom's map.
        store.get_lesson(session.lesson_id).find_stage("shanghai_intro")["scene"]["view"]["center"] = [0, 0]
        runtime.classroom.present_session_scene(session_id, "shanghai_intro")
        self.assertEqual(store.get_project(project_id).view["center"], [121.47, 31.23])
        runtime.classroom.present_session_scene(session_id, "shanghai_intro", "shanghai_age")
        age_layers = [layer for layer in store.get_project(project_id).layers if layer.visible and layer.source == "one_map_catalog"]
        self.assertEqual([layer.metadata["catalog_id"] for layer in age_layers], ["shanghai_age_60_plus_2020"])
        self.assertEqual(len(age_layers[0].data["features"]), 16)
        self.assertEqual(session.to_dict(), before)
        runtime.classroom.present_session_scene(session_id, "shanghai_intro", "shanghai_density")
        self.assertFalse(any(layer.visible and layer.metadata.get("catalog_id") == "shanghai_age_60_plus_2020" for layer in store.get_project(project_id).layers))
        runtime.classroom.present_session_scene(session_id, "shanghai_intro", "lujiazui")
        self.assertEqual(store.get_project(project_id).base_map["id"], "amap_imagery")
        self.assertEqual(store.get_project(project_id).view["center"], [121.505, 31.237])
        self.assertFalse(any(layer.visible and layer.source == "one_map_catalog" for layer in store.get_project(project_id).layers))
        runtime.classroom.present_session_scene(session_id, "shanghai_intro", "stage")
        self.assertEqual(session.to_dict(), before)
        with self.assertRaises(ValueError):
            runtime.classroom.present_session_scene(session_id, "china_inquiry", "stage")
        with self.assertRaises(ValueError):
            runtime.classroom.present_session_scene(session_id, "shanghai_intro", "unknown")
        runtime.classroom.enter_session_stage(session_id, "china_inquiry")
        with self.assertRaises(ValueError):
            runtime.classroom.present_session_scene(session_id, "china_inquiry", "lujiazui")
