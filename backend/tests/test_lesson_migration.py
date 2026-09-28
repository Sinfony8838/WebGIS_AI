from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.app.config import AppConfig
from backend.app.runtime import WebGISRuntime
from backend.app.store import RuntimeStore


def _legacy_draft() -> dict:
    return {
        "title": "人口迁移",
        "core_questions": {"core": "人口为什么会迁移？", "sub_questions": ["谁在迁移？", "迁往哪里？", "为什么迁？"]},
        "capabilities": [
            {"id": "population_top20", "reason": "TOP20 查询"},
            {"id": "map_2d", "reason": "底图"},
        ],
        "stages": [
            {"stage_id": "s1", "title": "情境导入", "minutes": 10, "question_chain": ["人口分布均匀吗？"], "scene": {}},
            {"stage_id": "s2", "title": "成因探究", "minutes": 30, "scene": None},
        ],
    }


class LessonMigrationTest(unittest.TestCase):
    """旧草稿「核心问题与问题链 / GIS·AI 能力」的一次性迁移预览与写入。"""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root_dir = Path(__file__).resolve().parents[2]
        config = AppConfig(root_dir=root_dir)
        config.data_dir = Path(self.temp_dir.name) / "backend" / "data"
        config.state_dir = config.data_dir / "state"
        config.uploads_dir = config.data_dir / "uploads"
        config.outputs_dir = config.data_dir / "outputs"
        config.state_file = config.state_dir / "runtime.json"
        config.minimax_api_key = ""
        config.minimax_token_plan_key = ""
        config.ensure_dirs()
        self.store = RuntimeStore(config.state_file)
        self.runtime = WebGISRuntime(config=config, store=self.store)
        self.project = self.runtime.create_project()["project_id"]
        self.service = self.runtime.classroom.lesson_design
        self.addCleanup(self.temp_dir.cleanup)

    def _design(self):
        design = self.service.create_or_resume(self.project, "local_admin")
        design.draft.update(_legacy_draft())
        self.store.upsert_lesson_design(design)
        return design

    def test_preview_maps_questions_and_scene_capabilities_deterministically(self) -> None:
        design = self._design()
        preview = self.service.migration_preview(design.design_id)
        self.assertTrue(preview["available"])
        self.assertFalse(preview["applied"])
        by_kind = {}
        for item in preview["items"]:
            by_kind.setdefault(item["kind"], []).append(item)
        # 核心问题 → 环节1 问题链首位
        core_items = [item for item in by_kind.get("question", []) if item["detail"] == "人口为什么会迁移？"]
        self.assertEqual(core_items[0]["target_stage_id"], "s1")
        self.assertEqual(core_items[0]["position"], 0)
        # 子问题按序轮流分配：3 条 → s1、s2、s1（追加，去重）
        subs = [item for item in by_kind.get("question", []) if item["detail"] != "人口为什么会迁移？"]
        self.assertEqual([item["target_stage_id"] for item in subs], ["s1", "s2", "s1"])
        # 非场景类能力标记为不可迁移，保留在原字段
        scene_items = by_kind.get("unmappable", [])
        self.assertEqual({item["detail"] for item in scene_items}, {"population_top20", "map_2d"})

    def test_preview_routes_template_capability_into_first_stage_scene(self) -> None:
        design = self._design()
        design.draft["capabilities"] = [{"id": "population_distribution", "reason": "人口专题图"}]
        self.store.upsert_lesson_design(design)
        preview = self.service.migration_preview(design.design_id)
        scene_items = [item for item in preview["items"] if item["kind"] == "template"]
        self.assertEqual(len(scene_items), 1)
        self.assertEqual(scene_items[0]["target_stage_id"], "s1")

    def test_preview_unavailable_without_legacy_content_or_stages(self) -> None:
        design = self.service.create_or_resume(self.project, "local_admin")
        self.assertFalse(self.service.migration_preview(design.design_id)["available"])
        empty = self.service.create_or_resume(self.project, "local_admin")
        empty.draft.update({"core_questions": {"core": "问题", "sub_questions": ["子问题"]}, "stages": []})
        self.store.upsert_lesson_design(empty)
        self.assertFalse(self.service.migration_preview(empty.design_id)["available"])

    def test_apply_writes_into_stages_and_marks_flag_once(self) -> None:
        design = self._design()
        latest = self.service.get(design.design_id)
        result = self.service.apply_migration(design.design_id, latest.revision)
        applied_draft = self.service.get(design.design_id).draft
        self.assertTrue(applied_draft["legacy_migration_applied"])
        self.assertEqual(applied_draft["stages"][0]["question_chain"][0], "人口为什么会迁移？")
        self.assertIn("谁在迁移？", applied_draft["stages"][0]["question_chain"])
        self.assertIn("为什么迁？", applied_draft["stages"][0]["question_chain"])
        self.assertIn("迁往哪里？", applied_draft["stages"][1]["question_chain"])
        # 旧字段保留可读
        self.assertEqual(applied_draft["core_questions"]["core"], "人口为什么会迁移？")
        self.assertEqual(applied_draft["capabilities"][0]["id"], "population_top20")
        # 已应用后再预览/应用
        self.assertFalse(self.service.migration_preview(design.design_id)["available"])
        latest = self.service.get(design.design_id)
        with self.assertRaisesRegex(ValueError, "已迁移"):
            self.service.apply_migration(design.design_id, latest.revision)

    def test_apply_revision_conflict_and_published_lesson_untouched(self) -> None:
        design = self._design()
        with self.assertRaisesRegex(ValueError, "已更新"):
            self.service.apply_migration(design.design_id, design.revision + 5)

    def test_apply_never_mutates_the_base_published_lesson(self) -> None:
        import json

        base = self.store.get_lesson("lesson_builtin_population_shanghai_world")
        before = json.dumps(base.to_dict(), sort_keys=True, ensure_ascii=False)
        design = self.service.create_or_resume(self.project, "local_admin", base.lesson_id)
        design.draft["core_questions"] = _legacy_draft()["core_questions"]
        design.draft["capabilities"] = _legacy_draft()["capabilities"]
        self.store.upsert_lesson_design(design)
        latest = self.service.get(design.design_id)
        self.service.apply_migration(design.design_id, latest.revision)
        after = json.dumps(self.store.get_lesson(base.lesson_id).to_dict(), sort_keys=True, ensure_ascii=False)
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
