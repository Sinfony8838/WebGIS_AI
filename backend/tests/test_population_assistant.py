from __future__ import annotations

import unittest
from unittest.mock import patch
from pathlib import Path

from backend.app.config import AppConfig
from backend.app.services.knowledge_base import KnowledgeBaseService
from backend.app.services.resource_search import ResourceSearchService
from backend.app.services.session_engine import KnowledgeEngine


class CapturingClient:
    def __init__(self, response: str = "回答") -> None:
        self.response = response
        self.calls: list[dict] = []

    def chat_completion(self, messages, temperature=0.3, **kwargs):
        self.calls.append({"messages": messages, "temperature": temperature})
        return self.response


class PopulationAssistantTest(unittest.TestCase):
    def build_config(self, *, with_llm: bool = False) -> AppConfig:
        config = AppConfig(root_dir=Path(__file__).resolve().parents[2])
        config.llm_provider = "minimax"
        config.minimax_api_key = "test-key" if with_llm else ""
        return config

    def test_structured_brainstorm_uses_selected_region_not_reference_freshness(self):
        from unittest.mock import Mock
        client = CapturingClient("头脑风暴问题：青藏高原河谷为什么可能出现局部人口集聚？\n回答：需比较水源、地形条件并用地图验证。\n回答总结：总体稀疏不排除局部集聚。")
        search = Mock()
        engine = KnowledgeEngine(self.build_config(with_llm=True), minimax_client=client, resource_search=search)
        prompt = ("GeoBot 头脑风暴：围绕胡焕庸线解释例外。\n随机抽中的地区是：青藏高原河谷。\n"
                  "【本次探究任务】\n从所抽地区的水源、地形解释局部人口集聚。\n"
                  "【课堂参考材料】\n1935年的历史人口比例不能冒用为今天的统计结论。教材来源请核实。\n"
                  "【回答格式】不要输出地图中心坐标。")
        region_entry = {"title":"青藏高原河谷", "canonical_answer":"河谷条件参考", "citations":[], "teaching_points":[]}
        original_match = engine._match_entry
        with patch.object(engine, "_match_entry", side_effect=lambda q: region_entry if q == "青藏高原河谷" else original_match(q)):
            result = engine.answer(prompt, map_context={"teaching_context":{"phase":"in_class"}})
        search.search.assert_not_called()
        self.assertTrue(result["llm_used"])
        self.assertIn("青藏高原河谷", result["direct_answer"])
        self.assertNotIn("timely_verification_guardrail", str(result["retrieval_trace"]))
        self.assertIn("河谷条件参考", str(client.calls[0]["messages"]))
        self.assertIn("不能冒用为今天", str(client.calls[0]["messages"]))

    def test_builtin_china_brainstorm_keeps_material_without_false_latest_guard(self):
        import json
        from unittest.mock import Mock
        lesson = json.loads((Path(__file__).resolve().parents[1] / "app/data/builtin/lessons/population_shanghai_world_lesson.json").read_text(encoding="utf-8"))
        stage = next(stage for stage in lesson["stages"] if "比较胡焕庸线" in stage["title"])
        for region in stage["brainstorm"]["regions"]:
            with self.subTest(region=region):
                client = CapturingClient(f"头脑风暴问题：{region}的局部条件如何影响人口分布？\n回答：比较水源与地形，结论需地图验证。\n回答总结：总体与局部需分开比较。")
                search = Mock()
                engine = KnowledgeEngine(self.build_config(with_llm=True), minimax_client=client, resource_search=search)
                prompt = "\n".join([
                    f"GeoBot 头脑风暴：围绕“{stage['title']}”开展随机地区探究。",
                    f"随机抽中的地区是：{region}。", "【本次探究任务】", stage["brainstorm"]["prompt"],
                    "请生成一个与当前问题链衔接的追问，并提供教师参考回答；不替学生作答，不推断学生掌握情况。",
                    "【课堂参考材料】", "；".join(stage["script"]),
                    *["\n".join(str(question.get(key) or "") for key in ("text", "material", "answer", "explanation")) for question in stage["questions"]],
                    "【回答格式】只输出头脑风暴问题、回答、回答总结。不要输出地图中心坐标。",
                ])
                result = engine.answer(prompt, map_context={"teaching_context": {"phase": "in_class"}})
                search.search.assert_not_called()
                self.assertTrue(result["llm_used"])
                self.assertIn(region, result["direct_answer"])
                self.assertNotIn("timely_verification_guardrail", str(result["retrieval_trace"]))
                self.assertIn("不能冒用为今天", str(client.calls[0]["messages"]))
                self.assertIn(stage["brainstorm"]["prompt"], str(client.calls[0]["messages"]))

    def test_structured_brainstorm_explicit_latest_request_still_requires_evidence(self):
        from unittest.mock import Mock
        client = CapturingClient()
        search = Mock()
        search.search.return_value = {"items":[]}
        engine = KnowledgeEngine(self.build_config(with_llm=True), minimax_client=client, resource_search=search)
        prompt = ("GeoBot 头脑风暴：地区人口。\n随机抽中的地区是：上海。\n"
                  "【本次探究任务】请联网查询今年最新上海人口数据。\n"
                  "【课堂参考材料】不要求学生背诵数字。")
        result = engine.answer(prompt, map_context={"teaching_context":{"phase":"in_class"}})
        self.assertIn("没有取得", result["direct_answer"])
        self.assertFalse(client.calls)
        self.assertIn("今年最新", search.search.call_args.kwargs["query"])
        self.assertNotIn("不要求学生", search.search.call_args.kwargs["query"])

    def test_brainstorm_source_notes_do_not_block_generation_but_latest_facts_do(self) -> None:
        client = CapturingClient("头脑风暴问题：区级平均值能代表各街镇吗？\n回答：不能。\n回答总结：比较须注意尺度。")
        engine = KnowledgeEngine(self.build_config(with_llm=True), minimax_client=client)
        context = {"teaching_context": {"phase": "in_class"}}
        result = engine.answer("GeoBot 头脑风暴：上海人口密度比较。参考材料来源：2020年普查；请核实统计口径。生成一个尺度转换追问。", map_context=context)
        self.assertIn("区级平均值", result["direct_answer"])
        self.assertEqual(len(client.calls), 1)
        latest = engine.answer("GeoBot 头脑风暴：请使用今年最新上海常住人口数据生成追问。", map_context=context)
        self.assertIn("没有取得", latest["direct_answer"])
        self.assertEqual(len(client.calls), 1)

    def test_shanghai_extension_retrieves_commuting_evidence_not_incidental_density(self) -> None:
        client = CapturingClient("头脑风暴问题：只建住宅能形成年轻环吗？\n回答：不一定，还需观察实际入住与通勤。\n回答总结：居住与就业应分开检验。")
        engine = KnowledgeEngine(self.build_config(with_llm=True), minimax_client=client)
        result = engine.answer("GeoBot 头脑风暴：上海年轻环的条件变化追问。\n请围绕下面2025河南卷题组，沿用限定问题给出教师参考回答。\n材料：人口密度、人口总量、2020普查，地图不能推断年龄比例。", map_context={"teaching_context": {"phase": "in_class"}}, teaching_task="teaching_question")
        self.assertTrue(result["llm_used"])
        self.assertEqual([c["url"] for c in result["citations"]], ["https://www.geog.com.cn/CN/abstract/article/0375-5444/48138"])
        reference = client.calls[0]["messages"][1]["content"]
        self.assertIn("2017年9月", reference)
        self.assertIn("跨区就业", reference)
        self.assertIn("并非2025年高考试题官方解析", reference)
        self.assertIn("没有取得", engine.answer("GeoBot 头脑风暴：今年上海年轻环最新年龄比例是什么？", map_context={"teaching_context": {"phase": "in_class"}})["direct_answer"])
        self.assertEqual(len(client.calls), 1)

    def test_long_or_absolute_classroom_draft_is_reviewed_before_display(self) -> None:
        client = CapturingClient()
        engine = KnowledgeEngine(self.build_config(with_llm=True), minimax_client=client)
        final = "问题：只建住宅能保证年轻环形成吗？\n回答：不能保证；若通勤便利，年轻人也可能在郊区居住、跨区就业，应核对实际入住年龄与通勤资料。\n回答总结：不能只凭住宅供应判断。"
        with patch.object(client, "chat_completion", side_effect=["职住平衡是年轻环形成的必要条件，缺一不可。", final]) as call:
            result = engine.answer("GeoBot 头脑风暴：上海年轻环的条件变化追问。", teaching_task="teaching_question")
        self.assertEqual(call.call_count, 2)
        self.assertEqual(result["direct_answer"], final)
        self.assertNotIn("缺一不可", result["direct_answer"])
        with patch.object(client, "chat_completion", return_value="未经压缩的很长回答。" * 50) as call:
            failed = engine.answer("GeoBot 头脑风暴：上海年轻环的条件变化追问。", teaching_task="teaching_question")
        self.assertEqual(call.call_count, 2)
        self.assertFalse(failed["llm_used"])
        self.assertIn("未能生成可用回答", failed["direct_answer"])
        with patch.object(client, "chat_completion", side_effect=["关于气候的冗长初稿。" * 50, "问题：降水如何影响分布？回答：需结合水资源及其他条件。总结：比较条件组合。"] ) as call:
            engine.answer("GeoBot 头脑风暴：气候与人口分布的条件变化追问。")
        self.assertNotIn("跨区通勤", call.call_args.args[0][0]["content"])

    def test_fixed_shanghai_followup_rejects_known_false_necessity_claims(self) -> None:
        question = "GeoBot 头脑风暴：上海年轻环的条件变化追问。\n限定任务：如果郊区仅增加住宅但缺少就业岗位，年轻环一定会形成吗？"
        for draft in (
            "职住平衡是年轻环形成的必要条件，缺一不可。",
            "年轻环的形成需要职住空间分离。",
            "缺少本地就业就不会形成年轻环。",
        ):
            with self.subTest(draft=draft):
                client = CapturingClient(draft)
                engine = KnowledgeEngine(self.build_config(with_llm=True), minimax_client=client)
                result = engine.answer(question, teaching_task="teaching_question")
                self.assertFalse(result["llm_used"])
                self.assertIn("AI 回答未通过条件检查", result["direct_answer"])
                self.assertIn("跨区就业", result["direct_answer"])
                self.assertIn({"source": "reviewed_teacher_reference", "status": "fallback"}, result["retrieval_trace"])
        client = CapturingClient("不一定。本地岗位少不等于就业不可达，通勤便利时仍可能吸引年轻人居住，需检验实际年龄结构。")
        result = KnowledgeEngine(self.build_config(with_llm=True), minimax_client=client).answer(question)
        self.assertTrue(result["llm_used"])
        self.assertNotIn("未通过", result["direct_answer"])

    def test_density_and_total_are_not_swapped_for_shanghai_and_tibet(self) -> None:
        engine = KnowledgeEngine(self.build_config())

        result = engine.answer("人口密度高是否等于人口总量大？以上海和西藏为例。")

        answer = result["direct_answer"]
        self.assertIn("人口总量回答", answer)
        self.assertIn("上海的人口总量和人口密度都高于西藏", answer)
        self.assertIn("不能用来证明", answer)
        self.assertNotIn("上海的人口总量反而远低于西藏", answer)
        self.assertEqual(result["retrieval_mode"], "local")

    def test_migration_flow_does_not_imply_net_migration(self) -> None:
        engine = KnowledgeEngine(self.build_config())

        result = engine.answer("人口迁移流线越粗是不是表示迁入人口越多？能否据此判断净迁入？")

        answer = result["direct_answer"]
        self.assertIn("必须先看图例", answer)
        self.assertIn("所有迁入量减去所有迁出量", answer)
        self.assertIn("不能判断净迁入", answer)
        self.assertNotIn("沿海地区一定是净迁入", answer)

    def test_population_change_and_comparability_concepts_stay_source_free(self) -> None:
        engine = KnowledgeEngine(self.build_config())
        cases = [
            (
                "人口自然增长率下降，为什么人口总量还可能继续增加？",
                ("不等于增长率已经为零", "净迁移"),
            ),
            (
                "自然增长为负是否等于人口一定减少？还要看什么？",
                ("自然增长和净迁移共同决定", "统计时期"),
            ),
            (
                "比较两个城市人口规模时，常住人口和户籍人口能混用吗？",
                ("不能直接混用", "统一年份、行政范围和人口口径"),
            ),
            (
                "人口净迁入为正，为什么常住人口总量仍可能下降？",
                ("自然增长加净迁移", "自然减少的规模大于净迁入"),
            ),
            (
                "做城市人口Top20时，怎样保证年份、行政范围和统计口径可比？",
                ("同一统计年份", "同一行政范围"),
            ),
        ]

        for question, expected in cases:
            with self.subTest(question=question):
                result = engine.answer(question)
                answer = result["direct_answer"]
                for phrase in expected:
                    self.assertIn(phrase, answer)
                self.assertFalse(result["llm_used"])
                self.assertNotIn("知识库", answer)
                self.assertNotRegex(answer, r"\d+\s*(?:万|亿|%)")

    def test_census_data_is_labeled_as_2020_not_current(self) -> None:
        engine = KnowledgeEngine(self.build_config())

        result = engine.answer("课堂上如何使用2020年七普数据，同时避免把历史数据说成当前数据？")

        answer = result["direct_answer"]
        self.assertIn("2020年第七次全国人口普查数据", answer)
        self.assertIn("不要简称为“当前人口数据”", answer)
        self.assertIn("没有完成最新核验时，不补写现时人口数", answer)

    def test_authority_homepage_suggestions_are_not_verified_evidence(self) -> None:
        config = self.build_config(with_llm=True)
        knowledge_base = KnowledgeBaseService(config)
        resource_search = ResourceSearchService(config, knowledge_base)
        client = CapturingClient("胡焕庸线不是行政边界；当前比例尚未取得可核验的在线结果。")
        engine = KnowledgeEngine(config, minimax_client=client, resource_search=resource_search)

        result = engine.answer("胡焕庸线是行政边界吗？今天还有效吗？")

        self.assertEqual(result["retrieval_mode"], "local_web")
        self.assertFalse(result["web_verified"])
        self.assertNotIn("World Bank Data", {item["title"] for item in result["citations"]})
        self.assertEqual(client.calls, [])
        self.assertIn("不能据此断言现状仍然相同", result["direct_answer"])
        self.assertIn("不提供未经核实的现时比例", result["direct_answer"])

    def test_subdistrict_materials_require_the_relevant_region(self) -> None:
        engine = KnowledgeEngine(self.build_config(with_llm=False))
        self.assertEqual(engine._match_entry("青浦街镇人口如何变化？")["id"], "shanghai_qingpu_population_statistics")
        self.assertEqual(engine._match_entry("杨浦常住人口资料")["id"], "shanghai_yangpu_population_statistics")
        self.assertIsNone(engine._match_entry("请核实今年最新人口总量和来源"))

    def test_unverified_latest_population_without_local_entry_is_explicitly_deferred(self) -> None:
        config = self.build_config(with_llm=True)

        class EmptySearch:
            def search(self, query: str, scope: str, limit: int):
                return {"items": []}

        client = CapturingClient("中国当前人口为一个未经验证的数值。")
        engine = KnowledgeEngine(config, minimax_client=client, resource_search=EmptySearch())

        result = engine.answer("请核实今年最新人口总量和来源")

        self.assertFalse(result["web_verified"])
        self.assertEqual(client.calls, [])
        self.assertIn("暂时不能给出当前数值", result["direct_answer"])
        self.assertIn("机构主页", result["direct_answer"])

    def test_verified_web_result_enters_answer_context_and_citations(self) -> None:
        config = self.build_config(with_llm=True)

        class VerifiedSearch:
            def search(self, query: str, scope: str, limit: int):
                return {
                    "items": [
                        {
                            "title": "国家统计局核验页",
                            "url": "https://www.stats.gov.cn/example",
                            "summary": "已核验的官方统计摘要。",
                            "confidence": 0.95,
                            "evidence_verified": True,
                        }
                    ]
                }

        client = CapturingClient("已根据官方统计摘要回答。")
        engine = KnowledgeEngine(config, minimax_client=client, resource_search=VerifiedSearch())

        result = engine.answer("请核实今年最新人口数据及来源")

        self.assertTrue(result["web_verified"])
        self.assertIn("国家统计局核验页", {item["title"] for item in result["citations"]})
        user_prompt = client.calls[0]["messages"][1]["content"]
        self.assertIn("已核验的官方统计摘要", user_prompt)

    def test_population_image_negated_current_data_does_not_trigger_web_search(self) -> None:
        config = self.build_config(with_llm=True)

        class FailingSearch:
            def search(self, query: str, scope: str, limit: int):
                raise AssertionError("pure image reading must not search the web")

        client = CapturingClient("图中显示人口密度总体东南高、西北低。")
        engine = KnowledgeEngine(config, minimax_client=client, resource_search=FailingSearch())

        result = engine.answer(
            "请描述图中的人口密度分布，不要把图中比例说成当前数据。",
            {
                "image_attachment": {"artifact_id": "population-map"},
                "vision_summary": "The legend is population density. The printed data year is 2014.",
            },
        )

        self.assertEqual(result["retrieval_mode"], "none")
        self.assertTrue(result["llm_used"])
        self.assertEqual(result["citations"], [])
        system_prompt = client.calls[0]["messages"][0]["content"]
        self.assertIn("全文通常不超过 260 个汉字", system_prompt)
        self.assertIn("只有视觉结果明确给出区间时", system_prompt)
        self.assertIn("用户没有询问原因或影响因素时", system_prompt)
        self.assertIn("不得称为行政边界", system_prompt)

    def test_population_image_can_explicitly_request_latest_web_material(self) -> None:
        config = self.build_config(with_llm=True)

        class VerifiedSearch:
            def search(self, query: str, scope: str, limit: int):
                return {
                    "items": [
                        {
                            "title": "官方最新人口资料",
                            "url": "https://www.stats.gov.cn/example",
                            "summary": "带统计日期和口径的核验摘要。",
                            "confidence": 0.95,
                            "evidence_verified": True,
                        }
                    ]
                }

        client = CapturingClient("图中年份与最新资料需要分开说明。")
        engine = KnowledgeEngine(config, minimax_client=client, resource_search=VerifiedSearch())

        result = engine.answer(
            "请分析这张人口图，并联网核实最新资料。",
            {
                "image_attachment": {"artifact_id": "population-map"},
                "vision_summary": "The map title says population density in 2014.",
            },
        )

        self.assertEqual(result["retrieval_mode"], "web")
        self.assertTrue(result["web_verified"])
        self.assertIn("官方最新人口资料", {item["title"] for item in result["citations"]})

    def test_image_answer_removes_unsolicited_coordinate_sentence(self) -> None:
        answer = "芬兰人口密度总体南高北低。主要密集带位于北纬60°至64°。南部颜色更深。"

        cleaned = KnowledgeEngine._sanitize_image_answer_coordinates(answer, "请分析芬兰人口密度的南北差异。")
        preserved = KnowledgeEngine._sanitize_image_answer_coordinates(answer, "请说明人口密集带的纬度范围。")

        self.assertIn("南高北低", cleaned)
        self.assertNotIn("北纬60°", cleaned)
        self.assertIn("南部颜色更深", cleaned)
        self.assertIn("北纬60°", preserved)

    def test_population_legend_statement_uses_every_printed_tick(self) -> None:
        summary = """Mapped variable: Population Density, persons/km².
**Legend — Class Boundaries as Printed**
The legend shows these exact values:
- 200 (darkest)
- 100
- 50
- 10
- 1
- 0 (lightest)

**Color Scheme**
- Sequential warm ramp.
"""
        answer = "高值区集中在东亚和南亚。图例共设五个等级，为0、1、50、100、200人/km²。"

        cleaned = KnowledgeEngine._ensure_population_legend_statement(
            answer,
            "请根据图例分析世界人口密度分布。",
            summary,
        )

        self.assertIn("图例标注了0、1、10、50、100、200", cleaned)
        self.assertNotIn("五个等级", cleaned)

    def test_population_legend_values_support_color_first_format(self) -> None:
        summary = """### Legend (Population Density)
- **Dark brown**: 200
- **Orange**: 100
- **Yellow**: 50
- **Pale yellow**: 10
- **Cream**: 1
- **White**: 0

### Spatial Pattern
"""

        self.assertEqual(
            KnowledgeEngine._population_legend_values(summary),
            ["0", "1", "10", "50", "100", "200"],
        )

    def test_migration_flow_legend_is_not_rewritten_as_population_density_colors(self) -> None:
        summary = """### Legend for migration flow
- 10,000 people: thin line
- 50,000 people: thick line
"""
        answer = "图例显示线越粗，单条迁移路径的规模越大。"

        cleaned = KnowledgeEngine._ensure_population_legend_statement(
            answer,
            "请根据图例分析人口迁移流线。",
            summary,
        )

        self.assertEqual(cleaned, answer)

    def test_plain_course_prep_population_answer_stays_compact(self) -> None:
        config = self.build_config(with_llm=True)
        client = CapturingClient("中国人口分布受自然和社会经济因素共同影响。")
        engine = KnowledgeEngine(config, minimax_client=client)

        engine.answer(
            "为什么我国人口东南多、西北少？不要只归因于自然条件。",
            {"teaching_context": {"phase": "course_prep"}},
            teaching_task="teaching_explain",
        )

        system_prompt = client.calls[0]["messages"][0]["content"]
        self.assertIn("通常不超过 350 字", system_prompt)
        self.assertIn("严格区分人口总量、人口密度", system_prompt)
        self.assertIn("不要用“知识库认为”", system_prompt)
        self.assertNotIn("可以组织问题阶梯", system_prompt)

    def test_explicit_lesson_design_keeps_structured_prep_guidance(self) -> None:
        config = self.build_config(with_llm=True)
        client = CapturingClient("教学设计")
        engine = KnowledgeEngine(config, minimax_client=client)

        engine.answer(
            "请设计一节胡焕庸线教学课的问题链。",
            {"teaching_context": {"phase": "course_prep"}},
            teaching_task="teaching_question",
        )

        system_prompt = client.calls[0]["messages"][0]["content"]
        self.assertIn("可以组织问题阶梯", system_prompt)


if __name__ == "__main__":
    unittest.main()
