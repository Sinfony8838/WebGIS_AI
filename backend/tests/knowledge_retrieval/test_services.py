"""KnowledgeBaseService / KnowledgeService integration tests:
permission isolation before caching, cache invalidation on writes,
insufficient-evidence payloads and provenance fields."""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from backend.app.config import AppConfig
from backend.app.services.knowledge import KnowledgeService
from backend.app.services.knowledge_base import KnowledgeBaseService


class KnowledgeRetrievalServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.config = AppConfig()
        self.knowledge_dir = self.root / "knowledge"
        self.knowledge_dir.mkdir(parents=True, exist_ok=True)
        self.config.knowledge_dir = self.knowledge_dir
        self.service = KnowledgeBaseService(self.config)

    def write_manifest(self, items: list[dict]) -> None:
        (self.knowledge_dir / "kb_manifest.json").write_text(
            json.dumps({"version": "1.0", "items": items}, ensure_ascii=False),
            encoding="utf-8",
        )

    def seed(self) -> None:
        self.service.upsert_item(
            {
                "id": "cn_density",
                "title": "全国人口密度图",
                "topic": "population_distribution",
                "region": "china",
                "time": "2020",
                "keywords": ["全国", "人口密度"],
                "summary": "全国人口密度分布教学图。",
            }
        )
        self.service.upsert_item(
            {
                "id": "sh_density",
                "title": "上海人口密度图",
                "topic": "population_distribution",
                "region": "shanghai",
                "time": "2020",
                "keywords": ["上海", "人口密度"],
                "summary": "上海人口密度分布教学图。",
            }
        )

    def test_natural_chinese_search_ranks_region_match(self) -> None:
        self.seed()
        payload = self.service.search("上海的人口密度怎么样", limit=3)
        self.assertEqual(payload["status"], "success")
        self.assertFalse(payload["insufficient"])
        self.assertEqual(payload["items"][0]["id"], "sh_density")
        self.assertGreater(payload["items"][0]["retrieval_score"], 0)

    def test_year_constraint_not_confused(self) -> None:
        self.service.upsert_item(
            {
                "id": "census_2000",
                "title": "2000年人口普查资料",
                "topic": "population_census",
                "region": "china",
                "time": "2000",
                "keywords": ["人口普查", "五普"],
                "summary": "2000年人口普查资料。",
            }
        )
        self.service.upsert_item(
            {
                "id": "census_2020",
                "title": "2020年人口普查资料",
                "topic": "population_census",
                "region": "china",
                "time": "2020",
                "keywords": ["人口普查", "七普"],
                "summary": "2020年人口普查资料。",
            }
        )
        result = self.service.search("2000年人口普查资料", limit=3)
        self.assertEqual(result["items"][0]["id"], "census_2000")
        self.assertNotIn("census_2020", [item["id"] for item in result["items"]])

    def test_no_answer_returns_insufficient_not_top_n(self) -> None:
        self.seed()
        payload = self.service.search("今天上海的天气怎么样", limit=3)
        self.assertTrue(payload["insufficient"])
        self.assertEqual(payload["items"], [])
        self.assertTrue(payload["message"])

    def test_private_items_isolated_across_users_and_cache(self) -> None:
        self.seed()
        self.service.upsert_item(
            {
                "id": "private_a",
                "title": "私有案例",
                "topic": "case",
                "keywords": ["私有案例"],
                "summary": "用户A的私有案例。",
                "owner_user_id": "user_a",
            },
            owner_user_id="user_a",
        )
        self.service.upsert_item(
            {
                "id": "private_b",
                "title": "私有案例",
                "topic": "case",
                "keywords": ["私有案例"],
                "summary": "用户B的私有案例。",
                "owner_user_id": "user_b",
            },
            owner_user_id="user_b",
        )
        # 同一句话交替查询，覆盖结果缓存的键隔离。
        for _ in range(2):
            ids_a = [i["id"] for i in self.service.search("私有案例", owner_user_id="user_a")["items"]]
            ids_b = [i["id"] for i in self.service.search("私有案例", owner_user_id="user_b")["items"]]
            self.assertNotIn("private_b", ids_a)
            self.assertNotIn("private_a", ids_b)
        # 匿名（未登录 owner）查询看不到任何私有条目。
        anonymous = [i["id"] for i in self.service.search("私有案例")["items"]]
        self.assertNotIn("private_a", anonymous)
        self.assertNotIn("private_b", anonymous)

    def test_add_update_delete_invalidate_search(self) -> None:
        self.seed()
        self.service.upsert_item(
            {
                "id": "fresh",
                "title": "长三角城市群专题",
                "topic": "urbanization",
                "region": "china",
                "keywords": ["长三角", "城市群"],
                "summary": "长三角城市群专题资料。",
                "owner_user_id": "teacher",
            },
            owner_user_id="teacher",
        )
        self.assertIn(
            "fresh", [i["id"] for i in self.service.search("长三角城市群", owner_user_id="teacher")["items"]]
        )
        self.service.upsert_item(
            {
                "id": "fresh",
                "title": "长三角与成渝城市群专题",
                "topic": "urbanization",
                "region": "china",
                "keywords": ["长三角", "成渝"],
                "summary": "更新后补充成渝对比视角。",
                "owner_user_id": "teacher",
            },
            owner_user_id="teacher",
        )
        self.assertIn(
            "fresh", [i["id"] for i in self.service.search("成渝城市群", owner_user_id="teacher")["items"]]
        )
        self.service.delete_item("fresh", owner_user_id="teacher")
        self.assertNotIn(
            "fresh", [i["id"] for i in self.service.search("长三角城市群", owner_user_id="teacher")["items"]]
        )

    def test_delete_builtin_rejected(self) -> None:
        self.seed()
        with self.assertRaises(ValueError):
            self.service.delete_item("cn_density", owner_user_id="someone")

    def test_provenance_fields_present(self) -> None:
        self.seed()
        item = self.service.search("全国人口密度", limit=1)["items"][0]
        for field in ("id", "title", "source", "time", "region"):
            self.assertIn(field, item)
        self.assertTrue(str(item["id"]))


class KnowledgeServiceRetrievalTest(unittest.TestCase):
    def test_card_search_and_abstain(self) -> None:
        root_dir = Path(__file__).resolve().parents[3]
        service = KnowledgeService(AppConfig(root_dir=root_dir))
        cards = service.search("胡焕庸线两侧为什么差异这么大", limit=3)
        self.assertEqual(cards[0]["id"], "kb_hu_line")
        # 无关问题如实返回空，不硬凑卡片。
        self.assertEqual(service.search("珠穆朗玛峰有多高", limit=3), [])


if __name__ == "__main__":
    unittest.main()
