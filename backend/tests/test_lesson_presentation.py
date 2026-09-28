from __future__ import annotations

import unittest


class PresentationNormalizationTest(unittest.TestCase):
    """环节 presentation 布局归一化：稳定 ID、白名单类型、归一化坐标。"""

    def test_normalize_keeps_valid_blocks_and_clamps_geometry(self) -> None:
        from backend.app.services.lessons import normalize_presentation

        layout = normalize_presentation({
            "blocks": [
                {"id": "blk_title", "type": "text", "text": "情境导入", "x": -0.2, "y": 0.0, "w": 2.0, "h": 0.1, "z": 0, "order": 1},
                {"id": "blk_q", "type": "question", "asset": {"question_id": "s1q1"}, "x": 0.1, "y": 0.5, "w": 0.5, "h": 0.3, "order": 2},
                {"id": "blk_img", "type": "image", "asset": {"url": "/files/uploads/p1/image_library/map.png", "mime_type": "image/png", "name": "map"}, "x": 0.5, "y": 0.4, "w": 0.4, "h": 0.4},
            ]
        })
        blocks = layout["blocks"]
        self.assertEqual(len(blocks), 3)
        self.assertEqual(blocks[0]["x"], 0.0)
        self.assertEqual(blocks[0]["w"], 1.0)
        self.assertEqual(blocks[1]["asset"]["question_id"], "s1q1")
        self.assertEqual(blocks[2]["asset"]["mime_type"], "image/png")

    def test_normalize_drops_unknown_types_and_empty_blocks(self) -> None:
        from backend.app.services.lessons import normalize_presentation

        self.assertEqual(normalize_presentation({"blocks": [{"id": "x", "type": "flash"}]}), {})
        self.assertEqual(normalize_presentation({"blocks": [{"type": "text"}]}), {})
        self.assertEqual(normalize_presentation(None), {})
        self.assertEqual(normalize_presentation({"blocks": "bad"}), {})

    def test_stage_whitelist_survives_lesson_save(self) -> None:
        from backend.app.config import AppConfig
        from backend.app.runtime import WebGISRuntime
        from backend.app.store import RuntimeStore
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            config = AppConfig(root_dir=Path(tmp))
            config.data_dir = Path(tmp) / "data"
            config.state_dir = config.data_dir / "state"
            config.uploads_dir = config.data_dir / "uploads"
            config.outputs_dir = config.data_dir / "outputs"
            config.state_file = config.state_dir / "runtime.json"
            config.minimax_api_key = ""
            config.minimax_token_plan_key = ""
            config.ensure_dirs()
            store = RuntimeStore(config.state_file)
            runtime = WebGISRuntime(config=config, store=store)
            project_id = runtime.create_project()["project_id"]
            layout = {"blocks": [{"id": "blk_title", "type": "text", "text": "标题", "x": 0.1, "y": 0.1, "w": 0.5, "h": 0.2, "z": 0, "order": 1}]}
            stage_with_layout = {
                "stage_id": "s1", "title": "导入", "minutes": 10,
                "questions": [{"text": "人口分布特点？", "answer": "东多西少", "explanation": "胡焕庸线"}],
                "presentation": layout,
            }
            lesson = runtime.classroom.lesson_service.create_lesson({
                "title": "展示布局", "grade": "高一", "objectives": [],
                "stages": [stage_with_layout],
                "metadata": {"project_id": project_id},
            })
            stage = runtime.classroom.lesson_service.get_lesson(lesson.lesson_id).stages[0]
            self.assertEqual(stage.get("presentation"), layout)


if __name__ == "__main__":
    unittest.main()
