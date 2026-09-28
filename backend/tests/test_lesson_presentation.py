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


def _rehearsal_runtime():
    from backend.app.config import AppConfig
    from backend.app.runtime import WebGISRuntime
    from backend.app.store import RuntimeStore
    import tempfile
    from pathlib import Path

    tmp = tempfile.TemporaryDirectory()
    config = AppConfig(root_dir=Path(tmp.name))
    config.data_dir = Path(tmp.name) / "data"
    config.state_dir = config.data_dir / "state"
    config.uploads_dir = config.data_dir / "uploads"
    config.outputs_dir = config.data_dir / "outputs"
    config.state_file = config.state_dir / "runtime.json"
    config.minimax_api_key = ""
    config.minimax_token_plan_key = ""
    config.ensure_dirs()
    store = RuntimeStore(config.state_file)
    runtime = WebGISRuntime(config=config, store=store)
    runtime._tmp_cleanup = tmp
    return runtime


class PresentationRehearsalUpdateTest(unittest.TestCase):
    """模拟测试中的展示布局编辑：修订号、素材校验、发布后进入课时。"""

    def setUp(self) -> None:
        self.runtime = _rehearsal_runtime()
        self.addCleanup(self.runtime._tmp_cleanup.cleanup)
        self.project_id = self.runtime.create_project()["project_id"]
        self.rehearsal_service = self.runtime.classroom.lesson_rehearsal

    def _active_rehearsal(self, with_question: bool = True):
        questions = [{"text": "人口分布特点？", "answer": "东多西少", "explanation": "胡焕庸线"}] if with_question else []
        lesson = self.runtime.classroom.lesson_service.create_lesson({
            "title": "展示布局", "grade": "高一", "objectives": [],
            "stages": [{"stage_id": "s1", "title": "导入", "minutes": 10, "questions": questions}],
            "metadata": {"project_id": self.project_id},
        })
        return self.rehearsal_service.create(self.project_id, lesson.lesson_id, "local_admin")

    def test_presentation_update_roundtrip_and_revision(self) -> None:
        rehearsal = self._active_rehearsal()
        layout = {"blocks": [{"id": "b1", "type": "text", "text": "情境导入", "x": 0.05, "y": 0.05, "w": 0.6, "h": 0.2, "order": 1}]}
        result = self.rehearsal_service.update(
            rehearsal["rehearsal"]["rehearsal_id"],
            presentation_update={"stage_id": "s1", "presentation": layout},
            expected_revision=rehearsal["rehearsal"]["revision"],
        )
        self.assertEqual(result["status"], "success")
        stage = result["rehearsal"]["working_copy"]["stages"][0]
        self.assertEqual(stage["presentation"]["blocks"][0]["text"], "情境导入")
        with self.assertRaisesRegex(ValueError, "已更新"):
            self.rehearsal_service.update(
                rehearsal["rehearsal"]["rehearsal_id"],
                presentation_update={"stage_id": "s1", "presentation": layout},
                expected_revision=rehearsal["rehearsal"]["revision"],
            )

    def test_presentation_update_rejects_unknown_question_reference(self) -> None:
        rehearsal = self._active_rehearsal()
        layout = {"blocks": [{"id": "b1", "type": "question", "asset": {"question_id": "ghost"}, "x": 0.1, "y": 0.1, "w": 0.4, "h": 0.2}]}
        with self.assertRaisesRegex(ValueError, "不存在于本环节"):
            self.rehearsal_service.update(
                rehearsal["rehearsal"]["rehearsal_id"],
                presentation_update={"stage_id": "s1", "presentation": layout},
                expected_revision=rehearsal["rehearsal"]["revision"],
            )

    def test_presentation_update_allows_project_assets_and_https_but_not_http(self) -> None:
        rehearsal = self._active_rehearsal(with_question=False)
        # 上传一张项目图片作为合法素材
        png_signature = bytes([0x89]) + b"PNG" + bytes([0x0D, 0x0A, 0x1A, 0x0A])
        image = self.runtime.upload_image_asset(self.project_id, "map.png", png_signature + b"0" * 64, "地图")
        image_url = image["artifact"]["metadata"]["public_url"]
        layout = {"blocks": [
            {"id": "b1", "type": "image", "asset": {"url": image_url}, "x": 0.1, "y": 0.1, "w": 0.4, "h": 0.4},
            {"id": "b2", "type": "video", "asset": {"url": "https://cdn.example.com/intro.mp4"}, "x": 0.5, "y": 0.1, "w": 0.4, "h": 0.3},
        ]}
        result = self.rehearsal_service.update(
            rehearsal["rehearsal"]["rehearsal_id"],
            presentation_update={"stage_id": "s1", "presentation": layout},
            expected_revision=rehearsal["rehearsal"]["revision"],
        )
        self.assertEqual(result["status"], "success")
        http_layout = {"blocks": [{"id": "b3", "type": "image", "asset": {"url": "http://insecure.example.com/x.png"}, "x": 0.1, "y": 0.1, "w": 0.4, "h": 0.4}]}
        with self.assertRaisesRegex(ValueError, "https"):
            self.rehearsal_service.update(
                rehearsal["rehearsal"]["rehearsal_id"],
                presentation_update={"stage_id": "s1", "presentation": http_layout},
                expected_revision=result["rehearsal"]["revision"],
            )

    def test_completed_rehearsal_publishes_presentation_into_lesson(self) -> None:
        from backend.tests.test_lesson_design import _table_ready_draft
        draft = _table_ready_draft()
        layout = {"blocks": [{"id": "b1", "type": "text", "text": "标题", "x": 0.1, "y": 0.1, "w": 0.5, "h": 0.2}]}
        draft["stages"][0]["presentation"] = layout
        lesson = self.runtime.classroom.lesson_service.create_lesson({
            "title": draft["title"], "grade": draft["grade"], "objectives": draft["objectives"],
            "stages": draft["stages"], "plan": draft,
            "metadata": {"project_id": self.project_id},
        })
        rehearsal = self.rehearsal_service.create(self.project_id, lesson.lesson_id, "local_admin")
        result = self.rehearsal_service.update(
            rehearsal["rehearsal"]["rehearsal_id"],
            presentation_update={"stage_id": "s1", "presentation": layout},
            expected_revision=rehearsal["rehearsal"]["revision"],
        )
        revision = result["rehearsal"]["revision"]
        completed = self.rehearsal_service.complete(rehearsal["rehearsal"]["rehearsal_id"], revision)
        lesson = self.runtime.store.get_lesson(completed["lesson"]["lesson_id"])
        self.assertEqual(lesson.stages[0].get("presentation")["blocks"][0]["text"], "标题")
