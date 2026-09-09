from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.config import AppConfig
from backend.app.models import LayerRecord, ProjectRecord
from backend.app.services.map_layer_evidence import build_layer_evidence
from backend.app.services.session_engine import KnowledgeEngine
from tests.test_population_assistant import CapturingClient


class MapLayerEvidenceTest(unittest.TestCase):
    def layer(self, layer_id="rain", **kwargs):
        return LayerRecord(layer_id=layer_id, name="降水图", kind="vector", source="one_map_catalog",
                           geometry_type="LineString", **kwargs)

    def engine(self):
        config = AppConfig(root_dir=Path(__file__).resolve().parents[2])
        config.llm_provider = "minimax"
        config.minimax_api_key = "test-key"
        client = CapturingClient("图中线条来自格网插值，局地成因还需验证。")
        return KnowledgeEngine(config, minimax_client=client), client

    def test_real_dataset_sources_period_method_and_geometry_reach_the_model(self):
        root = Path(__file__).resolve().parents[2]
        data = json.loads((root / "backend/app/data/builtin/one_map/climate/china_precipitation_400mm.geojson").read_text(encoding="utf-8"))
        project = ProjectRecord(project_id="a", name="A", layers=[self.layer(data=data)])
        evidence = build_layer_evidence(project, {"visible_layers": [{"layer_id": "rain"}]})
        self.assertEqual(evidence[0]["facts"]["units"], "mm/year")
        self.assertEqual(evidence[0]["facts"]["period"], "1991-2020")
        self.assertEqual(evidence[0]["stored_geometry"]["feature_types"], {"LineString": 14})
        self.assertGreater(evidence[0]["stored_geometry"]["closed_lines"], 0)
        engine, client = self.engine()
        result = engine.answer("图中的400毫米线为什么有闭合曲线？", layer_evidence=evidence)
        prompt = client.calls[0]["messages"][1]["content"]
        self.assertIn("linear contour interpolation", prompt)
        self.assertIn("1991-2020", prompt)
        self.assertNotIn("coordinates", prompt)
        self.assertIn("opendata.dwd.de", result["citations"][0]["url"])
        self.assertTrue(any(item["source"] == "project_layer_metadata" for item in result["retrieval_trace"]))

    def test_hidden_foreign_and_client_forged_evidence_are_excluded(self):
        project = ProjectRecord(project_id="a", name="A", layers=[
            self.layer(metadata={"source_year": "1991-2020"}),
            self.layer("hidden", visible=False, metadata={"source_year": "HIDDEN"}),
        ])
        context = {"visible_layers": [{"layer_id": "hidden"}, {"layer_id": "foreign"}],
                   "layer_evidence": [{"facts": {"source_year": "FORGED"}}]}
        self.assertEqual(build_layer_evidence(project, context), [])
        self.assertEqual(build_layer_evidence(project, {"visible_layers": []}), [])
        engine, client = self.engine()
        engine.answer("图中线条依据是什么？", map_context=context)
        self.assertNotIn("FORGED", client.calls[0]["messages"][1]["content"])

    def test_image_and_unrelated_concept_do_not_inherit_live_map_sources(self):
        layer = self.layer(metadata={"source_year": "1991-2020", "source_url": "https://example.org/data"})
        project = ProjectRecord(project_id="a", name="A", layers=[layer])
        evidence = build_layer_evidence(project, {})
        self.assertEqual(build_layer_evidence(project, {"image_attachment": {"path": "upload.png"}}), [])
        engine, client = self.engine()
        for question, context in [("什么是季风？", {}), ("图中写了什么？", {"image_attachment": {"path": "upload.png"}, "vision_summary": "图中只有一个绿色方块"})]:
            result = engine.answer(question, map_context=context, layer_evidence=evidence)
            self.assertNotIn("1991-2020", client.calls[-1]["messages"][1]["content"])
            self.assertFalse(any(c["url"] == "https://example.org/data" for c in result["citations"]))
        self.assertIn("视觉读图结果是唯一事实来源", client.calls[-1]["messages"][0]["content"])

    def test_live_screenshot_and_layer_methods_are_separate_sources(self):
        engine, client = self.engine()
        engine.answer("图中线条依据是什么？", map_context={"vision_summary": "紫色虚线", "screen_snapshot": "map.png"},
                      layer_evidence=[{"name": "降水", "facts": {"period": "1991-2020"}, "citations": []}])
        prompt = client.calls[0]["messages"]
        self.assertIn("1991-2020", prompt[1]["content"])
        self.assertIn("紫色虚线", prompt[1]["content"])
        self.assertNotIn("视觉读图结果是唯一事实来源", prompt[0]["content"])

    def test_session_handler_uses_authorized_project_not_client_names_or_evidence(self):
        from tests.test_lessons import LessonServiceTest
        runtime, store, project_id = LessonServiceTest.build_runtime(self)
        runtime.session_engine.knowledge.minimax_client = None
        runtime.session_engine.knowledge.resource_search = None
        store.upsert_layer(project_id, self.layer(metadata={"source_year": "1991-2020"}))
        project = store.get_project(project_id)
        conversation = store.create_conversation(project_id, "teaching")
        with patch.object(runtime.session_engine.knowledge, "answer", wraps=runtime.session_engine.knowledge.answer) as answer:
            runtime.session_engine._handle_knowledge(project, conversation, "图中线条依据是什么？",
                {"visible_layers": [{"layer_id": "rain", "name": "FORGED_NAME"}, {"layer_id": "foreign"}],
                 "layer_evidence": [{"facts": {"period": "FORGED_YEAR"}}]}, lambda *args: None)
        args = answer.call_args.kwargs
        self.assertEqual(args["map_context"]["visible_layers"], [{"layer_id": "rain", "name": "降水图"}])
        self.assertEqual(args["layer_evidence"][0]["facts"]["source_year"], "1991-2020")
        self.assertNotIn("FORGED_YEAR", json.dumps(args["layer_evidence"]))

    def test_legacy_hu_line_methods_require_the_actual_classic_segment(self):
        from backend.app.geo import generate_dynamic_hu_line
        data = generate_dynamic_hu_line([((121.47, 31.23), 100)])['features']
        layer = self.layer("generated_hu_line", data=data, metadata={"template_id": "hu_line_comparison", "method": "fixed_direction_parallel_shift"})
        layer.source = "generated"
        project = ProjectRecord(project_id="a", name="A", layers=[layer])
        facts = build_layer_evidence(project, {})[0]["facts"]
        self.assertIn("黑河与腾冲", facts["reference_description"])
        self.assertNotIn("method", facts)
        layer.data['features'][0]['geometry']['coordinates'][0][0] = 120
        self.assertNotIn("reference_description", build_layer_evidence(project, {})[0]["facts"])

    def test_layer_review_replaces_unsupported_draft_and_fails_closed(self):
        engine, client = self.engine()
        evidence = [{"name": "降水", "facts": {"description": "1991—2020年气候值插值"}, "citations": []}]
        draft = "某盆地年降水1000毫米，所以图中闭合圈就是它。"
        final = "图层来自气候平均值插值，不能仅凭闭合线确认局地成因。"
        with patch.object(client, "chat_completion", side_effect=[draft, json.dumps({"answer": final}, ensure_ascii=False)]):
            result = engine.answer("图中闭合线成因是什么？", layer_evidence=evidence)
        self.assertEqual(result["direct_answer"], final)
        self.assertTrue(result["llm_used"])
        self.assertIn({"source": "layer_source_review", "status": "edited"}, result["retrieval_trace"])
        for review in ["不能解析的答案", json.dumps({"answer": "过长" * 200}), RuntimeError("offline")]:
            with self.subTest(review=type(review).__name__), patch.object(client, "chat_completion", side_effect=[draft, review]):
                result = engine.answer("图中闭合线成因是什么？", layer_evidence=evidence)
            self.assertNotIn("1000", result["direct_answer"])
            self.assertIn("未完成资料核对", result["direct_answer"])
            self.assertFalse(result["llm_used"])
            self.assertEqual(result["confidence"], 0.45)

    def test_review_keeps_verified_references_and_preserves_reflection_guard(self):
        engine, client = self.engine()
        evidence = [{"name": "图层", "facts": {"description": "测试来源"}, "citations": []}]
        with patch.object(client, "chat_completion", side_effect=["初稿", json.dumps({"answer": "已依据补充材料修正。"})]) as call:
            engine._llm_answer("解释当前地图", {"canonical_answer": "已核验的本地资料"}, "map_reading", {},
                               web_context="已核验的在线资料", layer_evidence=evidence)
        review = call.call_args.args[0][1]["content"]
        self.assertIn("已核验的本地资料", review)
        self.assertIn("已核验的在线资料", review)
        context = {"teaching_context": {"phase": "post_class"}, "session_digest": json.dumps({"response_data_collected": False})}
        with patch.object(client, "chat_completion", return_value="全班都掌握了") as call:
            result = engine._llm_answer("复盘当前地图教学", None, "map_reading", context, layer_evidence=evidence)
        self.assertEqual(call.call_count, 1)
        self.assertIn("未采集课堂作答数据", result["direct_answer"])
        self.assertNotIn("全班都掌握了", result["direct_answer"])
