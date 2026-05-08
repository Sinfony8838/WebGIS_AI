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


class WorkflowTemplateTests(unittest.TestCase):
    def test_detect_population(self) -> None:
        self.assertEqual(detect_template("帮我制作中国人口密度分级设色图"), "population_choropleth")

    def test_detect_buffer(self) -> None:
        self.assertEqual(detect_template("对学校做 1 公里缓冲区"), "facility_buffer")

    def test_detect_hu_line(self) -> None:
        self.assertEqual(detect_template("叠加胡焕庸线对比两侧人口"), "hu_line_compare")

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

    def test_template_listing(self) -> None:
        items = list_templates()
        self.assertEqual(len(items), 3)
        ids = {item["id"] for item in items}
        self.assertEqual(ids, {"population_choropleth", "facility_buffer", "hu_line_compare"})


if __name__ == "__main__":
    unittest.main()
