from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.app.config import AppConfig
from backend.app.models import LayerRecord
from backend.app.services.knowledge_base import KnowledgeBaseService


class KnowledgeBaseServiceTest(unittest.TestCase):
    def build_service(self) -> tuple[KnowledgeBaseService, Path]:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        config = AppConfig()
        knowledge_dir = Path(temp_dir.name) / "knowledge"
        knowledge_dir.mkdir(parents=True, exist_ok=True)
        config.knowledge_dir = knowledge_dir
        service = KnowledgeBaseService(config)
        return service, knowledge_dir

    def test_manifest_is_created_when_missing(self) -> None:
        service, knowledge_dir = self.build_service()
        result = service.get_manifest()
        self.assertEqual(result["status"], "success")
        self.assertTrue((knowledge_dir / "kb_manifest.json").exists())
        self.assertIn("items", result)

    def test_upsert_and_search_manifest_item(self) -> None:
        service, _ = self.build_service()
        item = service.upsert_item(
            {
                "id": "ports_demo",
                "title": "沿海港口分布",
                "topic": "coastal_economy",
                "region": "china_east",
                "keywords": ["港口", "区位"],
                "summary": "港口沿海集聚。",
                "canonical_answer": "港口通常在沿海和河口区域集聚，受区位与交通条件影响。",
                "teaching_points": ["先看分布。", "再看区位。"],
            }
        )
        self.assertEqual(item["id"], "ports_demo")
        self.assertEqual(item["materials"], [])

        search = service.search(query="港口", topic="coastal")
        self.assertEqual(search["status"], "success")
        self.assertEqual(search["total"], 1)
        self.assertEqual(search["items"][0]["id"], "ports_demo")

    def test_add_material_to_manifest_item(self) -> None:
        service, _ = self.build_service()
        service.upsert_item(
            {
                "id": "delta_demo",
                "title": "Delta Demo",
                "topic": "regional",
                "summary": "Delta teaching material.",
            }
        )

        material = service.add_material_to_item(
            "delta_demo",
            {
                "title": "Delta video",
                "url": "https://example.edu/delta.mp4",
                "type": "video",
                "region_binding": {"name": "Delta", "layer_id": "admin_layer"},
            },
        )

        self.assertEqual(material["type"], "video")
        search = service.search(query="Delta")
        self.assertEqual(search["items"][0]["materials"][0]["region_binding"]["name"], "Delta")

    def test_build_item_from_layer_creates_dataset_reference(self) -> None:
        service, _ = self.build_service()
        layer = LayerRecord.create(
            layer_id="upload_population_points",
            name="人口点图",
            kind="vector",
            source="upload",
            geometry_type="Point",
            metadata={"source_file": "population.csv"},
        )
        item = service.build_item_from_layer("project_1", layer, {"topic": "population", "keywords": ["人口", "分布"]})
        self.assertEqual(item["topic"], "population")
        self.assertTrue(item["dataset_refs"])
        self.assertEqual(item["dataset_refs"][0]["layer_id"], "upload_population_points")

    def test_topics_aggregate_manifest_status(self) -> None:
        service, _ = self.build_service()
        service.upsert_item(
            {
                "id": "census_2020",
                "title": "中国第七次人口普查资料",
                "topic": "population_census",
                "status": "stored_only",
                "summary": "人口普查资料。",
            }
        )
        service.upsert_item(
            {
                "id": "koppen",
                "title": "世界柯本气候分区图",
                "topic": "climate_zoning",
                "status": "renderable_layer",
                "summary": "可渲染影像图层。",
            }
        )

        topics = service.topics()
        by_topic = {item["topic"]: item for item in topics["items"]}
        self.assertEqual(by_topic["population_census"]["stored_only_count"], 1)
        self.assertEqual(by_topic["climate_zoning"]["renderable_count"], 1)

    def test_engine_units_merge_geo_and_manifest(self) -> None:
        service, knowledge_dir = self.build_service()
        (knowledge_dir / "geo_knowledge.json").write_text(
            json.dumps(
                [
                    {
                        "id": "base_1",
                        "title": "基础条目",
                        "tags": ["基础"],
                        "canonical_answer": "基础答案",
                        "teaching_points": ["基础讲解"],
                        "citations": [],
                    }
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        service.upsert_item(
            {
                "id": "manifest_1",
                "title": "清单条目",
                "topic": "demo_topic",
                "keywords": ["专题"],
                "summary": "清单摘要",
                "canonical_answer": "清单答案",
                "teaching_points": ["清单讲解"],
            }
        )

        units = service.build_engine_units()
        ids = {item["id"] for item in units}
        self.assertIn("base_1", ids)
        self.assertIn("manifest_1", ids)


if __name__ == "__main__":
    unittest.main()
