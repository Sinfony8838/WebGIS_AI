"""Knowledge retrieval engine unit tests.

Behaviour tests run against the real builtin knowledge corpus (same data
the production services index), because the evidence guard is calibrated
for classroom-scale corpora; pure functions are tested on fixed inputs.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from backend.app.config import AppConfig
from backend.app.services.knowledge_retrieval.constraints import (
    DocumentConstraints,
    extract_constraints,
)
from backend.app.services.knowledge_retrieval.engine import RetrievalDoc, RetrievalEngine
from backend.app.services.knowledge_retrieval.scoring import (
    ScoredDoc,
    char_bigrams,
    dedupe_hits,
    jaccard,
)
from backend.app.services.knowledge_retrieval.textnorm import normalize_text
from backend.app.services.knowledge_retrieval.tokenize import tokenize

REPO_ROOT = Path(__file__).resolve().parents[3]


def build_builtin_engine() -> RetrievalEngine:
    """Index the real builtin manifest + geo units, like production paths."""
    knowledge_dir = AppConfig(root_dir=REPO_ROOT).builtin_dir / "knowledge"
    items: list[dict] = []
    manifest = json.loads((knowledge_dir / "kb_manifest.json").read_text(encoding="utf-8"))
    items.extend(item for item in manifest.get("items", []) if isinstance(item, dict))
    geo = json.loads((knowledge_dir / "geo_knowledge.json").read_text(encoding="utf-8"))
    for unit in geo:
        items.append(
            {
                "id": unit.get("id"),
                "title": unit.get("title"),
                "topic": unit.get("domain") or "geo_concept",
                "region": "",
                "time": "",
                "keywords": unit.get("tags") or [],
                "summary": unit.get("canonical_answer") or "",
                "canonical_answer": unit.get("canonical_answer") or "",
                "teaching_points": unit.get("teaching_points") or [],
            }
        )
    return RetrievalEngine([RetrievalDoc.from_mapping(item) for item in items])


class NormalizeTextTest(unittest.TestCase):
    def test_fullwidth_and_case(self) -> None:
        self.assertEqual(normalize_text("ＱＧＩＳ"), "qgis")
        self.assertEqual(normalize_text("人口密度？"), "人口密度")

    def test_digits_kept(self) -> None:
        self.assertEqual(normalize_text("2020年 七普"), "2020年 七普")


class TokenizeTest(unittest.TestCase):
    def test_lexicon_terms_win_over_bigrams(self) -> None:
        tokens = tokenize("上海人口密度", {"人口密度"})
        self.assertIn("人口密度", tokens)
        self.assertNotIn("人口", tokens)

    def test_function_fragments_dropped(self) -> None:
        tokens = tokenize("是一条什么线")
        self.assertNotIn("是一", tokens)
        self.assertNotIn("条什", tokens)
        self.assertNotIn("什么", tokens)


class ConstraintsTest(unittest.TestCase):
    def test_region_year_metric(self) -> None:
        parsed = extract_constraints("上海2010年的人口密度是多少")
        self.assertEqual(parsed.region, "shanghai")
        self.assertIn(2010, parsed.years)
        self.assertIn("density", parsed.metrics)

    def test_census_alias_maps_to_year(self) -> None:
        parsed = extract_constraints("五普资料")
        self.assertEqual(parsed.years, (2000,))
        self.assertEqual(parsed.census_terms, ("五普",))

    def test_china_aliases_canonical(self) -> None:
        for word in ("全国", "我国", "中国"):
            self.assertEqual(extract_constraints(f"{word}人口").region, "china")

    def test_document_constraints_from_fields(self) -> None:
        parsed = DocumentConstraints.from_fields(
            region="shanghai",
            time_value="2010",
            text="上海市人口普查汇总，涉及人口密度",
            topic="population_census",
        )
        self.assertEqual(parsed.region, "shanghai")
        self.assertEqual(parsed.years, (2010,))
        self.assertIn("density", parsed.metrics)
        self.assertEqual(parsed.topic, "population_census")


class ScoringHelpersTest(unittest.TestCase):
    def test_jaccard(self) -> None:
        self.assertAlmostEqual(jaccard({"a", "b"}, {"a", "b", "c"}), 2.0 / 3.0)

    def test_char_bigrams(self) -> None:
        self.assertEqual(char_bigrams("人口"), {"人口"})

    def test_dedupe_keeps_different_census_years(self) -> None:
        wupu = RetrievalDoc.from_mapping(
            {
                "id": "wupu",
                "title": "中国第五次人口普查资料",
                "canonical_answer": "第五次全国人口普查相关空间数据资料，适合时序对比。",
            }
        )
        liupu = RetrievalDoc.from_mapping(
            {
                "id": "liupu",
                "title": "中国第六次人口普查资料",
                "canonical_answer": "第六次全国人口普查相关空间数据资料，先作为资料保存。",
            }
        )
        kept = dedupe_hits(
            [
                ScoredDoc(doc_id="wupu", score=1.0, coverage=1.0),
                ScoredDoc(doc_id="liupu", score=1.0, coverage=1.0),
            ],
            {"wupu": wupu.title, "liupu": liupu.title},
            {"wupu": wupu.canonical_answer, "liupu": liupu.canonical_answer},
            years_by_id={"wupu": (2000,), "liupu": (2010,)},
        )
        self.assertEqual([row.doc_id for row in kept], ["wupu", "liupu"])

    def test_dedupe_merges_same_map_variants(self) -> None:
        hd = RetrievalDoc.from_mapping(
            {"id": "hd", "title": "世界柯本气候分区图（高清）", "canonical_answer": "高清影像，可叠加讲解全球气候分区。"}
        )
        lite = RetrievalDoc.from_mapping(
            {"id": "lite", "title": "世界柯本气候分区图（轻量）", "canonical_answer": "轻量影像，可叠加讲解全球气候分区。"}
        )
        kept = dedupe_hits(
            [
                ScoredDoc(doc_id="hd", score=1.0, coverage=1.0),
                ScoredDoc(doc_id="lite", score=1.0, coverage=1.0),
            ],
            {"hd": hd.title, "lite": lite.title},
            {"hd": hd.canonical_answer, "lite": lite.canonical_answer},
        )
        self.assertEqual([row.doc_id for row in kept], ["hd"])


class RetrievalEngineBehaviourTest(unittest.TestCase):
    """Behaviour checks on the real builtin corpus (classroom scale)."""

    def setUp(self) -> None:
        self.engine = build_builtin_engine()

    def test_natural_question_hits_top(self) -> None:
        result = self.engine.search("胡焕庸线两侧为什么人口差异这么大", limit=3)
        self.assertFalse(result.insufficient)
        self.assertEqual(result.ids[0], "kb_hu_line")

    def test_shanghai_question_prefers_shanghai_material(self) -> None:
        result = self.engine.search("上海的人口密度怎么样", limit=3)
        self.assertFalse(result.insufficient)
        self.assertEqual(result.ids[0], "shanghai_population_density_preclass")

    def test_year_constraint_not_confused(self) -> None:
        result = self.engine.search("2000年人口普查资料", limit=5)
        self.assertEqual(result.ids[0], "project_349d85af43884d3cb1b5904ce6bd0a94_upload___a1f9b3d2")
        self.assertNotIn("project_349d85af43884d3cb1b5904ce6bd0a94_upload___fffdbf28", result.ids)

    def test_weather_question_abstains(self) -> None:
        result = self.engine.search("今天上海的天气怎么样", limit=3)
        self.assertTrue(result.insufficient)
        self.assertEqual(result.hits, [])

    def test_off_topic_question_abstains(self) -> None:
        result = self.engine.search("中国的GDP是多少", limit=3)
        self.assertTrue(result.insufficient)

    def test_de_head_missing_subject_abstains(self) -> None:
        result = self.engine.search("河流的航运价值怎么评价", limit=3)
        self.assertTrue(result.insufficient)

    def test_region_only_query_returns_region_docs(self) -> None:
        result = self.engine.search("上海", limit=5)
        self.assertFalse(result.insufficient)
        self.assertIn("shanghai_population_density_preclass", result.ids)

    def test_census_alias_constraint_path(self) -> None:
        result = self.engine.search("五普", limit=5)
        self.assertIn("project_349d85af43884d3cb1b5904ce6bd0a94_upload___a1f9b3d2", result.ids)

    def test_empty_query(self) -> None:
        self.assertTrue(self.engine.search("  ").insufficient)

    def test_teaching_points_match(self) -> None:
        result = self.engine.search("服务半径怎么画出来", limit=5)
        self.assertIn("gis_buffer_analysis", result.ids)


if __name__ == "__main__":
    unittest.main()
