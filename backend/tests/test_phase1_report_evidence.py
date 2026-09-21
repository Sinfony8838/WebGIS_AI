"""Phase-1 audit task T4: report evidence semantics and privacy boundaries.

Synthetic fixtures only — no real classroom records. Covers duration
semantics, anomaly flagging, valid-answer denominators, nickname caveats,
source labels, evidence_refs, and the aggregate-only LLM payload.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch

from backend.app.config import AppConfig
from backend.app.models import ClassSessionRecord, LessonRecord
from backend.app.services.reports import ReportService


def _make_session() -> ClassSessionRecord:
    session = ClassSessionRecord.create("lesson_x", "p1", "")
    return session


def _stage_event(stage_id: str, minutes: int = 5, offset_seconds: int = 0) -> Dict[str, Any]:
    return {
        "type": "stage_enter",
        "stage_id": stage_id,
        "timestamp": f"2026-09-10T10:00:{offset_seconds:02d}",
        "payload": {"stage_title": stage_id, "planned_minutes": minutes},
    }


def _choice_question_event(question_id: str, offset_seconds: int = 10) -> Dict[str, Any]:
    return {
        "type": "question_launched",
        "stage_id": "s1",
        "timestamp": f"2026-09-10T10:05:{offset_seconds:02d}",
        "payload": {"question_id": question_id, "text": "人口多密度一定高吗？", "options": ["是", "否"]},
    }


def test_duration_is_session_elapsed_and_effective_teaching_is_unknown(tmp_path: Path) -> None:
    session = _make_session()
    session.started_at = "2026-09-10T10:00:00"
    session.ended_at = "2026-09-10T10:40:00"
    service = ReportService(AppConfig(root_dir=tmp_path))
    stats = service.build_statistics(session, None)
    assert stats["duration_minutes"] == 40.0
    assert stats["duration_semantics"] == "session_elapsed"
    assert stats["effective_teaching_minutes"] is None
    assert "无法计算" in stats["effective_teaching_note"]
    markdown = service.render_markdown(stats, {"text": "", "generator": "rules"})
    assert "会话经过时长" in markdown and "有效教学时长：未计算" in markdown


def test_running_session_updated_fallback_counts_elapsed_and_flags_anomaly(tmp_path: Path) -> None:
    session = _make_session()
    session.started_at = "2026-09-01T08:00:00"
    session.ended_at = None
    session.updated_at = "2026-09-15T08:30:00"  # abandoned "running" session
    service = ReportService(AppConfig(root_dir=tmp_path))
    stats = service.build_statistics(session, None)
    assert stats["ended_at"] is None
    assert stats["duration_minutes"] is not None  # elapsed time, honestly labeled
    assert "session_still_running" in stats["anomalies"]
    markdown = service.render_markdown(stats, {"text": "", "generator": "rules"})
    assert "session_still_running" in markdown and "不改动原始记录" in markdown


def test_choice_correct_rate_uses_only_valid_answers(tmp_path: Path) -> None:
    session = _make_session()
    session.events = [_choice_question_event("q1")]
    session.responses["q1"] = [
        {"nickname": "甲", "choice_index": 1},
        {"nickname": "乙", "choice_index": 0},
        {"nickname": "丙", "choice_index": 1},
        {"nickname": "丁", "text": "我觉得是否"},          # text answer
        {"nickname": "戊", "choice_index": 9},             # out of range
        {"nickname": "己", "choice_index": None, "text": ""},  # empty submission
    ]
    lesson = LessonRecord.create(title="人口", stages=[{"stage_id": "s1", "questions": [
        {"question_id": "q1", "text": "人口多密度一定高吗？", "options": ["是", "否"], "answer_index": 1}
    ]}])
    service = ReportService(AppConfig(root_dir=tmp_path))
    stats = service.build_statistics(session, lesson)
    question = stats["questions"][0]
    assert question["response_count"] == 6
    assert question["valid_count"] == 3
    assert question["text_count"] == 1
    assert question["option_counts"] == [1, 2]
    assert question["correct_rate"] == round(2 / 3, 4)  # 2/3 of VALID answers, not 2/6
    assert stats["valid_choice_responses"] == 3
    assert stats["text_response_count"] == 1
    markdown = service.render_markdown(stats, {"text": "", "generator": "rules"})
    assert "3 份有效选择题作答" in markdown
    assert "分母为 3 份" in markdown


def test_zero_valid_answers_never_yield_a_correct_rate(tmp_path: Path) -> None:
    session = _make_session()
    session.events = [_choice_question_event("q1")]
    session.responses["q1"] = [
        {"nickname": "甲", "text": "开放回答一"},
        {"nickname": "乙", "text": "开放回答二"},
    ]
    service = ReportService(AppConfig(root_dir=tmp_path))
    stats = service.build_statistics(session, None)
    question = stats["questions"][0]
    assert question["response_count"] == 2
    assert question["valid_count"] == 0
    assert question["correct_rate"] is None
    markdown = service.render_markdown(stats, {"text": "", "generator": "rules"})
    assert "无有效选择题作答，正确率不可计算" in markdown
    assert "（0%）" not in markdown


def test_participant_count_carries_nickname_caveat_and_counts_split(tmp_path: Path) -> None:
    session = _make_session()
    session.events = [_stage_event("s1"), _choice_question_event("q1"),
                      {"type": "teacher_observation", "stage_id": "s1",
                       "timestamp": "2026-09-10T10:02:00",
                       "payload": {"verdict": "misconception", "tag": "总量当密度", "note": "张三认为甲区人口多所以密度大"}}]
    session.responses["q1"] = [
        {"nickname": "小明", "choice_index": 0},
        {"nickname": "小明", "choice_index": 1},  # same nickname, duplicate across questions
        {"nickname": "匿名", "choice_index": 0},
    ]
    service = ReportService(AppConfig(root_dir=tmp_path))
    stats = service.build_statistics(session, None)
    assert stats["participant_count"] == 1
    assert stats["participants"] == ["小明"]
    assert "不代表实名" in stats["participant_count_basis"]
    assert stats["observation_count"] == 1
    assert stats["valid_choice_responses"] == 3
    markdown = service.render_markdown(stats, {"text": "", "generator": "rules"})
    assert "不代表实名学生人数" in markdown
    assert "教师观察 1 条" in markdown


def test_data_source_defaults_to_unknown_for_legacy_records(tmp_path: Path) -> None:
    session = _make_session()
    service = ReportService(AppConfig(root_dir=tmp_path))
    stats = service.build_statistics(session, None)
    assert stats["data_source"] == "unknown"
    session.metadata["source"] = "test"
    assert service.build_statistics(session, None)["data_source"] == "test"
    markdown = service.render_markdown(stats, {"text": "", "generator": "rules"})
    assert "unknown" in markdown


def test_stage_progress_counts_entered_vs_planned(tmp_path: Path) -> None:
    session = _make_session()
    session.events = [_stage_event("s1")]
    lesson = LessonRecord.create(title="人口", stages=[{"stage_id": "s1"}, {"stage_id": "s2"}])
    service = ReportService(AppConfig(root_dir=tmp_path))
    stats = service.build_statistics(session, lesson)
    assert stats["planned_stage_count"] == 2
    markdown = service.render_markdown(stats, {"text": "", "generator": "rules"})
    assert "已进入 1/2 个教案环节" in markdown and "进入不等于完成学习" in markdown


def test_llm_payload_is_aggregate_only(tmp_path: Path) -> None:
    captured: Dict[str, Any] = {}

    class FakeClient:
        def chat_completion(self, messages: List[Dict[str, Any]], temperature: float = 0.2, **_: Any) -> str:
            captured["messages"] = messages
            return "### 学情诊断\n基于汇总数据的复盘。"

    session = _make_session()
    session.events = [_choice_question_event("q1")]
    session.responses["q1"] = [
        {"nickname": "王小明1392", "choice_index": 0},
        {"nickname": "李小红", "text": "我家附近就是流动人口聚居区"},
    ]
    session.events.append({"type": "teacher_observation", "stage_id": "s1",
                           "timestamp": "2026-09-10T10:02:00",
                           "payload": {"verdict": "misconception", "tag": "总量当密度", "note": "王小明把总量当密度"}})
    service = ReportService(AppConfig(root_dir=tmp_path), minimax_client=FakeClient())
    stats = service.build_statistics(session, None)
    result = service.compose_diagnosis(stats)
    assert result["generator"] == "minimax"
    user_content = captured["messages"][1]["content"]
    # Free text, nicknames and observation notes never reach the model.
    assert "王小明" not in user_content and "李小红" not in user_content
    assert "流动人口聚居区" not in user_content
    assert "把总量当密度" not in user_content
    payload = json.loads(user_content)
    for question in payload["questions"]:
        assert "sample_texts" not in question and "text" not in question
    assert "notes" not in payload["observations"] and "records" not in payload["observations"]
    assert "participants" not in payload
    # Aggregates the model MAY see — minimization must not gut informativeness:
    # type, collection mode, sample counts, option distributions and rates stay.
    question = payload["questions"][0]
    assert question["response_count"] == 2 and question["text_count"] == 1
    assert question["option_counts"] == [1, 0]
    assert question["collection_mode"] == "student_response"
    assert payload["participant_count"] == 2
    assert payload["observations"]["misconception_tags"] == [["总量当密度", 1]]
    assert payload["observations"]["verdict_counts"]["misconception"] == 1


def test_recommendations_carry_evidence_refs_or_design_suggestion(tmp_path: Path) -> None:
    lesson = LessonRecord.create(title="人口", stages=[
        {"stage_id": "s", "questions": [{"question_id": "q", "text": "题", "options": ["A", "B"], "answer_index": 1}]}
    ])
    service = ReportService(AppConfig(root_dir=tmp_path))
    stats = {"response_data_collected": True, "questions": [
        {"question_id": "q", "text": "题", "response_count": 2, "valid_count": 2, "correct_rate": 0.5,
         "options": ["A", "B"], "answer_index": 1}]}
    result = service.build_practice_recommendations(stats, lesson)
    review = [item for item in result if item["practice_id"] == "class_question_q"][0]
    assert "statistics.questions.q.correct_rate" in review["evidence_refs"]
    # Every emitted ref resolves to evidence that exists in this session.
    for item in result:
        for ref in item["evidence_refs"]:
            assert service.evidence_ref_exists(ref, stats, lesson), ref
    # No evidence at all → explicit design suggestion, not an invented claim.
    empty = service.build_practice_recommendations({"lesson_title": "人口", "response_data_collected": False}, None)
    assert empty[0]["evidence_refs"] == ["设计建议（证据不足）"]
    assert service.evidence_ref_exists(empty[0]["evidence_refs"][0], {"questions": []}, None)
    assert "设计建议（证据不足）" in empty[0]["evidence_basis"]
    markdown = service.render_markdown(stats, {"text": "", "generator": "rules"}, result)
    assert "证据引用" in markdown


def test_relaunched_same_question_merges_into_one_entry(tmp_path: Path) -> None:
    """同一道题重复发起：统计合并为单题条目，口径保持一致。"""
    session = _make_session()
    session.events = [
        _choice_question_event("q1", offset_seconds=10),
        _choice_question_event("q1", offset_seconds=20),  # relaunch
    ]
    session.responses["q1"] = [
        {"nickname": "甲", "choice_index": 1},
        {"nickname": "乙", "choice_index": 1},
    ]
    service = ReportService(AppConfig(root_dir=tmp_path))
    stats = service.build_statistics(session, None)
    assert len(stats["questions"]) == 1
    question = stats["questions"][0]
    assert question["response_count"] == 2
    assert question["valid_count"] == 2


def test_real_label_is_not_treated_as_classroom_acceptance_proof(tmp_path: Path) -> None:
    session = _make_session()
    session.metadata["source"] = "real"
    service = ReportService(AppConfig(root_dir=tmp_path))
    stats = service.build_statistics(session, None)
    assert stats["data_source"] == "real"
    markdown = service.render_markdown(stats, {"text": "", "generator": "rules"})
    assert "real" in markdown
    assert "不等于已完成真实课堂验收" in markdown
    # Non-real sources do not carry the acceptance disclaimer.
    plain = service.render_markdown({"data_source": "unknown"}, {"text": "", "generator": "rules"})
    assert "不等于已完成真实课堂验收" not in plain


def test_no_answer_data_still_never_calls_the_model(tmp_path: Path) -> None:
    class ExplodingClient:
        def chat_completion(self, *_: Any, **__: Any) -> str:
            raise AssertionError("model must not be called without answer data")

    session = _make_session()
    service = ReportService(AppConfig(root_dir=tmp_path), minimax_client=ExplodingClient())
    stats = service.build_statistics(session, None)
    result = service.compose_diagnosis(stats)
    assert result["generator"] == "rules"
