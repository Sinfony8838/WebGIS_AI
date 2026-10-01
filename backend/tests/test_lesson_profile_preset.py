"""课前剖面预设（任务3/4）：规范化、模拟测试保存、发布进入课时版本与课堂快照。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.app.config import AppConfig
from backend.app.runtime import WebGISRuntime
from backend.app.store import RuntimeStore
from backend.app.services.lessons import normalize_profile_preset
from backend.tests.test_lesson_rehearsal import _valid_plan


class NormalizeProfilePresetTest(unittest.TestCase):
    def test_drops_invalid_lines_and_clamps_window_geometry(self) -> None:
        preset = normalize_profile_preset({
            "lines": [
                {"id": "l1", "name": "测线 1", "coordinates": [[121.4, 31.2], [121.6, 31.25]], "total_km": 21.4, "color": "#087cad"},
                {"id": "bad", "name": "坏线", "coordinates": [[999, 31]], "total_km": 0},
                {"id": "empty", "name": "空线", "coordinates": [], "total_km": 0},
            ],
            "windows": [
                {"kind": "population", "record_index": 0, "source_id": "shanghai_worldpop_2020", "x": -0.5, "y": 0.1, "w": 0.34, "h": 0.42},
                {"kind": "terrain", "record_index": 0, "x": 0.9, "y": 0.9, "w": 0.34, "h": 0.42},
                {"kind": "bogus", "record_index": 0},
                {"kind": "population", "record_index": 9},
            ],
        })
        self.assertEqual(len(preset["lines"]), 1)
        # 越界坐标收敛：x 不小于 0；x+w 不超过 1（保持窗口完整可见）。
        pop = preset["windows"][0]
        self.assertEqual(pop["x"], 0.0)
        terrain = preset["windows"][1]
        self.assertLessEqual(terrain["x"] + terrain["w"], 1.0 + 1e-9)
        self.assertLessEqual(terrain["y"] + terrain["h"], 1.0 + 1e-9)
        # 非法 kind 与越界 record_index 的窗口被丢弃
        self.assertEqual(len(preset["windows"]), 2)

    def test_empty_preset_returns_empty_dict(self) -> None:
        self.assertEqual(normalize_profile_preset(None), {})
        self.assertEqual(normalize_profile_preset({"lines": []}), {})
        self.assertEqual(normalize_profile_preset({"lines": [{"id": "x", "coordinates": [[1, 1]]}]}), {})


class RehearsalProfilePresetTest(unittest.TestCase):
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
        self.addCleanup(self.temp_dir.cleanup)

    def _make_lesson(self):
        plan = _valid_plan()
        return self.runtime.classroom.lesson_service.create_lesson(
            {
                "title": plan["title"], "subject": "地理", "grade": plan["grade"],
                "objectives": plan["objectives"], "stages": plan["stages"],
                "metadata": {"design_id": "design_x", "project_id": self.project,
                             "created_from": "lesson_design", "lesson_version": 1, "ready_for_class": False},
                "plan": plan,
            },
            source="assistant_draft", owner_user_id="local_admin",
        )

    def _preset(self) -> dict:
        return {
            "lines": [
                {"id": "msr_a", "name": "测线 1", "coordinates": [[121.4, 31.2], [121.6, 31.25]], "total_km": 21.4, "color": "#087cad"},
                {"id": "msr_b", "name": "测线 2", "coordinates": [[120.9, 30.9], [121.1, 31.0]], "total_km": 24.0, "color": "#d97706"},
            ],
            "windows": [
                {"kind": "population", "record_index": 0, "source_id": "shanghai_worldpop_2020", "x": 0.05, "y": 0.12, "w": 0.34, "h": 0.42},
                {"kind": "terrain", "record_index": 0, "x": 0.45, "y": 0.12, "w": 0.34, "h": 0.42},
                {"kind": "population", "record_index": 1, "source_id": "layer_x", "x": 0.05, "y": 0.56, "w": 0.34, "h": 0.42},
                {"kind": "terrain", "record_index": 1, "x": 0.45, "y": 0.56, "w": 0.34, "h": 0.42},
            ],
        }

    def test_rehearsal_saves_and_publishes_profile_preset_with_version(self) -> None:
        cw = self.runtime.classroom
        lesson = self._make_lesson()
        created = cw.create_lesson_rehearsal(self.project, lesson.lesson_id, "local_admin")
        rehearsal_id = created["rehearsal"]["rehearsal_id"]
        stage_id = created["rehearsal"]["working_copy"]["stages"][0]["stage_id"]

        # 保存预设：写入工作副本环节
        updated = cw.update_lesson_rehearsal(rehearsal_id, profile_preset={"stage_id": stage_id, "preset": self._preset()})
        stage = updated["rehearsal"]["working_copy"]["stages"][0]
        self.assertEqual(len(stage["profile_preset"]["lines"]), 2)
        self.assertEqual(len(stage["profile_preset"]["windows"]), 4)

        # 没有测线的预设被拒绝（提示先画测线）
        with self.assertRaises(ValueError):
            cw.update_lesson_rehearsal(rehearsal_id, profile_preset={"stage_id": stage_id, "preset": {"lines": [], "windows": []}})

        # 版本冲突检查
        current = self.runtime.classroom.lesson_rehearsal.get(rehearsal_id)
        with self.assertRaises(ValueError):
            cw.update_lesson_rehearsal(
                rehearsal_id,
                profile_preset={"stage_id": stage_id, "preset": self._preset()},
                expected_revision=current.revision + 5,
            )

        # 完成发布：预设进入新课时版本
        completed = cw.complete_lesson_rehearsal(rehearsal_id)
        published = completed["lesson"]
        pub_stage = next(s for s in published["stages"] if s["stage_id"] == stage_id)
        self.assertEqual(len(pub_stage["profile_preset"]["windows"]), 4)
        self.assertEqual(published["metadata"]["lesson_version"], 2)
        self.assertTrue(published["metadata"]["ready_for_class"])

        # 开课快照带预设；正在运行的课堂继续使用快照
        session = cw.create_class_session(published["lesson_id"], self.project)["session"]
        snap_stage = next(s for s in session["metadata"]["lesson_snapshot"]["stages"] if s["stage_id"] == stage_id)
        self.assertEqual(len(snap_stage["profile_preset"]["lines"]), 2)

    def test_lesson_save_normalizes_profile_preset_stage_whitelist(self) -> None:
        lesson = self._make_lesson()
        payload = lesson.to_dict()
        payload["stages"][0]["profile_preset"] = {
            "lines": [{"id": "l1", "name": "测线 1", "coordinates": [[121.4, 31.2], [121.5, 31.3]], "total_km": 12, "color": "#111"}],
            "windows": [{"kind": "nope", "record_index": 0}],
        }
        self.runtime.classroom.lesson_service.update_lesson(lesson.lesson_id, payload)
        refreshed = self.runtime.classroom.lesson_service.get_lesson(lesson.lesson_id)
        preset = refreshed.stages[0].get("profile_preset")
        # 窗口全部非法 → 只保留测线；结构整体合法
        self.assertEqual(len(preset["lines"]), 1)
        self.assertEqual(preset["windows"], [])


if __name__ == "__main__":
    unittest.main()
