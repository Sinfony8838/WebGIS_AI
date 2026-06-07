"""Tests for workflow validator and template expansion (no PyQGIS needed)."""
from __future__ import annotations

import unittest

from backend.app.services.workflow_validator import (
    ALLOWED_OPS,
    REQUIRED_PARAMS,
    WorkflowValidator,
    validate_workflow,
)
from backend.app.services.workflow_templates import (
    detect_template,
    expand_template,
    list_templates,
)


class WorkflowValidatorTests(unittest.TestCase):
    def test_top_level_must_be_object(self) -> None:
        result = validate_workflow([])
        self.assertFalse(result.valid)
        self.assertEqual(result.errors[0].code, "WORKFLOW_NOT_OBJECT")

    def test_steps_required(self) -> None:
        result = validate_workflow({"steps": []})
        self.assertFalse(result.valid)
        self.assertEqual(result.errors[0].code, "WORKFLOW_NO_STEPS")

    def test_op_whitelist(self) -> None:
        result = validate_workflow(
            {"steps": [{"id": "s1", "op": "delete_database", "params": {}}]}
        )
        self.assertFalse(result.valid)
        self.assertTrue(any(e.code == "STEP_OP_NOT_ALLOWED" for e in result.errors))

    def test_required_params_buffer(self) -> None:
        wf = {
            "steps": [
                {"id": "s1", "op": "load_layer", "params": {"source": "demo.geojson"}},
                {"id": "s2", "op": "buffer", "params": {"input": "${s1.layer}"}},
            ]
        }
        result = validate_workflow(wf)
        self.assertFalse(result.valid)
        self.assertTrue(any(e.code == "STEP_PARAM_MISSING" and e.field == "distance" for e in result.errors))

    def test_buffer_distance_must_be_positive(self) -> None:
        wf = {
            "steps": [
                {"id": "s1", "op": "load_layer", "params": {"source": "demo.geojson"}},
                {"id": "s2", "op": "buffer", "params": {"input": "${s1.layer}", "distance": -10}},
            ]
        }
        result = validate_workflow(wf)
        self.assertFalse(result.valid)
        self.assertTrue(any(e.code == "BUFFER_BAD_DISTANCE" for e in result.errors))

    def test_unknown_step_reference(self) -> None:
        wf = {
            "steps": [
                {"id": "s1", "op": "load_layer", "params": {"source": "demo.geojson"}},
                {"id": "s2", "op": "buffer", "params": {"input": "${s99.layer}", "distance": 100}},
            ]
        }
        result = validate_workflow(wf)
        self.assertFalse(result.valid)
        self.assertTrue(any(e.code == "REFERENCE_UNKNOWN_STEP" for e in result.errors))

    def test_self_reference_rejected(self) -> None:
        wf = {
            "steps": [
                {"id": "s1", "op": "buffer", "params": {"input": "${s1.layer}", "distance": 10}},
            ]
        }
        result = validate_workflow(wf)
        self.assertFalse(result.valid)
        self.assertTrue(any(e.code == "REFERENCE_SELF" for e in result.errors))

    def test_unsafe_source_rejected(self) -> None:
        wf = {
            "steps": [
                {"id": "s1", "op": "load_layer", "params": {"source": "/etc/passwd"}},
            ]
        }
        result = validate_workflow(wf)
        self.assertFalse(result.valid)
        self.assertTrue(any(e.code == "LOAD_LAYER_UNSAFE_SOURCE" for e in result.errors))

    def test_traversal_source_rejected(self) -> None:
        wf = {
            "steps": [
                {"id": "s1", "op": "load_layer", "params": {"source": "../../etc/passwd"}},
            ]
        }
        result = validate_workflow(wf)
        self.assertFalse(result.valid)
        self.assertTrue(any(e.code == "LOAD_LAYER_UNSAFE_SOURCE" for e in result.errors))

    def test_classes_range(self) -> None:
        wf = {
            "steps": [
                {"id": "s1", "op": "load_layer", "params": {"source": "demo.geojson"}},
                {
                    "id": "s2",
                    "op": "choropleth",
                    "params": {"input": "${s1.layer}", "field": "x", "classes": 99},
                },
            ]
        }
        result = validate_workflow(wf)
        self.assertFalse(result.valid)
        self.assertTrue(any(e.code == "CHOROPLETH_BAD_CLASSES" for e in result.errors))

    def test_minimal_valid_workflow(self) -> None:
        wf = {
            "version": "1.0",
            "intent": "demo",
            "steps": [
                {"id": "s1", "op": "load_layer", "params": {"source": "demo.geojson"}},
                {
                    "id": "s2",
                    "op": "export_geojson",
                    "params": {"input": "${s1.layer}"},
                    "depends_on": ["s1"],
                },
            ],
        }
        result = validate_workflow(wf)
        self.assertTrue(result.valid, msg=[e.to_dict() for e in result.errors])
        self.assertEqual(result.normalized["steps"][0]["op"], "load_layer")

    def test_required_params_registered_for_all_ops(self) -> None:
        for op in ALLOWED_OPS:
            self.assertIn(op, REQUIRED_PARAMS, f"missing required param entry for {op}")

    def test_clip_in_allowed_ops(self) -> None:
        # Phase 1.1: clip promoted from RESERVED to ALLOWED
        self.assertIn("clip", ALLOWED_OPS)

    def test_clip_requires_input_and_clip_layer(self) -> None:
        wf = {
            "steps": [
                {"id": "s1", "op": "load_layer", "params": {"source": "a.geojson"}},
                {
                    "id": "s2",
                    "op": "clip",
                    # missing clip_layer
                    "params": {"input": "${s1.layer}"},
                    "depends_on": ["s1"],
                },
            ]
        }
        result = validate_workflow(wf)
        self.assertFalse(result.valid)
        self.assertTrue(any(
            e.code == "STEP_PARAM_MISSING" and e.field == "clip_layer"
            for e in result.errors
        ))

    def test_clip_with_both_layers_valid(self) -> None:
        wf = {
            "version": "1.0",
            "intent": "clip demo",
            "steps": [
                {"id": "s1", "op": "load_layer", "params": {"source": "input.geojson"}},
                {"id": "s2", "op": "load_layer", "params": {"source": "region.geojson"}},
                {
                    "id": "s3",
                    "op": "clip",
                    "params": {"input": "${s1.layer}", "clip_layer": "${s2.layer}"},
                    "depends_on": ["s1", "s2"],
                },
            ],
        }
        result = validate_workflow(wf)
        self.assertTrue(result.valid, msg=[e.to_dict() for e in result.errors])

    def test_clip_step_output_keys_available_to_downstream(self) -> None:
        wf = {
            "version": "1.0",
            "intent": "clip then export",
            "steps": [
                {"id": "s1", "op": "load_layer", "params": {"source": "input.geojson"}},
                {"id": "s2", "op": "load_layer", "params": {"source": "region.geojson"}},
                {
                    "id": "s3",
                    "op": "clip",
                    "params": {"input": "${s1.layer}", "clip_layer": "${s2.layer}"},
                    "depends_on": ["s1", "s2"],
                },
                {
                    "id": "s4",
                    "op": "export_geojson",
                    "params": {"input": "${s3.layer}", "name": "clipped"},
                    "depends_on": ["s3"],
                },
            ],
        }
        result = validate_workflow(wf)
        self.assertTrue(result.valid, msg=[e.to_dict() for e in result.errors])

    def test_clip_no_longer_in_reserved_ops(self) -> None:
        from backend.app.services.workflow_validator import RESERVED_OPS
        self.assertNotIn("clip", RESERVED_OPS)

    def test_intersection_in_allowed_ops(self) -> None:
        self.assertIn("intersection", ALLOWED_OPS)

    def test_intersection_requires_input_and_overlay(self) -> None:
        wf = {
            "steps": [
                {"id": "s1", "op": "load_layer", "params": {"source": "a.geojson"}},
                {
                    "id": "s2",
                    "op": "intersection",
                    "params": {"input": "${s1.layer}"},  # missing overlay_layer
                    "depends_on": ["s1"],
                },
            ]
        }
        result = validate_workflow(wf)
        self.assertFalse(result.valid)
        self.assertTrue(any(
            e.code == "STEP_PARAM_MISSING" and e.field == "overlay_layer"
            for e in result.errors
        ))

    def test_intersection_with_both_layers_valid(self) -> None:
        wf = {
            "version": "1.0",
            "intent": "intersection demo",
            "steps": [
                {"id": "s1", "op": "load_layer", "params": {"source": "input.geojson"}},
                {"id": "s2", "op": "load_layer", "params": {"source": "overlay.geojson"}},
                {
                    "id": "s3",
                    "op": "intersection",
                    "params": {"input": "${s1.layer}", "overlay_layer": "${s2.layer}"},
                    "depends_on": ["s1", "s2"],
                },
                {
                    "id": "s4",
                    "op": "export_geojson",
                    "params": {"input": "${s3.layer}", "name": "isec"},
                    "depends_on": ["s3"],
                },
            ],
        }
        result = validate_workflow(wf)
        self.assertTrue(result.valid, msg=[e.to_dict() for e in result.errors])

    def test_intersection_no_longer_in_reserved_ops(self) -> None:
        from backend.app.services.workflow_validator import RESERVED_OPS
        self.assertNotIn("intersection", RESERVED_OPS)

    def test_spatial_join_in_allowed_ops(self) -> None:
        self.assertIn("spatial_join", ALLOWED_OPS)

    def test_spatial_join_requires_input_and_join_layer(self) -> None:
        wf = {
            "steps": [
                {"id": "s1", "op": "load_layer", "params": {"source": "a.geojson"}},
                {
                    "id": "s2",
                    "op": "spatial_join",
                    "params": {"input": "${s1.layer}"},  # missing join_layer
                    "depends_on": ["s1"],
                },
            ]
        }
        result = validate_workflow(wf)
        self.assertFalse(result.valid)
        self.assertTrue(any(
            e.code == "STEP_PARAM_MISSING" and e.field == "join_layer"
            for e in result.errors
        ))

    def test_spatial_join_rejects_unknown_predicate(self) -> None:
        wf = {
            "steps": [
                {"id": "s1", "op": "load_layer", "params": {"source": "a.geojson"}},
                {"id": "s2", "op": "load_layer", "params": {"source": "b.geojson"}},
                {
                    "id": "s3",
                    "op": "spatial_join",
                    "params": {
                        "input": "${s1.layer}",
                        "join_layer": "${s2.layer}",
                        "predicate": "near_enough",  # not allowed
                    },
                    "depends_on": ["s1", "s2"],
                },
            ]
        }
        result = validate_workflow(wf)
        self.assertFalse(result.valid)
        self.assertTrue(any(e.code == "SPATIAL_JOIN_BAD_PREDICATE" for e in result.errors))

    def test_spatial_join_rejects_unknown_method(self) -> None:
        wf = {
            "steps": [
                {"id": "s1", "op": "load_layer", "params": {"source": "a.geojson"}},
                {"id": "s2", "op": "load_layer", "params": {"source": "b.geojson"}},
                {
                    "id": "s3",
                    "op": "spatial_join",
                    "params": {
                        "input": "${s1.layer}",
                        "join_layer": "${s2.layer}",
                        "predicate": "within",
                        "method": "many_to_many",  # not allowed
                    },
                    "depends_on": ["s1", "s2"],
                },
            ]
        }
        result = validate_workflow(wf)
        self.assertFalse(result.valid)
        self.assertTrue(any(e.code == "SPATIAL_JOIN_BAD_METHOD" for e in result.errors))

    def test_spatial_join_accepts_all_predicates(self) -> None:
        # Each predicate should produce a valid workflow on its own.
        for pred in ("intersects", "contains", "within", "touches", "overlaps", "equals", "crosses"):
            wf = {
                "version": "1.0",
                "intent": f"spatial join {pred}",
                "steps": [
                    {"id": "s1", "op": "load_layer", "params": {"source": "a.geojson"}},
                    {"id": "s2", "op": "load_layer", "params": {"source": "b.geojson"}},
                    {
                        "id": "s3",
                        "op": "spatial_join",
                        "params": {
                            "input": "${s1.layer}",
                            "join_layer": "${s2.layer}",
                            "predicate": pred,
                        },
                        "depends_on": ["s1", "s2"],
                    },
                ],
            }
            result = validate_workflow(wf)
            self.assertTrue(result.valid, msg=f"predicate {pred}: {[e.to_dict() for e in result.errors]}")

    def test_spatial_join_no_longer_in_reserved_ops(self) -> None:
        from backend.app.services.workflow_validator import RESERVED_OPS
        self.assertNotIn("spatial_join", RESERVED_OPS)

    def test_classify_in_allowed_ops(self) -> None:
        self.assertIn("classify", ALLOWED_OPS)

    def test_classify_requires_input_and_field(self) -> None:
        wf = {
            "steps": [
                {"id": "s1", "op": "load_layer", "params": {"source": "a.geojson"}},
                {
                    "id": "s2",
                    "op": "classify",
                    "params": {"input": "${s1.layer}"},  # missing field
                    "depends_on": ["s1"],
                },
            ]
        }
        result = validate_workflow(wf)
        self.assertFalse(result.valid)
        self.assertTrue(any(
            e.code == "STEP_PARAM_MISSING" and e.field == "field"
            for e in result.errors
        ))

    def test_classify_bad_classes_count(self) -> None:
        wf = {
            "steps": [
                {"id": "s1", "op": "load_layer", "params": {"source": "a.geojson"}},
                {
                    "id": "s2",
                    "op": "classify",
                    "params": {"input": "${s1.layer}", "field": "pop", "classes": 99},
                    "depends_on": ["s1"],
                },
            ]
        }
        result = validate_workflow(wf)
        self.assertFalse(result.valid)
        self.assertTrue(any(e.code == "CLASSIFY_BAD_CLASSES" for e in result.errors))

    def test_classify_bad_method(self) -> None:
        wf = {
            "steps": [
                {"id": "s1", "op": "load_layer", "params": {"source": "a.geojson"}},
                {
                    "id": "s2",
                    "op": "classify",
                    "params": {
                        "input": "${s1.layer}",
                        "field": "pop",
                        "classes": 5,
                        "method": "magic_method",
                    },
                    "depends_on": ["s1"],
                },
            ]
        }
        result = validate_workflow(wf)
        self.assertFalse(result.valid)
        self.assertTrue(any(e.code == "CLASSIFY_BAD_METHOD" for e in result.errors))

    def test_classify_bad_output_field(self) -> None:
        wf = {
            "steps": [
                {"id": "s1", "op": "load_layer", "params": {"source": "a.geojson"}},
                {
                    "id": "s2",
                    "op": "classify",
                    "params": {
                        "input": "${s1.layer}",
                        "field": "pop",
                        "classes": 5,
                        "output_field": "1bad name",
                    },
                    "depends_on": ["s1"],
                },
            ]
        }
        result = validate_workflow(wf)
        self.assertFalse(result.valid)
        self.assertTrue(any(e.code == "CLASSIFY_BAD_OUTPUT_FIELD" for e in result.errors))

    def test_classify_valid(self) -> None:
        wf = {
            "version": "1.0",
            "intent": "classify demo",
            "steps": [
                {"id": "s1", "op": "load_layer", "params": {"source": "a.geojson"}},
                {
                    "id": "s2",
                    "op": "classify",
                    "params": {
                        "input": "${s1.layer}",
                        "field": "population",
                        "classes": 4,
                        "method": "quantile",
                        "output_field": "pop_bucket",
                    },
                    "depends_on": ["s1"],
                },
                {
                    "id": "s3",
                    "op": "export_geojson",
                    "params": {"input": "${s2.layer}", "name": "classified"},
                    "depends_on": ["s2"],
                },
            ],
        }
        result = validate_workflow(wf)
        self.assertTrue(result.valid, msg=[e.to_dict() for e in result.errors])

    def test_classify_no_longer_in_reserved_ops(self) -> None:
        from backend.app.services.workflow_validator import RESERVED_OPS
        self.assertNotIn("classify", RESERVED_OPS)


class WorkflowTemplateTests(unittest.TestCase):
    def test_detect_population(self) -> None:
        self.assertEqual(detect_template("帮我制作中国人口密度分级设色图"), "population_choropleth")

    def test_detect_buffer(self) -> None:
        self.assertEqual(detect_template("对学校做 1 公里缓冲区"), "facility_buffer")

    def test_detect_hu_line(self) -> None:
        self.assertEqual(detect_template("叠加胡焕庸线对比两侧人口"), "hu_line_compare")

    def test_detect_clip_to_region(self) -> None:
        self.assertEqual(detect_template("把人口图层裁剪到长三角范围"), "clip_to_region")
        self.assertEqual(detect_template("筛选黄河流域范围内的城市"), "clip_to_region")

    def test_population_template_validates(self) -> None:
        match = expand_template(
            "population_choropleth",
            "制作中国人口密度分级设色图",
            {"project_id": "p1"},
        )
        result = validate_workflow(match.workflow)
        self.assertTrue(result.valid, msg=[e.to_dict() for e in result.errors])

    def test_buffer_template_validates_distance_extracted(self) -> None:
        match = expand_template(
            "facility_buffer",
            "对学校做 3 公里缓冲区",
            {"project_id": "p1", "facility_dataset": "schools.geojson"},
        )
        result = validate_workflow(match.workflow)
        self.assertTrue(result.valid)
        # The buffer step must use a distance > 0
        buffer_step = next(s for s in match.workflow["steps"] if s["op"] == "buffer")
        self.assertGreater(buffer_step["params"]["distance"], 0)

    def test_clip_template_validates_end_to_end(self) -> None:
        match = expand_template(
            "clip_to_region",
            "把全国POI裁剪到长三角范围",
            {"project_id": "p1", "input_dataset": "poi.geojson", "region_dataset": "yrd.geojson"},
        )
        result = validate_workflow(match.workflow)
        self.assertTrue(result.valid, msg=[e.to_dict() for e in result.errors])
        # Verify the clip step is present and wired
        clip_step = next(s for s in match.workflow["steps"] if s["op"] == "clip")
        self.assertEqual(clip_step["params"]["input"], "${s2.layer}")
        self.assertEqual(clip_step["params"]["clip_layer"], "${s4.layer}")

    def test_detect_overlay_intersection(self) -> None:
        self.assertEqual(detect_template("把人口和气候带求交集"), "overlay_intersection")
        self.assertEqual(detect_template("两个图层的相交部分"), "overlay_intersection")

    def test_intersection_template_validates_end_to_end(self) -> None:
        match = expand_template(
            "overlay_intersection",
            "把人口图层和气候带求交集",
            {"project_id": "p1", "input_dataset": "pop.geojson", "overlay_dataset": "climate.geojson"},
        )
        result = validate_workflow(match.workflow)
        self.assertTrue(result.valid, msg=[e.to_dict() for e in result.errors])
        isec = next(s for s in match.workflow["steps"] if s["op"] == "intersection")
        self.assertEqual(isec["params"]["input"], "${s2.layer}")
        self.assertEqual(isec["params"]["overlay_layer"], "${s4.layer}")

    def test_detect_spatial_join(self) -> None:
        self.assertEqual(detect_template("把学校和行政区做空间连接"), "spatial_join_attributes")
        self.assertEqual(detect_template("看每个学校落在哪个区"), "spatial_join_attributes")

    def test_spatial_join_template_validates_end_to_end(self) -> None:
        match = expand_template(
            "spatial_join_attributes",
            "把学校和行政区做空间连接",
            {"project_id": "p1", "input_dataset": "schools.geojson", "join_dataset": "districts.geojson"},
        )
        result = validate_workflow(match.workflow)
        self.assertTrue(result.valid, msg=[e.to_dict() for e in result.errors])
        step = next(s for s in match.workflow["steps"] if s["op"] == "spatial_join")
        self.assertEqual(step["params"]["input"], "${s2.layer}")
        self.assertEqual(step["params"]["join_layer"], "${s4.layer}")
        self.assertEqual(step["params"]["predicate"], "intersects")

    def test_detect_classify(self) -> None:
        self.assertEqual(detect_template("把人口字段按 quantile 分级"), "classify_field")
        self.assertEqual(detect_template("用 jenks 方法对数据分类"), "classify_field")

    def test_classify_template_validates_end_to_end(self) -> None:
        match = expand_template(
            "classify_field",
            "对人口字段分 5 级",
            {"project_id": "p1", "dataset": "provinces.geojson", "field": "population", "classes": 5},
        )
        result = validate_workflow(match.workflow)
        self.assertTrue(result.valid, msg=[e.to_dict() for e in result.errors])
        step = next(s for s in match.workflow["steps"] if s["op"] == "classify")
        self.assertEqual(step["params"]["field"], "population")
        self.assertEqual(step["params"]["classes"], 5)
        self.assertEqual(step["params"]["output_field"], "population_class")

    def test_population_choropleth_priority_over_classify(self) -> None:
        # Ensure the more specific choropleth keyword still wins.
        self.assertEqual(detect_template("制作中国人口密度分级设色图"), "population_choropleth")

    def test_template_listing(self) -> None:
        items = list_templates()
        self.assertEqual(len(items), 7)
        ids = {item["id"] for item in items}
        self.assertEqual(
            ids,
            {
                "population_choropleth",
                "facility_buffer",
                "hu_line_compare",
                "clip_to_region",
                "overlay_intersection",
                "spatial_join_attributes",
                "classify_field",
            },
        )


if __name__ == "__main__":
    unittest.main()
