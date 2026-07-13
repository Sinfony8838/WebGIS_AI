from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.app.config import AppConfig
from backend.app.runtime import WebGISRuntime
from backend.app.services.knowledge import KnowledgeService
from backend.app.store import RuntimeStore


class KnowledgeServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        root_dir = Path(__file__).resolve().parents[2]
        self.config = AppConfig(root_dir=root_dir)
        self.service = KnowledgeService(self.config)

    def test_manifest_seeded_with_population_cards(self) -> None:
        items = self.service.list_items()
        self.assertGreaterEqual(len(items), 8)
        ids = {item["id"] for item in items}
        self.assertIn("kb_hu_line", ids)
        self.assertIn("kb_population_density", ids)

    def test_search_matches_hu_line_question(self) -> None:
        results = self.service.search("胡焕庸线两侧为什么人口差异这么大", limit=3)
        self.assertTrue(results)
        self.assertEqual(results[0]["id"], "kb_hu_line")

    def test_search_empty_query_returns_nothing(self) -> None:
        self.assertEqual(self.service.search("  "), [])


class KnowledgeAnswerFallbackTest(unittest.TestCase):
    def test_explain_falls_back_without_llm_and_appends_kb_reference(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root_dir = Path(__file__).resolve().parents[2]
        config = AppConfig(root_dir=root_dir)
        config.minimax_api_key = ""
        config.data_dir = Path(temp_dir.name) / "backend" / "data"
        config.state_dir = config.data_dir / "state"
        config.uploads_dir = config.data_dir / "uploads"
        config.outputs_dir = config.data_dir / "outputs"
        config.state_file = config.state_dir / "runtime.json"
        config.ensure_dirs()
        runtime = WebGISRuntime(config=config, store=RuntimeStore(config.state_file))
        project_id = runtime.create_project()["project_id"]
        runtime.apply_lesson_scene(project_id, "lesson_builtin_population_distribution", "s4")

        project = runtime.store.get_project(project_id)
        answer = runtime._compose_knowledge_answer(project, "胡焕庸线两侧为什么差异这么大", {})

        self.assertIn("知识参考", answer)
        self.assertIn("胡焕庸线", answer)


if __name__ == "__main__":
    unittest.main()
