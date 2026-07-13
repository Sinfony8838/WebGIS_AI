from __future__ import annotations

import json
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend.app.services.timeline_service import TimelineService


class TimelineServiceParseTest(unittest.TestCase):
    """Tests for TimelineService._parse_llm_json."""

    def test_plain_array(self) -> None:
        raw = json.dumps([{"stage": "导入", "title": "T", "description": "", "durationMin": 5}])
        result = TimelineService._parse_llm_json(raw)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["stage"], "导入")

    def test_code_fenced(self) -> None:
        payload = [{"stage": "新授", "title": "X", "description": "", "durationMin": 10}]
        raw = "```json\n" + json.dumps(payload) + "\n```"
        result = TimelineService._parse_llm_json(raw)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["stage"], "新授")

    def test_with_preamble_text(self) -> None:
        payload = [{"stage": "练习", "title": "P", "description": "", "durationMin": 8}]
        raw = "以下是提取的教学流程：\n" + json.dumps(payload) + "\n以上为分析结果。"
        result = TimelineService._parse_llm_json(raw)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["stage"], "练习")

    def test_nodes_key_dict(self) -> None:
        payload = {"nodes": [{"stage": "小结", "title": "S", "description": "", "durationMin": 5}]}
        result = TimelineService._parse_llm_json(json.dumps(payload))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["stage"], "小结")

    def test_invalid_json_raises(self) -> None:
        with self.assertRaises(ValueError):
            TimelineService._parse_llm_json("this is not json at all")

    def test_dict_without_nodes_raises(self) -> None:
        with self.assertRaises(ValueError):
            TimelineService._parse_llm_json(json.dumps({"foo": "bar"}))


class TimelineServiceExtractTextTest(unittest.TestCase):
    """Tests for TimelineService.extract_text formats."""

    def test_unsupported_format(self) -> None:
        svc = TimelineService(llm_client=None)  # type: ignore[arg-type]
        with self.assertRaises(ValueError) as ctx:
            svc.extract_text("lesson.xlsx", b"hello")
        self.assertIn("lesson.xlsx", str(ctx.exception))

    def test_legacy_doc_format_requires_docx(self) -> None:
        svc = TimelineService(llm_client=None)  # type: ignore[arg-type]
        with self.assertRaises(ValueError) as ctx:
            svc.extract_text("lesson.doc", b"hello")
        self.assertIn(".docx", str(ctx.exception))

    def test_docx_extracts_paragraphs_and_tables(self) -> None:
        svc = TimelineService(llm_client=None)  # type: ignore[arg-type]

        def fake_document(_stream):  # type: ignore[no-untyped-def]
            return SimpleNamespace(
                paragraphs=[
                    SimpleNamespace(text="导入活动"),
                    SimpleNamespace(text=""),
                    SimpleNamespace(text="新授内容"),
                ],
                tables=[
                    SimpleNamespace(
                        rows=[
                            SimpleNamespace(
                                cells=[
                                    SimpleNamespace(text="阶段"),
                                    SimpleNamespace(text="时长"),
                                ]
                            )
                        ]
                    )
                ],
            )

        with patch.dict(sys.modules, {"docx": SimpleNamespace(Document=fake_document)}):
            text = svc.extract_text("lesson.docx", b"fake-docx")

        self.assertIn("导入活动", text)
        self.assertIn("新授内容", text)
        self.assertIn("阶段\t时长", text)


class TimelineServiceGenerateValidationTest(unittest.TestCase):
    """Tests for generate_timeline validation (requires mocking LLM)."""

    def test_empty_nodes_raises(self) -> None:
        class FakeLLM:
            def chat_completion(self, messages, temperature=0.3):  # type: ignore[no-untyped-def]
                return json.dumps([])

        svc = TimelineService(llm_client=FakeLLM())  # type: ignore[arg-type]
        with self.assertRaises(ValueError) as ctx:
            svc.generate_timeline("lesson.txt", b"some text", "proj-1")
        self.assertIn("教学阶段", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
