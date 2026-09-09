"""After-class diagnostic report built from class-session events.

The statistics section is fully rule-based so a report can always be
generated offline; the diagnosis section prefers a MiniMax completion
and falls back to data-driven rule text when the LLM is unavailable.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..config import AppConfig
from ..models import ClassSessionRecord, LessonRecord
from .minimax_client import MiniMaxClient
from .lesson_homework import homework_guidance


VERDICT_LABELS = {"correct": "回答正确", "partial": "部分正确", "misconception": "存在误区"}


def _parse_ts(value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


class ReportService:
    def __init__(self, config: AppConfig, minimax_client: Optional[MiniMaxClient] = None):
        self.config = config
        self.minimax_client = minimax_client

    # ------------------------------------------------------------------
    # Statistics (rule-based, always available)
    # ------------------------------------------------------------------

    def build_statistics(self, session: ClassSessionRecord, lesson: Optional[LessonRecord]) -> Dict[str, Any]:
        events = list(session.events)
        stage_lookup: Dict[str, Dict[str, Any]] = {}
        question_lookup: Dict[str, Dict[str, Any]] = {}
        if lesson is not None:
            for stage in lesson.stages:
                stage_lookup[str(stage.get("stage_id"))] = stage
                for question in stage.get("questions", []):
                    question_lookup[str(question.get("question_id"))] = {**question, "stage_id": stage.get("stage_id")}

        stages = self._stage_durations(events, session, stage_lookup)
        questions = self._question_stats(events, session, question_lookup)
        observations = self._observation_stats(events)
        participants = self._participants(session)
        response_data_collected = any(bool(items) for items in session.responses.values())
        snapshots = [
            {"timestamp": event.get("timestamp", ""), **(event.get("payload") or {})}
            for event in events
            if event.get("type") == "snapshot"
        ]
        assistant_exchanges = [
            {"timestamp": event.get("timestamp", ""), **(event.get("payload") or {})}
            for event in events
            if event.get("type") == "assistant_exchange"
        ]

        started = _parse_ts(session.started_at)
        ended = _parse_ts(session.ended_at) or _parse_ts(session.updated_at)
        duration_minutes = None
        if started and ended and ended > started:
            duration_minutes = round((ended - started).total_seconds() / 60.0, 1)

        return {
            "session_id": session.session_id,
            "lesson_id": session.lesson_id,
            "lesson_title": lesson.title if lesson else session.metadata.get("lesson_title", ""),
            "lesson_snapshot_available": isinstance(session.metadata.get("lesson_snapshot"), dict),
            "started_at": session.started_at,
            "ended_at": session.ended_at,
            "duration_minutes": duration_minutes,
            "participant_count": len(participants),
            "participants": sorted(participants),
            "response_data_collected": response_data_collected,
            "stages": stages,
            "questions": questions,
            "observations": observations,
            "snapshot_count": len(snapshots),
            "snapshots": snapshots,
            "assistant_exchange_count": len(assistant_exchanges),
            "assistant_exchanges": assistant_exchanges[:10],
            "event_count": len(events),
        }

    def _stage_durations(
        self,
        events: List[Dict[str, Any]],
        session: ClassSessionRecord,
        stage_lookup: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        enters = [event for event in events if event.get("type") == "stage_enter"]
        results: List[Dict[str, Any]] = []
        for index, event in enumerate(enters):
            start = _parse_ts(event.get("timestamp", ""))
            if index + 1 < len(enters):
                end = _parse_ts(enters[index + 1].get("timestamp", ""))
            else:
                end = _parse_ts(session.ended_at) or _parse_ts(session.updated_at)
            actual_minutes = None
            if start and end and end > start:
                actual_minutes = round((end - start).total_seconds() / 60.0, 1)
            stage_id = str(event.get("stage_id") or "")
            stage = stage_lookup.get(stage_id, {})
            payload = event.get("payload") or {}
            results.append(
                {
                    "stage_id": stage_id,
                    "title": payload.get("stage_title") or stage.get("title", stage_id),
                    "planned_minutes": payload.get("planned_minutes") or stage.get("minutes"),
                    "actual_minutes": actual_minutes,
                    "entered_at": event.get("timestamp", ""),
                }
            )
        return results

    def _question_stats(
        self,
        events: List[Dict[str, Any]],
        session: ClassSessionRecord,
        question_lookup: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        launched: Dict[str, Dict[str, Any]] = {}
        for event in events:
            event_type = str(event.get("type") or "")
            if event_type not in {"question_launched", "teacher_question_presented"}:
                continue
            payload = event.get("payload") or {}
            question_id = str(payload.get("question_id") or "")
            if question_id:
                launched[question_id] = {
                    **payload,
                    "stage_id": event.get("stage_id", ""),
                    "collection_mode": "teacher_observation"
                    if event_type == "teacher_question_presented"
                    else "student_response",
                }

        results: List[Dict[str, Any]] = []
        for question_id, info in launched.items():
            defined = question_lookup.get(question_id, {})
            options = info.get("options") or defined.get("options") or []
            answer_index = defined.get("answer_index")
            responses = list(session.responses.get(question_id, []))
            counts = [0] * len(options)
            texts: List[str] = []
            for item in responses:
                choice = item.get("choice_index")
                if isinstance(choice, int) and 0 <= choice < len(counts):
                    counts[choice] += 1
                elif str(item.get("text") or "").strip():
                    texts.append(str(item.get("text")))
            total = len(responses)
            correct_rate = None
            if isinstance(answer_index, int) and 0 <= answer_index < len(counts) and total:
                correct_rate = round(counts[answer_index] / total, 4)
            results.append(
                {
                    "question_id": question_id,
                    "stage_id": info.get("stage_id", ""),
                    "text": info.get("text") or defined.get("text", ""),
                    "type": info.get("type") or defined.get("type", "open"),
                    "collection_mode": info.get("collection_mode", "student_response"),
                    "options": options,
                    "answer_index": answer_index if isinstance(answer_index, int) else None,
                    "response_count": total,
                    "option_counts": counts,
                    "correct_rate": correct_rate,
                    "sample_texts": texts[:10],
                    "misconceptions": defined.get("misconceptions", []),
                }
            )
        return results

    def _observation_stats(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        observations = [event for event in events if event.get("type") == "teacher_observation"]
        verdict_counts = {"correct": 0, "partial": 0, "misconception": 0}
        tag_counts: Dict[str, int] = {}
        notes: List[Dict[str, Any]] = []
        records: List[Dict[str, Any]] = []
        for event in observations:
            payload = event.get("payload") or {}
            verdict = str(payload.get("verdict") or "")
            if verdict in verdict_counts:
                verdict_counts[verdict] += 1
            tag = str(payload.get("tag") or "").strip()
            if tag and verdict == "misconception":
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
            records.append({"question_id": str(payload.get("question_id") or ""),
                            "stage_id": event.get("stage_id", ""), "verdict": verdict,
                            "tag": tag, "note": str(payload.get("note") or "")})
            if str(payload.get("note") or "").strip():
                notes.append(
                    {
                        "timestamp": event.get("timestamp", ""),
                        "stage_id": event.get("stage_id", ""),
                        "verdict": verdict,
                        "tag": tag,
                        "note": payload.get("note", ""),
                    }
                )
        return {
            "total": len(observations),
            "verdict_counts": verdict_counts,
            "misconception_tags": sorted(tag_counts.items(), key=lambda item: -item[1]),
            "notes": notes,
            "records": records,
        }

    def _participants(self, session: ClassSessionRecord) -> set[str]:
        participants: set[str] = set()
        for responses in session.responses.values():
            for item in responses:
                nickname = str(item.get("nickname") or "").strip()
                if nickname and nickname not in {"匿名", "anonymous"}:
                    participants.add(nickname)
        return participants

    # ------------------------------------------------------------------
    # Diagnosis (LLM preferred, rule fallback)
    # ------------------------------------------------------------------

    def compose_diagnosis(self, statistics: Dict[str, Any]) -> Dict[str, Any]:
        # Teacher-only sessions intentionally do not contain student answers.
        # A model completion cannot add evidence here, but it can accidentally
        # turn lesson content into invented claims about student performance.
        if not statistics.get("response_data_collected"):
            return {"text": self._diagnose_with_rules(statistics), "generator": "rules"}
        if self.minimax_client is not None:
            try:
                text = self._diagnose_with_llm(statistics)
                if text.strip():
                    return {"text": text.strip(), "generator": "minimax"}
            except Exception:
                pass
        return {"text": self._diagnose_with_rules(statistics), "generator": "rules"}

    def build_practice_recommendations(
        self, statistics: Dict[str, Any], lesson: Optional[LessonRecord]
    ) -> List[Dict[str, Any]]:
        """Use the opening lesson snapshot; observations can prioritize, not invent tasks."""
        questions = [q for q in statistics.get("questions") or [] if isinstance(q, dict)]
        observations = statistics.get("observations") or {}
        verdicts = observations.get("verdict_counts") or {}
        collected = bool(statistics.get("response_data_collected"))
        evidence = "课堂作答已采集；请结合各题样本量复核，不据少量记录推断全班表现。" if collected else "课堂作答未采集；没有足够证据判定全班共性误区。"
        if verdicts.get("partial"):
            evidence += f"教师记录部分正确 {verdicts['partial']} 次。"
        if verdicts.get("misconception"):
            evidence += f"教师记录误区表现 {verdicts['misconception']} 次，仅代表所记录的观察。"

        stage_ids = {str(stage.get("stage_id")) for stage in (lesson.stages if lesson else [])}
        entered_ids = {str(stage.get("stage_id")) for stage in statistics.get("stages") or []}
        progress = (f"本次记录进入 {len(stage_ids & entered_ids)}/{len(stage_ids)} 个教案环节；进入记录不代表完成学习，布置前请核对教学进度。"
                    if stage_ids else "缺少完整教案环节记录，布置前请核对教学进度。")
        lesson_source = ("来自开课时保存的教案。" if statistics.get("lesson_snapshot_available")
                         else "来自关联教案；本会话缺少开课快照，内容可能包含课后修改。")
        plan = lesson.plan if lesson and isinstance(lesson.plan, dict) else {}
        homework = plan.get("homework") if isinstance(plan.get("homework"), dict) else {}
        result: List[Dict[str, Any]] = []
        for key, label in (("basic", "基础作业"), ("inquiry", "探究作业")):
            for index, text in enumerate(homework.get(key) or [], start=1):
                if not isinstance(text, str) or not text.strip():
                    continue
                guide = homework_guidance(homework, text)
                result.append({
                    "practice_id": f"lesson_homework_{key}_{index}", "level": label,
                    "title": guide.get("title") or f"教案预设作业 · {label}{index}", "suggested_minutes": guide.get("suggested_minutes"),
                    "prompt": text.strip(), "answer_points": guide.get("answer_points", []),
                    "evidence_basis": lesson_source + "这是教案预设任务。" + progress + evidence,
                })

        defined = {
            str(q.get("question_id")): q
            for stage in (lesson.stages if lesson else [])
            for q in stage.get("questions") or [] if isinstance(q, dict)
        }
        by_id = {str(q.get("question_id")): q for q in questions}
        priorities: Dict[str, str] = {}
        rated = [q for q in questions if collected and q.get("response_count", 0) > 0
                 and isinstance(q.get("correct_rate"), (int, float)) and q["correct_rate"] < 0.6]
        for q in sorted(rated, key=lambda item: item["correct_rate"]):
            priorities[str(q["question_id"])] = (
                f"本题已采集 {q['response_count']} 份作答，正确率 {q['correct_rate']:.0%}；建议回看原题并分析解题过程。")
        for note in observations.get("records") or []:
            qid = str(note.get("question_id") or "")
            if note.get("verdict") in {"partial", "misconception"} and qid in by_id:
                detail = str(note.get("tag") or note.get("note") or VERDICT_LABELS[note["verdict"]])
                priorities.setdefault(qid, f"教师对本题记录“{detail}”；仅针对这条观察安排回看，不代表全班诊断。")

        # Without preset homework, reuse presented questions, not a title-matched pack.
        candidates = list(priorities) if result else list(dict.fromkeys([*priorities, *by_id]))
        for qid in candidates[:2]:
            q = {**defined.get(qid, {}), **by_id[qid]}
            original = defined.get(qid, {})
            answer = str(original.get("answer") or "").strip()
            options, answer_index = q.get("options") or [], q.get("answer_index")
            if not answer and isinstance(answer_index, int) and 0 <= answer_index < len(options):
                answer = f"{chr(65 + answer_index)}. {options[answer_index]}"
            points = [value for value in (answer, str(original.get("explanation") or "").strip()) if value]
            result.append({
                "practice_id": f"class_question_{qid}", "level": "课堂回看",
                "title": "回看课堂原题", "suggested_minutes": None,
                "prompt": f"结合课堂原题的图表和材料，再回答：{q.get('text', '')}",
                "answer_points": points,
                "evidence_basis": priorities.get(qid, "本次课堂已呈现此题；作为复习安排，不代表学生答错。") + evidence,
            })
        if not result:
            objectives = [str(v).strip() for v in (lesson.objectives if lesson else []) if str(v).strip()]
            result.append({
                "practice_id": "lesson_review", "level": "教师待确认", "title": "确定课后复习任务",
                "suggested_minutes": None,
                "prompt": ("围绕本课目标“" + "；".join(objectives) + "”，选取课堂材料安排复习。"
                           if objectives else "尚无预设作业或已呈现的课堂题目，请先补充教学目标与材料再选题。"),
                "answer_points": [], "evidence_basis": progress + evidence,
            })
        return result

    def _diagnose_with_llm(self, statistics: Dict[str, Any]) -> str:
        if self.minimax_client is None:
            raise RuntimeError("LLM client unavailable")
        compact = {
            key: statistics.get(key)
            for key in (
                "lesson_title",
                "duration_minutes",
                "participant_count",
                "response_data_collected",
                "stages",
                "questions",
                "observations",
                "snapshot_count",
                "assistant_exchange_count",
            )
        }
        system = (
            "你是一名地理教研员，请基于课堂数据 JSON 写一份课后教学证据复盘。"
            "输出 Markdown（不要代码块包裹），分三个小节：\n"
            "### 学情诊断\n### 共性误区分析\n### 下节课教学建议\n"
            "要求：紧扣真实数据说话。只有 response_data_collected=true 时才能引用作答人数和正确率；"
            "否则必须明确写“课堂作答数据未采集”，只引用教师观察、误区标签、环节用时、截图和课堂事件，"
            "语言面向授课教师本人，每节 2-4 句，总长不超过 350 字，不要空话套话。"
        )
        return self.minimax_client.chat_completion(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(compact, ensure_ascii=False)},
            ],
            temperature=0.3,
        )

    def _diagnose_with_rules(self, statistics: Dict[str, Any]) -> str:
        lines: List[str] = ["### 学情诊断"]
        questions = statistics.get("questions") or []
        rated = [item for item in questions if item.get("correct_rate") is not None]
        if rated and statistics.get("response_data_collected"):
            average = sum(item["correct_rate"] for item in rated) / len(rated)
            lines.append(
                f"本节课发起 {len(questions)} 次提问，选择题平均正确率 {average:.0%}，"
                f"参与作答 {statistics.get('participant_count', 0)} 人。"
            )
            weakest = min(rated, key=lambda item: item["correct_rate"])
            if weakest["correct_rate"] < 0.6:
                lines.append(f"「{weakest['text']}」正确率仅 {weakest['correct_rate']:.0%}，需要针对性巩固。")
        elif statistics.get("response_data_collected"):
            lines.append("本节课已采集作答，但缺少可计算正确率的选择题数据；开放题需结合原文逐项评阅，不能据此判定掌握程度。")
        else:
            lines.append("本节课未采集课堂作答数据，诊断仅依据教师观察、环节用时和课堂证据。")

        observations = statistics.get("observations") or {}
        verdicts = observations.get("verdict_counts") or {}
        lines.append("")
        lines.append("### 共性误区分析")
        tags = observations.get("misconception_tags") or []
        if tags:
            tag_text = "、".join(f"“{tag}”（{count} 次）" for tag, count in tags[:3])
            lines.append(f"教师记录中出现频率最高的误区标签为：{tag_text}。")
        elif verdicts.get("misconception"):
            lines.append(f"教师共记录 {verdicts['misconception']} 次误区表现，建议课后回看具体备注。")
        else:
            lines.append("本次记录没有明确的共性误区证据；未记录不等于学生不存在误区。")

        lines.append("")
        lines.append("### 下节课教学建议")
        overtime = [
            item
            for item in statistics.get("stages") or []
            if item.get("actual_minutes") and item.get("planned_minutes")
            and float(item["actual_minutes"]) > float(item["planned_minutes"]) * 1.3
        ]
        if overtime:
            names = "、".join(str(item.get("title") or item.get("stage_id")) for item in overtime[:2])
            lines.append(
                f"系统计时显示环节“{names}”明显超时；请先核对是否存在暂停或演示等待，"
                "确认属于真实课堂节奏后，再压缩讲解或将部分任务前置为课前预习。"
            )
        if tags:
            lines.append(f"建议围绕“{tags[0][0]}”设计一道对比辨析题，在下节课导入环节即时检测。")
        if not overtime and not tags:
            lines.append("现有记录不足以判断学生掌握情况。建议下节课先用一道读图或概念辨析题收集作答，再据证据调整教学安排。")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Markdown rendering
    # ------------------------------------------------------------------

    def render_markdown(
        self,
        statistics: Dict[str, Any],
        diagnosis: Dict[str, Any],
        practice_recommendations: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        lines: List[str] = [
            f"# 课堂报告：{statistics.get('lesson_title', '')}",
            "",
            f"- 上课时间：{statistics.get('started_at', '')} ~ {statistics.get('ended_at', '') or '进行中'}",
            f"- 实际时长：{statistics.get('duration_minutes', '—')} 分钟",
            f"- 课堂作答数据：{'已采集' if statistics.get('response_data_collected') else '未采集'}",
            f"- 课堂事件：{statistics.get('event_count', 0)} 条"
            f"（截图 {statistics.get('snapshot_count', 0)} 张，助教问答 {statistics.get('assistant_exchange_count', 0)} 次）",
            "",
            "## 教学环节时间线",
            "",
            "| 环节 | 计划(分) | 实际(分) |",
            "| --- | --- | --- |",
        ]
        for stage in statistics.get("stages") or []:
            lines.append(
                f"| {stage.get('title', stage.get('stage_id', ''))} "
                f"| {stage.get('planned_minutes', '—')} | {stage.get('actual_minutes', '—')} |"
            )
        if not statistics.get("stages"):
            lines.append("| （本次会话未记录环节切换） | — | — |")

        lines.extend(["", "## 教师提问与课堂证据", ""])
        questions = statistics.get("questions") or []
        if not questions:
            lines.append("本节课未记录教师提问。")
        for index, question in enumerate(questions, start=1):
            teacher_oral = question.get("collection_mode") == "teacher_observation"
            collection_label = "教师口头呈现，表现由教师观察记录" if teacher_oral else (f"{question.get('response_count', 0)} 人作答" if question.get("response_count", 0) > 0 else "本题未采集作答数据")
            lines.append(f"**Q{index}. {question.get('text', '')}**（{collection_label}）")
            options = question.get("options") or []
            counts = question.get("option_counts") or []
            total = max(question.get("response_count", 0), 1)
            if not teacher_oral and question.get("response_count", 0) > 0:
                for option_index, option in enumerate(options):
                    count = counts[option_index] if option_index < len(counts) else 0
                    marker = " ✅" if question.get("answer_index") == option_index else ""
                    lines.append(f"- {chr(65 + option_index)}. {option}：{count} 人（{count / total:.0%}）{marker}")
            elif options:
                lines.append("- 备选项：" + "；".join(f"{chr(65 + option_index)}. {option}" for option_index, option in enumerate(options)))
            if question.get("correct_rate") is not None and not teacher_oral:
                lines.append(f"- 正确率：**{question['correct_rate']:.0%}**")
            for text in question.get("sample_texts") or []:
                lines.append(f"- 「{text}」")
            lines.append("")

        observations = statistics.get("observations") or {}
        lines.extend(["## 教师课堂观察", ""])
        verdicts = observations.get("verdict_counts") or {}
        lines.append(
            f"- 记录 {observations.get('total', 0)} 条："
            + "，".join(f"{VERDICT_LABELS[key]} {verdicts.get(key, 0)} 次" for key in VERDICT_LABELS)
        )
        for tag, count in observations.get("misconception_tags") or []:
            lines.append(f"- 误区标签「{tag}」：{count} 次")
        for note in observations.get("notes") or []:
            lines.append(f"- [{VERDICT_LABELS.get(note.get('verdict', ''), '记录')}] {note.get('note', '')}")

        lines.extend(["", "## 学情诊断与建议", "", diagnosis.get("text", ""), ""])
        generator = "AI 生成（MiniMax）" if diagnosis.get("generator") == "minimax" else "规则生成（证据保护）"
        lines.append(f"> 诊断内容来源：{generator}")
        lines.extend(["", "## 课后推荐练习巩固", "", "以下任务在课堂结束后使用，不计入课堂教学用时；预设作业需由教师结合实际进度确认。", ""])
        for index, item in enumerate(practice_recommendations or [], start=1):
            timing = f"（建议 {item['suggested_minutes']} 分钟）" if item.get("suggested_minutes") else ""
            lines.extend(
                [
                    f"### {index}. [{item.get('level', '')}] {item.get('title', '')}{timing}",
                    "",
                    str(item.get("prompt") or ""),
                    "",
                    "- 参考要点：" + "；".join(str(point) for point in item["answer_points"]) if item.get("answer_points") else "- 开放任务或未附参考答案，请结合原题材料评阅。",
                    "- 推荐依据：" + str(item.get("evidence_basis") or ""),
                    "",
                ]
            )
        return "\n".join(lines)
