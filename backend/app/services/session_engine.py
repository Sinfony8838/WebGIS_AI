from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from ..config import AppConfig
from ..models import ConversationRecord, ProjectRecord
from ..store import RuntimeStore
from .assistant import ASSISTANT_TOOL_SCHEMA, AssistantService
from .knowledge_base import KnowledgeBaseService
from .llm_planner import LLMPlanner
from .workflow_templates import INTERACTION_ALLOWED_TEMPLATES


GEOGRAPHY_ALLOWLIST = (
    "nasa.gov",
    "noaa.gov",
    "usgs.gov",
    "wmo.int",
    "fao.org",
    "worldbank.org",
    "un.org",
    "stats.gov.cn",
    "igsnrr.ac.cn",
)

TOOL_ACTION_HINTS = (
    "切换",
    "打开",
    "关闭",
    "显示",
    "隐藏",
    "导出",
    "飞到",
    "缩放",
    "加载",
    "叠加",
    "标注",
    "测量",
    "搜索",
    "制作",
    "生成",
    "创建",
    "绘制",
    "建立",
    "添加",
    "删除",
    "移除",
    "裁剪",
    "合并",
    "计算",
    "统计",
    "渲染",
    "发布",
    "发给",
    "发起",
    "呈现",
    "推送",
    "记一下",
    "apply",
    "switch",
    "hide",
    "show",
    "export",
    "zoom",
    "load",
    "create",
    "generate",
    "render",
    "draw",
    "add",
    "remove",
    "delete",
    "clip",
    "merge",
    "calculate",
)

EXPLANATION_HINTS = ("解释", "讲解", "分析", "为什么", "说明", "读图", "原因", "explain", "analysis", "why")
CURRENT_MAP_HINTS = ("当前视图", "当前地图", "当前画面", "当前图层", "当前区域", "当前选区", "图中", "图上", "视图", "画面")
MAP_READING_HINTS = ("读图", "判读", "图上", "图中", "视图", "地图", "图例", "等高线", "地貌", "地形", "地势", "空间格局", "分布特征")
TIME_SENSITIVE_HINTS = ("最新", "目前", "今天", "近年", "recent", "latest", "today")
LOCAL_RETRIEVAL_HINTS = (
    "知识库",
    "教材",
    "课程资料",
    "课堂资料",
    "项目资料",
    "本地资料",
    "课本",
)
WEB_RETRIEVAL_HINTS = (
    "最新",
    "今年",
    "当前数据",
    "实时",
    "核实",
    "查证",
    "来源",
    "在线搜索",
    "联网",
    "recent",
    "latest",
    "verify",
    "source",
)
IMAGE_WEB_RETRIEVAL_HINTS = (
    "联网",
    "在线搜索",
    "联网核实",
    "核实最新",
    "查证最新",
    "查询最新",
    "查找最新",
    "结合最新",
    "补充最新",
    "最新资料",
    "今年数据",
    "search online",
    "verify latest",
)
IMAGE_FOLLOW_UP_HINTS = ("这张图", "这幅图", "刚才的图", "刚才的图片", "上一张图", "图里", "图中")
MATCH_STOP_WORDS = {
    "什么",
    "怎么",
    "为什么",
    "当前",
    "这个",
    "那个",
    "请问",
    "分析",
    "解释",
    "说明",
    "地图",
    "图片",
    "the",
    "what",
    "why",
    "how",
}

TEACHING_TASKS = ("teaching_explain", "teaching_question", "teaching_action", "teaching_reflect", "teaching_prepare")
TEACHING_PREPARE_HINTS = ("共创教案", "教案共创", "备一节课", "生成整节教案", "逐步设计教案", "教案助手", "完整教案")
TEACHING_QUESTION_HINTS = ("追问", "提问", "设计问题", "出几道题", "几个问题", "还有什么问题", "进一步问", "follow-up")
TEACHING_REFLECT_HINTS = ("复盘", "课堂小结", "小结一下", "回顾一下", "总结本课", "总结这节课", "课后总结", "复习切口")


def _contains_any(text: str, tokens: Sequence[str]) -> bool:
    lowered = (text or "").lower()
    return any(token.lower() in lowered for token in tokens)


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()[:16]


def _parse_timestamp(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _utc_timestamp(minutes_from_now: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes_from_now)).isoformat()


def _teaching_scaffold_parts(knowledge: Dict[str, Any], map_context: Dict[str, Any]) -> Dict[str, str]:
    """Return one concise, student-facing summary for a teaching answer.

    Raw viewport metadata and teacher-only scaffolding are deliberately kept
    out of the projected classroom response.
    """
    knowledge = knowledge or {}
    direct_answer = str(knowledge.get("direct_answer") or "").strip()
    explicit_summary = ""
    if "回答总结：" in direct_answer:
        explicit_summary = direct_answer.rsplit("回答总结：", 1)[-1].strip().splitlines()[0].strip()
    candidates = [
        explicit_summary,
        direct_answer,
        *[str(item).strip() for item in list(knowledge.get("teaching_points") or []) if str(item).strip()],
    ]
    summary = next((item for item in candidates if item), "本次回答需要结合本节人口地理主题作进一步概括。")
    summary = " ".join(summary.split())
    for marker in ("。", "！", "？", ";", "；"):
        if marker in summary:
            summary = summary.split(marker, 1)[0].strip() + ("。" if marker in {"。", ";", "；"} else marker)
            break
    if len(summary) > 90:
        summary = summary[:88].rstrip("，、；;：:") + "。"
    return {"summary": summary}


def _format_scaffold_text(parts: Optional[Dict[str, str]]) -> str:
    """Render the structured teaching contract as the legacy text block.

    Kept for ``assistant_message`` (consumed by voice/history/tests) so the
    textual contract stays byte-identical; the frontend renders the structured
    ``teaching_contract`` field instead of parsing this text.
    """
    parts = parts or {}
    return f"回答总结：{parts.get('summary', '')}"


def _teaching_scaffold(knowledge: Dict[str, Any], map_context: Dict[str, Any]) -> str:
    """Backward-compatible text scaffold; see ``_teaching_scaffold_parts``."""
    return _format_scaffold_text(_teaching_scaffold_parts(knowledge, map_context))

META_ANSWER_TYPES = {"assistant_identity", "assistant_model", "assistant_capability"}


@dataclass
class ToolPermissionContext:
    allow_rules: List[str] = field(default_factory=lambda: ["low", "medium"])
    deny_rules: List[str] = field(default_factory=lambda: ["blocked"])
    ask_rules: List[str] = field(default_factory=lambda: ["high"])
    current_policy: str = "risk_based"
    denials: List[Dict[str, str]] = field(default_factory=list)
    rejected_tools: List[str] = field(default_factory=list)
    orphaned_confirmation: str = ""
    cooldown_rules: List[str] = field(default_factory=list)

    @classmethod
    def from_pinned_state(cls, pinned_state: Optional[Dict[str, Any]]) -> "ToolPermissionContext":
        pinned_state = pinned_state or {}
        return cls(
            denials=list(pinned_state.get("denials") or []),
            rejected_tools=list(pinned_state.get("rejected_tools") or []),
            orphaned_confirmation=str(pinned_state.get("orphaned_confirmation") or ""),
            cooldown_rules=list(pinned_state.get("cooldown_rules") or []),
        )

    def decision_for(self, risk_level: str, tool_name: str = "") -> str:
        # A rejected confirmation applies only to its frozen plan. Keep
        # rejected_tools as audit history, but allow a later explicit request
        # to create a fresh confirmation instead of permanently banning the
        # tool for the conversation.
        if risk_level in self.deny_rules:
            return "deny"
        if risk_level in self.ask_rules:
            return "ask"
        return "allow"

    def remember_denial(self, tool_name: str, reason: str) -> None:
        if tool_name and tool_name not in self.rejected_tools:
            self.rejected_tools.append(tool_name)
        if tool_name:
            self.denials.append({"tool_name": tool_name, "reason": reason})
            self.denials = self.denials[-8:]

    def mark_orphaned(self, confirmation_id: str) -> None:
        self.orphaned_confirmation = confirmation_id

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allow_rules": list(self.allow_rules),
            "deny_rules": list(self.deny_rules),
            "ask_rules": list(self.ask_rules),
            "current_policy": self.current_policy,
            "denials": list(self.denials),
            "rejected_tools": list(self.rejected_tools),
            "orphaned_confirmation": self.orphaned_confirmation,
            "cooldown_rules": list(self.cooldown_rules),
        }


class PromptRegistry:
    version = "super_geo_assistant_v2.1"

    def build(
        self,
        mode: str,
        map_context: Dict[str, Any],
        retrieval: Optional[List[Dict[str, Any]]] = None,
        conversation_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        conversation_context = conversation_context or {}
        retrieval_items = [
            {"title": item.get("title", ""), "url": item.get("url", "")}
            for item in (retrieval or [])[:5]
        ]
        map_summary = {
            "center": map_context.get("center"),
            "zoom": map_context.get("zoom"),
            "visible_layers": map_context.get("visible_layers", []),
            "selected_feature_summary": map_context.get("selected_feature_summary", ""),
        }
        memory_summary = {
            "running_summary": conversation_context.get("running_summary", ""),
            "task_memory": conversation_context.get("task_memory", {}),
            "pinned_state": conversation_context.get("pinned_state", {}),
            "last_map_grounding": conversation_context.get("last_map_grounding", {}),
        }
        parts = {
            "super_geo_base": "You are Super Geo Assistant. Stay inside geography and GIS scope.",
            "knowledge_mode": "Answer geography questions using AI general knowledge first, supplemented by local KB and online search. "
            "Provide authoritative citations and concise teaching points suitable for classroom use."
            if mode == "knowledge"
            else "",
            "tool_mode": "Plan and execute only safe, validated GIS actions."
            if mode == "tool"
            else "",
            "hybrid_mode": "Execute approved GIS actions first, then explain the spatial meaning."
            if mode == "hybrid"
            else "",
            "teaching_mode": "Act as a professional geography teaching agent: explain first, operate maps only through validated tools, always close with classroom guidance."
            if mode.startswith("teaching")
            else "",
            "interaction_mode": "Execute the teacher's spoken command with validated tools only; reply with short spoken-style Chinese suitable for classroom broadcast."
            if mode == "interaction"
            else "",
            "citation_policy": "Prefer authoritative sources, expose freshness, and never present timely facts as definitive without evidence.",
            "tool_safety_policy": "High-risk actions require confirmation; blocked or rejected actions must not execute.",
            "map_grounding": map_summary,
            "memory_projection": memory_summary,
            "retrieval_projection": retrieval_items,
        }
        return {
            "prompt_version": self.version,
            "mode": mode,
            "context_fingerprint": _fingerprint({"mode": mode, "parts": parts}),
            "context_parts": parts,
            "assembled_context": _stable_json({"mode": mode, "parts": parts}),
        }


class ConversationMemory:
    def __init__(self, store: RuntimeStore):
        self.store = store

    def get_or_create(
        self,
        project_id: str,
        assistant_mode: str,
        conversation_id: str = "",
        history: Optional[List[Dict[str, Any]]] = None,
        map_context: Optional[Dict[str, Any]] = None,
    ) -> ConversationRecord:
        conversation = self.store.get_conversation(conversation_id) if conversation_id else None
        if conversation is None:
            conversation = self.store.create_conversation(project_id, assistant_mode)
            for item in history or []:
                role = str(item.get("role") or "user")
                text = str(item.get("text") or item.get("content") or "").strip()
                if text:
                    self.store.append_conversation_message(
                        conversation.conversation_id,
                        role,
                        text,
                        assistant_mode=assistant_mode,
                        metadata={"seeded": True},
                    )
            conversation = self.store.get_conversation(conversation.conversation_id) or conversation
        if map_context:
            conversation.last_map_grounding = dict(map_context)
            conversation.pinned_state["last_map_grounding"] = dict(map_context)
            self.store.save_conversation(conversation)
        self._compress_if_needed(conversation)
        return conversation

    def append(self, conversation_id: str, role: str, text: str, assistant_mode: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        self.store.append_conversation_message(conversation_id, role, text, assistant_mode=assistant_mode, metadata=metadata)
        conversation = self.store.get_conversation(conversation_id)
        if conversation:
            self._compress_if_needed(conversation)

    def build_context(self, conversation: ConversationRecord) -> Dict[str, Any]:
        raw_messages = conversation.raw_messages[-8:]
        return {
            "raw_messages": raw_messages,
            "running_summary": conversation.running_summary,
            "task_memory": conversation.task_memory,
            "pinned_state": conversation.pinned_state,
            "last_map_grounding": conversation.last_map_grounding,
        }

    def update_task_memory(
        self,
        conversation: ConversationRecord,
        task_memory: Dict[str, Any],
        map_grounding: Dict[str, Any],
        pinned_state_updates: Optional[Dict[str, Any]] = None,
    ) -> None:
        conversation.task_memory = {**conversation.task_memory, **(task_memory or {})}
        conversation.pinned_state = {**conversation.pinned_state, **(pinned_state_updates or {})}
        if map_grounding:
            conversation.last_map_grounding = dict(map_grounding)
            conversation.pinned_state["last_map_grounding"] = dict(map_grounding)
        self.store.save_conversation(conversation)

    def _compress_if_needed(self, conversation: ConversationRecord) -> None:
        max_raw_messages = 8 if conversation.running_summary else 16
        if len(conversation.raw_messages) <= max_raw_messages:
            return
        older_messages = conversation.raw_messages[:-8]
        recent_messages = conversation.raw_messages[-8:]
        snippets = []
        for item in older_messages[-8:]:
            role = str(item.get("role") or "unknown")
            text = str(item.get("text") or "")[:160]
            snippets.append({"role": role, "text": text})
        summary = _stable_json({"compressed_messages": snippets})
        if summary:
            conversation.running_summary = f"{conversation.running_summary} {summary}".strip()[:1500]
            conversation.task_memory["summary_turns"] = int(conversation.task_memory.get("summary_turns") or 0) + len(older_messages)
        conversation.raw_messages = recent_messages
        self.store.save_conversation(conversation)


class AssistantRouter:
    def route(
        self,
        assistant_mode: str,
        message: str,
        history: List[Dict[str, Any]],
        map_context: Dict[str, Any],
        project_state: Dict[str, Any],
    ) -> Dict[str, str]:
        if assistant_mode == "knowledge":
            return {
                "intent": "knowledge",
                "reason": "explicit knowledge mode",
                "confidence": "1.00",
                "ambiguity_reason": "",
                "recommended_clarification": "",
            }
        if assistant_mode == "interaction":
            # 智能交互：语音操控专用模式。intent 固定，绝不经由教学路由，
            # 教学脚手架与知识检索不会串扰进来。
            return {
                "intent": "interaction",
                "reason": "explicit interaction mode",
                "confidence": "1.00",
                "ambiguity_reason": "",
                "recommended_clarification": "",
            }
        if assistant_mode == "teaching":
            return self._route_teaching(message, map_context)
        has_tool_hint = _contains_any(message, TOOL_ACTION_HINTS)
        has_explanation_hint = _contains_any(message, EXPLANATION_HINTS)
        if has_tool_hint and has_explanation_hint:
            return {
                "intent": "hybrid",
                "reason": "tool request with explanation",
                "confidence": "0.92",
                "ambiguity_reason": "",
                "recommended_clarification": "",
            }
        if has_tool_hint:
            return {
                "intent": "tool",
                "reason": "explicit tool instruction",
                "confidence": "0.84",
                "ambiguity_reason": "",
                "recommended_clarification": "",
            }
        if has_explanation_hint:
            return {
                "intent": "hybrid",
                "reason": "tool mode explanation request",
                "confidence": "0.63",
                "ambiguity_reason": "message asks for explanation without an explicit action target",
                "recommended_clarification": "Specify the map action first if you want the system to operate before explaining.",
            }
        return {
            "intent": "tool",
            "reason": "tool mode fallback",
            "confidence": "0.35",
            "ambiguity_reason": "no concrete tool action was found",
            "recommended_clarification": "Provide a specific operation or switch to knowledge mode.",
        }

    def _route_teaching(self, message: str, map_context: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
        """Teaching mode never asks the teacher to switch modes: an explicit map
        operation becomes a teaching action, reflection/question prompts keep
        their classroom framing, and everything else defaults to a teaching
        explanation."""
        if _contains_any(message, TEACHING_PREPARE_HINTS):
            return {
                "intent": "teaching_prepare",
                "reason": "explicit guided lesson-plan co-creation request",
                "confidence": "0.95",
                "ambiguity_reason": "",
                "recommended_clarification": "",
            }
        if _contains_any(message, TOOL_ACTION_HINTS):
            return {
                "intent": "teaching_action",
                "reason": "explicit map operation in teaching mode",
                "confidence": "0.88",
                "ambiguity_reason": "",
                "recommended_clarification": "",
            }
        if _contains_any(message, TEACHING_REFLECT_HINTS):
            return {
                "intent": "teaching_reflect",
                "reason": "lesson wrap-up or review request",
                "confidence": "0.82",
                "ambiguity_reason": "",
                "recommended_clarification": "",
            }
        if _contains_any(message, TEACHING_QUESTION_HINTS):
            return {
                "intent": "teaching_question",
                "reason": "classroom follow-up question design",
                "confidence": "0.76",
                "ambiguity_reason": "",
                "recommended_clarification": "",
            }
        teaching_context = (map_context or {}).get("teaching_context") if isinstance(map_context, dict) else {}
        phase = str((teaching_context or {}).get("phase") or "") if isinstance(teaching_context, dict) else ""
        if phase == "post_class":
            return {
                "intent": "teaching_reflect",
                "reason": "phase_default: post-class message defaults to reflection",
                "confidence": "0.72",
                "ambiguity_reason": "",
                "recommended_clarification": "",
            }
        return {
            "intent": "teaching_explain",
            "reason": "classroom question defaults to teaching explanation",
            "confidence": "0.70",
            "ambiguity_reason": "",
            "recommended_clarification": "",
        }


class KnowledgeEngine:
    def __init__(
        self,
        config: AppConfig,
        minimax_client: Any = None,
        resource_search: Any = None,
    ):
        self.config = config
        self.minimax_client = minimax_client
        self.resource_search = resource_search
        self.knowledge_units = self._load_units()

    def answer(
        self,
        question: str,
        map_context: Optional[Dict[str, Any]] = None,
        teaching_task: str = "",
    ) -> Dict[str, Any]:
        map_context = map_context or {}
        answer_type = "map_reading" if map_context.get("image_attachment") else self._classify(question)
        brainstorm_request = question.lstrip().startswith("GeoBot 头脑风暴：")
        if answer_type in {"assistant_identity", "assistant_model", "assistant_capability"}:
            return self._meta_answer(answer_type)

        # --- Phase 1: local KB lookup (fast, free) ---
        # Current-view map reading is grounded in the live map/screenshot, not
        # in a generic canned KB item. Skipping loose KB matches here prevents
        # unrelated teaching points from leaking into image interpretation.
        references_current_map = self._references_current_map((question or "").lower())
        matched_entry = None if answer_type == "map_reading" and references_current_map else self._match_entry(question)
        retrieval_mode = self._retrieval_mode(question, answer_type, matched_entry, map_context)
        entry = matched_entry if retrieval_mode in {"local", "local_web"} else None
        citations = list(entry.get("citations", [])) if entry else []
        retrieval_trace: List[Dict[str, Any]] = []
        if map_context.get("vision_summary"):
            retrieval_trace.append(
                {
                    "source": "map_vision",
                    "status": "success",
                    "provider": map_context.get("vision_provider", ""),
                    "snapshot_path": map_context.get("vision_snapshot_path", ""),
                }
            )
        elif map_context.get("vision_reason"):
            retrieval_trace.append({"source": "map_vision", "status": "fallback", "reason": map_context.get("vision_reason", "")})
        if citations:
            retrieval_trace.extend(self._score_sources(citations, source_type="local_kb", timely=answer_type == "timely_fact"))

        # --- Phase 2: online search for supplementary context ---
        teaching_context = map_context.get("teaching_context") if isinstance(map_context.get("teaching_context"), dict) else {}
        teaching_phase = str((teaching_context or {}).get("phase") or "")
        web_context = ""
        web_evidence_available = False
        # In-class requests skip online retrieval entirely: latency beats
        # coverage while the teacher is standing in front of the class.
        should_search_web = retrieval_mode in {"web", "local_web"}
        explicit_web = _contains_any(
            question,
            IMAGE_WEB_RETRIEVAL_HINTS if map_context.get("image_attachment") else WEB_RETRIEVAL_HINTS,
        )
        if self.resource_search is not None and should_search_web and (teaching_phase != "in_class" or explicit_web):
            try:
                web_results = self.resource_search.search(query=question, scope="web", limit=5)
                web_items = web_results.get("items", [])
                if web_items:
                    for item in web_items[:3]:
                        title = str(item.get("title") or "").strip()
                        url = str(item.get("url") or "").strip()
                        summary = str(item.get("summary") or "").strip()
                        evidence_verified = bool(item.get("evidence_verified", bool(summary)))
                        if not evidence_verified:
                            retrieval_trace.append(
                                {
                                    "source": "web_suggestion",
                                    "title": title,
                                    "url": url,
                                    "status": "suggestion_only",
                                }
                            )
                            continue
                        if title and url:
                            web_evidence_available = True
                            citations.append({"title": title, "url": url})
                            retrieval_trace.append({
                                "source": "web_search",
                                "title": title,
                                "url": url,
                                "authority_score": float(item.get("confidence") or 0.6),
                                "freshness_score": 0.85,
                            })
                        if summary:
                            web_context += f"- {title}: {summary}\n"
            except Exception:
                retrieval_trace.append({"source": "web_search", "status": "error"})

        web_verification_failed = should_search_web and not web_evidence_available
        if web_verification_failed:
            retrieval_trace.append({"source": "web_verification", "status": "unavailable"})

        # --- Phase 3: LLM-powered answer (primary path) ---
        llm_used = False
        population_guardrail_answer = self._population_guardrail_answer(question)
        verification_guardrail_answer = (
            self._unverified_timely_answer(question, entry) if web_verification_failed and not population_guardrail_answer else ""
        )
        deterministic_answer = population_guardrail_answer or verification_guardrail_answer
        if deterministic_answer:
            direct_answer = deterministic_answer
            mechanism_explanation = ""
            teaching_points = []
            confidence = 0.96 if population_guardrail_answer else 0.45
            retrieval_trace.append(
                {
                    "source": "population_concept_guardrail" if population_guardrail_answer else "timely_verification_guardrail",
                    "status": "success",
                }
            )
        elif self.minimax_client is not None and self.config.minimax_enabled():
            try:
                llm_answer = self._llm_answer(
                    question,
                    entry,
                    answer_type,
                    map_context,
                    web_context,
                    teaching_task=teaching_task,
                    web_verification_failed=web_verification_failed,
                )
                llm_used = True
                retrieval_trace.append({"source": "llm_generation", "status": "success"})
                direct_answer = llm_answer["direct_answer"]
                mechanism_explanation = llm_answer.get("mechanism_explanation", "")
                teaching_points = llm_answer.get("teaching_points", [])
                confidence = 0.45 if web_verification_failed else (0.88 if entry else 0.78)
            except Exception as exc:
                retrieval_trace.append({"source": "llm_generation", "status": "error", "detail": str(exc)})
                llm_used = False

        if not llm_used and not deterministic_answer:
            # Fallback to deterministic, classroom-safe templates.
            direct_answer = (
                entry.get("canonical_answer")
                if entry
                else "这个问题属于地理相关范围，但本地知识库里还没有完全对应的现成条目。"
                "我可以先按地理学的一般分析框架给出解释。"
            )
            if answer_type == "map_reading":
                direct_answer = self._map_reading_direct_answer(question, map_context)
            elif answer_type == "timely_fact":
                direct_answer = (
                    "这个问题具有时效性，但当前没有取得可核验的在线资料，"
                    "因此我不能把未经核实的数据当作当前结论。你可以明确要求联网核实后再问。"
                )
            mechanism_explanation = self._mechanism_text(question, entry, answer_type)
            teaching_points = list(entry.get("teaching_points", [])) if entry else self._default_teaching_points(answer_type)
            confidence = 0.92 if entry else (0.45 if answer_type == "timely_fact" else 0.68)
            if brainstorm_request:
                direct_answer = "头脑风暴生成失败：当前 AI 服务不可用，请稍后重试。"
                mechanism_explanation = ""
                teaching_points = []
                confidence = 0.0

        map_grounding = self._map_grounding(map_context, answer_type)
        return {
            "direct_answer": direct_answer,
            "mechanism_explanation": mechanism_explanation,
            "map_grounding": map_grounding,
            "teaching_points": teaching_points,
            "citations": citations,
            "confidence": confidence,
            "answer_type": answer_type,
            "retrieval_trace": retrieval_trace,
            "presentation": {
                **self._presentation_policy(answer_type),
                **({"show_map_grounding": False, "show_teaching_points": False} if teaching_task else {}),
            },
            "llm_used": llm_used,
            "retrieval_mode": retrieval_mode,
            "web_verified": web_evidence_available,
        }

    # ------------------------------------------------------------------
    # LLM-powered knowledge answer
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_think_tags(text: str) -> str:
        """Remove <think>...</think> blocks that some models emit."""
        import re as _re
        return _re.sub(r"<think>[\s\S]*?</think>", "", text, flags=_re.IGNORECASE).strip()

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        """Remove ```json ... ``` wrappers."""
        import re as _re
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = _re.sub(r"^```(?:json)?", "", cleaned, flags=_re.IGNORECASE).strip()
            cleaned = _re.sub(r"```\s*$", "", cleaned).strip()
        return cleaned

    @staticmethod
    def _sanitize_image_answer_coordinates(text: str, question: str) -> str:
        """Remove unsolicited coordinate details from an image answer.

        Vision summaries can contain graticule-derived latitude bands even
        when the user asked only about a spatial pattern. The prompt remains
        the primary control, while this small output guard prevents those
        internal reading aids from leaking into the final conversation.
        """
        if _contains_any(
            question,
            ("经纬度", "经度", "纬度", "坐标", "经线", "纬线", "比例尺", "尺度", "coordinate", "latitude", "longitude"),
        ):
            return text
        coordinate_pattern = re.compile(
            r"(?:\b\d{1,3}(?:\.\d+)?\s*°\s*[NSEW]\b|北纬|南纬|东经|西经|纬度|经度)",
            re.IGNORECASE,
        )
        kept: List[str] = []
        for line in text.splitlines():
            if not coordinate_pattern.search(line):
                kept.append(line)
                continue
            fragments = re.split(r"(?<=[。！？；])", line)
            kept.extend(fragment for fragment in fragments if fragment.strip() and not coordinate_pattern.search(fragment))
        return "\n".join(kept).strip()

    @staticmethod
    def _population_legend_values(vision_summary: str) -> List[str]:
        """Extract only explicitly printed population-legend values/classes."""
        values: List[str] = []
        in_legend = False
        for raw_line in vision_summary.splitlines():
            line = raw_line.strip()
            lowered = line.lower()
            if "legend" in lowered and not in_legend:
                in_legend = True
                continue
            if not in_legend:
                continue
            if line.startswith("#") or (
                line.startswith("**")
                and not re.match(r"^\*\*\s*[<>≤≥]?\s*\d", line)
                and "legend" not in lowered
            ):
                break
            match = re.match(
                r"^\s*-\s*(?:\*\*)?([<>≤≥]?\s*\d+(?:\.\d+)?(?:\s*[–—~-]\s*\d+(?:\.\d+)?)?\+?)",
                line,
            )
            if match is None:
                match = re.search(
                    r":\s*(?:\*\*)?([<>≤≥]?\s*\d+(?:\.\d+)?(?:\s*[–—~-]\s*\d+(?:\.\d+)?)?\+?)",
                    line,
                )
            if match:
                value = re.sub(r"\s+", "", match.group(1)).replace("~", "–").replace("—", "–")
                if value not in values:
                    values.append(value)
        if values and all(re.fullmatch(r"\d+(?:\.\d+)?", value) for value in values):
            values.sort(key=float)
        return values

    @classmethod
    def _ensure_population_legend_statement(cls, text: str, question: str, vision_summary: str) -> str:
        if "人口" not in question or "图例" not in question:
            return text
        summary_lower = vision_summary.lower()
        if "人口密度" not in vision_summary and "population density" not in summary_lower:
            return text
        values = cls._population_legend_values(vision_summary)
        if len(values) < 2:
            return text

        kept: List[str] = []
        for line in text.splitlines():
            fragments = re.split(r"(?<=[。！？；])", line)
            kept.extend(fragment for fragment in fragments if fragment.strip() and "图例" not in fragment)
        unit = "人/km²" if any(token in vision_summary for token in ("人/km²", "persons/km²", "persons per square kilometer")) else ""
        suffix = f"（{unit}）" if unit else ""
        legend = f"图例标注了{'、'.join(values)}{suffix}，颜色由浅到深表示人口密度升高。"
        body = "\n".join(kept).strip()
        return f"{body}\n\n{legend}" if body else legend

    def _llm_answer(
        self,
        question: str,
        entry: Optional[Dict[str, Any]],
        answer_type: str,
        map_context: Dict[str, Any],
        web_context: str = "",
        teaching_task: str = "",
        web_verification_failed: bool = False,
    ) -> Dict[str, Any]:
        """Call MiniMax LLM to generate a geography knowledge answer.

        The prompt asks for one natural Chinese answer. Structured teaching
        output is used only when the user explicitly asks for questions,
        lesson design, or a reflection checklist.
        """
        system_prompt = (
            "你是一位专业、自然、耐心的地理教学助手。默认使用简体中文，先直接回答用户真正关心的问题。\n"
            "回答应像真实交流：通常使用连贯短段落，只有比较、步骤或用户明确要求清单时才使用小标题或列表。\n"
            "不要套用固定的“证据点、原理分析、课堂要点、教师收束语”模板，不要输出 JSON、代码块、<think> 或 XML 标签。\n"
            "不要暴露检索轨迹、视觉摘要等内部字段，也不要主动报告经纬度、缩放等级或可见范围。\n"
            "不要用“知识库认为”“系统提示”“内部资料显示”等措辞描述回答来源。\n"
            "涉及图片时，把画面中可直接观察到的内容与地理推断区分开；文字、图例或边界看不清时自然说明不确定，不得编造。\n"
            "如果参考资料不足，直接说明限制并给出仍然可靠的判断，不要用生硬的系统提示口吻。\n"
        )
        brainstorm_request = question.lstrip().startswith("GeoBot 头脑风暴：")
        if teaching_task:
            system_prompt += (
                "\n你正在“专业教学智能体”模式下支持地理课堂。请把核心答案讲清楚，最后增加“回答总结：”，"
                "用一句话概括刚才的回答。不要输出证据或观察点、给学生的问题、教师收束语或下一步，"
                "不要复述地图中心坐标、缩放级别、可见范围等系统元数据，也不得编造图层数据或学生表现。\n"
            )
        if "人口" in question:
            system_prompt += (
                "人口地理回答必须严格区分人口总量、人口密度、迁入、迁出、净迁移和自然增长，不能互相替代。"
                "比较两个地区时先核对比较方向，结论必须与同一回答中的数字和表格一致。"
                "参考上下文没有给出对应年份和数值时，优先做可靠的定性比较，不自行编造人口、比例、排名或面积数据。\n"
            )
        if web_verification_failed:
            system_prompt += (
                "问题包含时效或核验意图，但本次没有取得包含具体事实的在线检索结果。"
                "你可以回答本地知识中的稳定定义，但必须明确说明最新或当前部分尚未核实；"
                "不得给出现时人口数、比例、排名，也不得把机构主页链接当成已经核验的证据。\n"
            )
        vision_summary = str(map_context.get("vision_summary") or "").strip()
        if vision_summary:
            system_prompt = (
                "你是一个受约束的地理图片信息转述编辑器。默认使用自然、简洁的简体中文回答。\n"
                "视觉读图结果是唯一事实来源，用户问题只决定从中挑选哪些内容，不授权你调用常识、记忆或外部知识补充答案。\n"
                "只可忠实翻译、压缩和重组视觉读图结果已经明确陈述的内容。任何地名、水域名、山名、行政区名、"
                "数值、方向和边界性质，必须在视觉读图结果中明确出现才能写入答案。\n"
                "视觉读图结果中已有中文专名时必须逐字复制，禁止改写或重新音译；只有外文名时宁可保留外文。"
                "数值、单位和大于小于等比较关系也必须保持原意，不得自行扩大或缩小范围。\n"
                "严禁使用“很可能是”“应该是”后接视觉读图结果中没有的专名；无法确认名称时，只描述图中可见的形态和位置关系，"
                "并明确说名称无法从图中确认。不要添加视觉摘要以外的成因、数量、历史或区域背景。\n"
                "先回答核心问题，再用自然短段落补充必要的不确定性；不要输出固定教学模板、JSON、代码块或内部字段。\n"
            )
            system_prompt += (
                "默认写成两到四个简短自然段；除非用户明确要求清单或逐项对照，不要使用 Markdown 标题。\n"
                "图例数值必须逐项保持视觉读图结果中的原始区间、单位和不等号；不能合并等级，也不能把一个等级的颜色或范围移给另一个等级。\n"
            )
            if "人口" in question:
                system_prompt += (
                    "这是人口专题图片转述：全文通常不超过 260 个汉字，只回答用户询问的变量、时间和空间差异，不要枚举无关城市或区域。\n"
                    "如果视觉结果只说图例印有若干刻度值，就按刻度值表述，不得擅自改写成闭区间或大于等于关系；只有视觉结果明确给出区间时才可逐字使用该区间。\n"
                    "用户没有询问原因或影响因素时，不得补充气候、地形、水源、农业、工业化、城市化等成因。\n"
                    "不要使用“像素”“内部读图结果”等机器处理词。线状标志只能按图中可见作用描述；除非图例明确说明，不得称为行政边界、法定边界或绝对分界线。\n"
                )
            if not _contains_any(question, ("经纬度", "坐标", "经线", "纬线", "比例尺", "尺度")):
                system_prompt += "用户没有询问坐标或尺度，答案中不要出现经纬度、坐标或经纬网数值。\n"
        if teaching_task:
            if teaching_task == "teaching_prepare":
                system_prompt += (
                    "\n用户准备共创一整节课。只说明已进入分步教案共创，并邀请用户先提供年级、课题、课时和学情；"
                    "不要在聊天中一次性输出长教案，也不要输出内部字段。\n"
                )
            elif teaching_task == "teaching_question":
                system_prompt += "\n用户明确需要课堂提问设计，可以用简短列表呈现由观察到解释的递进问题，并提示常见误区。\n"
            elif teaching_task == "teaching_reflect":
                system_prompt += (
                    "\n用户明确需要课后复盘，可以自然地概括已讲内容、易错提醒和下一步建议；"
                    "没有真实课堂记录时不得编造学生表现或掌握程度。\n"
                )

        if brainstorm_request:
            system_prompt += (
                "\n本次是课堂头脑风暴活动。忽略上面的常规三部分格式，只输出以下三部分："
                "“头脑风暴问题：”“回答：”“回答总结：”。问题必须体现区域差异、条件变化、尺度转换或"
                "反直觉比较中的至少一种；回答总结必须是一句话。不得输出教师提示、系统图层名或视口元数据。\n"
            )

        teaching_context = map_context.get("teaching_context") if isinstance(map_context.get("teaching_context"), dict) else {}
        phase = str((teaching_context or {}).get("phase") or "")
        if phase == "in_class":
            system_prompt += (
                "\n当前正在课堂授课：全文控制在 180 字以内，直接回答探究问题，不要展开背景综述；"
                "结尾用一句“回答总结”帮助学生概括。\n"
            )
        elif phase == "course_prep":
            asks_for_lesson_design = teaching_task == "teaching_question" or _contains_any(
                question,
                ("教学设计", "教案", "备课", "课堂活动", "问题链", "怎么教", "如何讲", "教学步骤"),
            )
            if asks_for_lesson_design:
                system_prompt += (
                    "\n当前处于课前备课，用户明确需要教学设计：可以组织问题阶梯、地图证据路线和预演话术，"
                    "设计的问题要附预期答案要点和常见误区。\n"
                )
            else:
                system_prompt += (
                    "\n当前虽处于课前备课，但这是普通知识问答：保持 2 至 4 个自然短段落，通常不超过 350 字，"
                    "不要自动扩展成完整教案、历史综述或多级标题。\n"
                )
        elif phase == "post_class":
            system_prompt += (
                "\n当前处于课后复盘：必须优先引用参考上下文中“课堂真实记录”里的具体数字；"
                "记录之外的学生表现一律不得推断或编造。\n"
            )

        # Build context from local KB entry and web search
        context_parts: List[str] = []
        if entry:
            context_parts.append(f"本地知识库参考：{entry.get('canonical_answer', '')}")
            kb_points = entry.get("teaching_points", [])
            if kb_points:
                context_parts.append(f"知识库要点：{'；'.join(kb_points)}")
        if web_context:
            context_parts.append(f"在线参考资料：\n{web_context}")
        if vision_summary:
            context_parts.append(f"视觉读图结果（图片事实仅限以下内容）：{vision_summary}")

        map_summary = "" if vision_summary else self._map_context_brief(map_context)
        if map_summary:
            context_parts.append(f"当前地图状态：{map_summary}")

        session_digest = str(map_context.get("session_digest") or "").strip()
        if session_digest:
            context_parts.append(f"课堂真实记录（可引用具体数字）：{session_digest}")

        user_content = question
        if context_parts:
            user_content = f"问题：{question}\n\n参考上下文：\n" + "\n".join(context_parts)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        raw = self.minimax_client.chat_completion(messages, temperature=0.0 if vision_summary else 0.3)

        # --- Post-process: strip think tags, code fences, JSON wrappers ---
        cleaned = self._strip_think_tags(raw)
        cleaned = self._strip_code_fences(cleaned)
        if vision_summary:
            cleaned = self._sanitize_image_answer_coordinates(cleaned, question)
            cleaned = self._ensure_population_legend_statement(cleaned, question, vision_summary)
        if phase == "post_class" and session_digest:
            try:
                digest = json.loads(session_digest)
            except (TypeError, json.JSONDecodeError):
                digest = {}
            if isinstance(digest, dict) and digest.get("response_data_collected") is False:
                cleaned = self._render_teacher_only_reflection(digest)

        # If the model still returned JSON despite the prompt, extract text from it
        if cleaned.startswith("{"):
            try:
                parsed = json.loads(cleaned)
                return {
                    "direct_answer": str(parsed.get("direct_answer") or ""),
                    "mechanism_explanation": str(parsed.get("mechanism_explanation") or ""),
                    "teaching_points": list(parsed.get("teaching_points") or []),
                }
            except json.JSONDecodeError:
                pass

        return {
            "direct_answer": cleaned,
            "mechanism_explanation": "",
            "teaching_points": [],
        }

    @staticmethod
    def _render_teacher_only_reflection(digest: Dict[str, Any]) -> str:
        """Render a post-class summary without inferring uncollected student data."""
        observations = digest.get("observations") if isinstance(digest.get("observations"), dict) else {}
        verdicts = observations.get("verdict_counts") if isinstance(observations.get("verdict_counts"), dict) else {}
        questions = [item for item in list(digest.get("questions") or []) if isinstance(item, dict)]
        stages = [item for item in list(digest.get("stages") or []) if isinstance(item, dict)]
        total = int(observations.get("total") or 0)
        parts = [
            "本次未采集课堂作答数据，因此不能据此判断正确率、最易错题或全班掌握程度。",
            (
                f"系统现有证据为：教师口头呈现 {len(questions)} 个问题，记录教师观察 {total} 条"
                f"（答对 {int(verdicts.get('correct') or 0)}、部分 {int(verdicts.get('partial') or 0)}、"
                f"误区 {int(verdicts.get('misconception') or 0)}），保存课堂截图 {int(digest.get('snapshot_count') or 0)} 张。"
            ),
        ]
        tags = [
            item
            for item in list(observations.get("misconception_tags") or [])
            if isinstance(item, (list, tuple)) and len(item) >= 2
        ]
        if tags:
            parts.append("教师明确记录的误区标签为：" + "、".join(f"{item[0]} {item[1]} 次" for item in tags[:3]) + "。")
        overtime = []
        for item in stages:
            try:
                actual = float(item.get("actual_minutes") or 0)
                planned = float(item.get("planned_minutes") or 0)
            except (TypeError, ValueError):
                continue
            if planned > 0 and actual > planned * 1.3:
                overtime.append(str(item.get("title") or item.get("stage_id") or "未命名环节"))
        if overtime:
            parts.append("按系统计时，超出计划的环节有：" + "、".join(overtime[:2]) + "；请结合是否存在暂停或演示等待再判断是否调整教案。")
        else:
            parts.append("下一步建议依据教师观察设计一题同类复测；如需判断班级掌握度，应在下次课采集课堂作答或补充有内容的观察备注。")
        return "\n\n".join(parts)

    @staticmethod
    def _parse_plain_answer(text: str) -> Dict[str, Any]:
        """Split a plain-text LLM answer into direct_answer, mechanism, and
        teaching points by looking for section markers."""
        import re as _re

        direct_parts: List[str] = []
        mechanism = ""
        teaching_points: List[str] = []

        # Try to split on known section headers
        mechanism_match = _re.search(
            r"\n\s*(?:原理分析|原理机制|机制解释|原理解释)[：:]\s*",
            text,
        )
        teaching_match = _re.search(
            r"\n\s*(?:课堂要点|教学要点|要点总结|要点)[：:]\s*",
            text,
        )

        # Determine the boundary positions
        mech_start = mechanism_match.start() if mechanism_match else len(text)
        teach_start = teaching_match.start() if teaching_match else len(text)

        # Direct answer = everything before both section markers
        direct_end = min(mech_start, teach_start)
        direct_parts.append(text[:direct_end].strip())

        # Mechanism = text between mechanism marker and teaching marker (or end)
        if mechanism_match:
            mech_content_start = mechanism_match.end()
            mech_content_end = teach_start if teach_start > mech_start else len(text)
            mechanism = text[mech_content_start:mech_content_end].strip()

        # Teaching points = bullet lines after the teaching marker
        if teaching_match:
            points_text = text[teaching_match.end():].strip()
            for line in points_text.split("\n"):
                line = line.strip()
                if not line:
                    continue
                # Strip leading bullet markers
                line = _re.sub(r"^[-•·*]\s*", "", line)
                line = _re.sub(r"^\d+[.、)\]]\s*", "", line)
                if line:
                    teaching_points.append(line)

        return {
            "direct_answer": "\n\n".join(p for p in direct_parts if p),
            "mechanism_explanation": mechanism,
            "teaching_points": teaching_points[:6],
        }

    def _meta_answer(self, answer_type: str) -> Dict[str, Any]:
        llm_status = self.config.llm_status()
        provider = str(llm_status.get("provider") or "unknown")
        model = str(llm_status.get("model") or "unknown")
        configured = bool(llm_status.get("configured"))

        if answer_type == "assistant_identity":
            return {
                "direct_answer": "我是本系统里的“超级地理助手”，负责地理知识问答，以及 WebGIS 场景下的地图操作辅助。复杂的 GIS 分析与制图请使用后台 GIS 分析工作流。",
                "mechanism_explanation": "",
                "map_grounding": "",
                "teaching_points": [
                    "我可以回答地理概念、区域地理、地图判读和 GIS 方法问题。",
                    "我也可以协助执行课堂地图操作、图层控制；复杂空间分析请走后台 GIS 分析工作流。",
                    "高风险操作会进入确认流程，不会默认直接执行。",
                ],
                "citations": [],
                "confidence": 0.99,
                "answer_type": answer_type,
                "retrieval_trace": [{"source": "runtime_identity", "configured": configured}],
                "internal_notes": "这类问题属于助手身份说明，不需要按地理知识点或当前地图画面来解释。",
                "presentation": self._presentation_policy(answer_type),
            }

        if answer_type == "assistant_model":
            direct_answer = f"当前后端配置接入的大模型是 {provider} 提供的 {model}。"
            if not configured:
                direct_answer = "当前后端还没有完成可用的大模型配置，因此暂时不能稳定使用在线模型回答。"
            return {
                "direct_answer": direct_answer,
                "mechanism_explanation": "",
                "map_grounding": "",
                "teaching_points": [
                    f"当前 provider: {provider}",
                    f"当前 model: {model}",
                    f"配置状态: {'已配置' if configured else '未配置'}",
                ],
                "citations": [],
                "confidence": 0.98 if configured else 0.9,
                "answer_type": answer_type,
                "retrieval_trace": [{"source": "runtime_llm_status", **llm_status}],
                "internal_notes": "这里回答的是系统运行配置，不是地理知识点，因此不应强行关联当前地图。",
                "presentation": self._presentation_policy(answer_type),
            }

        return {
            "direct_answer": "我是面向本系统的超级地理助手，既能做知识问答，也能协助地图与 GIS 工具操作。",
            "mechanism_explanation": "",
            "map_grounding": "",
            "teaching_points": [
                "知识问答优先覆盖地理学与 GIS 范围。",
                "工具操作会遵循风险分级与确认机制。",
                "涉及当前地图时，我会结合画面状态补充解释。",
            ],
            "citations": [],
            "confidence": 0.98,
            "answer_type": answer_type,
            "retrieval_trace": [{"source": "runtime_capability"}],
            "internal_notes": "这类问题属于助手能力说明，不需要用地理空间分析框架作答。",
            "presentation": self._presentation_policy(answer_type),
        }

    def _presentation_policy(self, answer_type: str) -> Dict[str, Any]:
        if answer_type == "assistant_identity":
            return {
                "show_mechanism": False,
                "show_map_grounding": False,
                "show_teaching_points": False,
                "teaching_points_title": "课堂要点",
            }
        if answer_type == "assistant_model":
            return {
                "show_mechanism": False,
                "show_map_grounding": False,
                "show_teaching_points": False,
                "teaching_points_title": "运行配置",
            }
        if answer_type == "assistant_capability":
            return {
                "show_mechanism": False,
                "show_map_grounding": False,
                "show_teaching_points": True,
                "teaching_points_title": "我可以这样帮你",
            }
        return {
            "show_mechanism": True,
            "show_map_grounding": answer_type == "map_reading",
            "show_teaching_points": True,
            "teaching_points_title": "课堂要点",
        }

    def render_public_answer(self, knowledge: Dict[str, Any], include_teaching_points: bool = True) -> str:
        answer_type = str(knowledge.get("answer_type") or "")
        presentation = dict(knowledge.get("presentation") or self._presentation_policy(answer_type))
        sections = [str(knowledge.get("direct_answer") or "").strip()]
        if presentation.get("show_mechanism", True):
            sections.append(str(knowledge.get("mechanism_explanation") or "").strip())
        if presentation.get("show_map_grounding", True):
            sections.append(str(knowledge.get("map_grounding") or "").strip())
        if include_teaching_points and presentation.get("show_teaching_points", True):
            teaching_points = [str(item).strip() for item in list(knowledge.get("teaching_points") or []) if str(item).strip()]
            if teaching_points:
                title = str(presentation.get("teaching_points_title") or "课堂要点")
                sections.append(f"{title}：\n- " + "\n- ".join(teaching_points))
        return "\n\n".join(part for part in sections if part)

    def _score_sources(self, citations: List[Dict[str, str]], source_type: str, timely: bool) -> List[Dict[str, Any]]:
        scored = []
        for item in citations:
            url = str(item.get("url") or "")
            allowlist_match = any(domain in url for domain in GEOGRAPHY_ALLOWLIST)
            scored.append(
                {
                    "source": source_type,
                    "title": item.get("title", ""),
                    "url": url,
                    "allowlist_match": allowlist_match,
                    "authority_score": 0.96 if allowlist_match else 0.65,
                    "freshness_score": 0.9 if timely else 0.6,
                    "conflict_resolution": "none",
                    "citation_required": timely,
                }
            )
        return scored

    def _load_units(self) -> List[Dict[str, Any]]:
        return KnowledgeBaseService(self.config).build_engine_units()

    def _classify(self, question: str) -> str:
        lowered = (question or "").lower()
        if _contains_any(lowered, ("什么大模型", "什么模型", "哪个模型", "model", "llm", "provider")):
            return "assistant_model"
        if _contains_any(lowered, ("你是谁", "你是什么", "你是干什么的", "介绍一下你自己", "who are you")):
            return "assistant_identity"
        if _contains_any(lowered, ("你能做什么", "你会什么", "能帮我做什么", "help", "capability")):
            return "assistant_capability"
        if self._references_current_map(lowered) or _contains_any(lowered, ("读图", "判读", "图上", "图中")):
            return "map_reading"
        if _contains_any(lowered, TIME_SENSITIVE_HINTS):
            return "timely_fact"
        if _contains_any(lowered, ("遥感", "gis", "rs", "空间分析", "buffer", "overlay")):
            return "gis_method"
        if _contains_any(lowered, MAP_READING_HINTS):
            return "map_reading"
        if _contains_any(lowered, ("地区", "区域", "沿海", "中国", "亚洲")):
            return "regional_geography"
        return "geo_concept"

    def _references_current_map(self, lowered_question: str) -> bool:
        return _contains_any(lowered_question, CURRENT_MAP_HINTS) or (
            "当前" in lowered_question and _contains_any(lowered_question, ("地图", "视图", "画面", "图层", "区域", "选区"))
        )

    @staticmethod
    def _population_guardrail_answer(question: str) -> str:
        """Return concise, deterministic answers for common population misconceptions.

        These concepts are frequently misanswered by swapping absolute and
        relative indicators or by treating a one-way flow as net migration.
        Keeping the core distinction deterministic prevents a fluent model
        response from contradicting its own numbers or the map legend.
        """
        text = question or ""
        if "人口密度" in text and _contains_any(text, ("人口总量", "总人口", "人口数量", "总量")):
            answer = (
                "人口总量回答一个地区“有多少人”，人口密度回答“单位面积上有多少人”，"
                "计算上是人口总量除以土地面积。两者不能互相替代：总量大不一定密度高，密度高也不必然意味着总量更大。"
            )
            if "上海" in text and "西藏" in text:
                answer += (
                    "以上海和西藏为例，上海的人口总量和人口密度都高于西藏，所以这组地区不能用来证明“密度高但总量小”；"
                    "它更适合说明土地面积差异会显著改变密度。若要做数量比较，还必须使用同一年、同一人口口径和同一级行政单元的数据。"
                )
            return answer

        if "自然增长率" in text and _contains_any(text, ("下降", "降低", "放缓")) and _contains_any(
            text, ("人口总量", "总人口", "人口增加", "继续增加")
        ):
            return (
                "自然增长率下降只表示人口自然增长的速度放慢，不等于增长率已经为零或转为负值。"
                "只要自然增长率仍为正，出生人数仍多于死亡人数，人口总量就可能继续增加；同样的增长率作用在不同人口基数上，带来的增量也不同。"
                "判断一个地区的总人口变化时，还要把净迁移与自然增长合并考虑，不能只看增长率是升还是降。"
            )

        if "自然增长" in text and "负" in text and _contains_any(text, ("人口", "总量", "减少", "下降")):
            return (
                "自然增长为负只说明死亡人数多于出生人数，并不能单独决定人口总量一定减少。"
                "一个地区的人口变化由自然增长和净迁移共同决定：如果净迁入大于自然减少，总量仍可增加；"
                "如果净迁入不足以抵消自然减少，总量才会下降。比较时还要统一统计时期和常住人口等人口口径。"
            )

        if "净迁入" in text and _contains_any(text, ("常住人口", "人口总量", "总人口")) and _contains_any(
            text, ("下降", "减少", "仍可能", "为什么")
        ):
            return (
                "净迁入为正只说明迁入人数多于迁出人数，不代表人口总量必然增加。"
                "常住人口变化可以概括为“自然增长加净迁移”：当自然减少的规模大于净迁入时，最终总量仍会下降；"
                "反过来，净迁入足以抵消自然减少时，总量才会增加。判断时必须使用同一时期、同一人口口径的数据。"
            )

        if "常住人口" in text and "户籍人口" in text and _contains_any(text, ("比较", "混用", "口径", "规模")):
            return (
                "常住人口和户籍人口不能直接混用比较。常住人口反映实际在当地居住的人口，户籍人口按户籍登记地统计，"
                "同一个人可能计入一个地区的户籍人口、同时计入另一个地区的常住人口。"
                "比较城市人口规模时，应统一年份、行政范围和人口口径，并在图题、表头或注释中明确写出“常住人口”或“户籍人口”。"
            )

        if _contains_any(text.lower(), ("top", "排名", "排行")) and "人口" in text and _contains_any(
            text, ("年份", "行政范围", "统计口径", "可比")
        ):
            return (
                "人口排名要先统一比较对象，再进行排序。所有城市应使用同一统计年份、同一人口口径和同一行政范围，"
                "例如不能把一个城市的全域常住人口与另一个城市的市辖区户籍人口放在同一榜单。"
                "结果中应同时标明数据年份、统计单位、人口口径、行政层级和来源；缺少任一项时，排名只能视为不可直接比较的参考。"
            )

        if "迁移" in text and "流线" in text and _contains_any(text, ("净迁入", "净迁移", "净流入", "净迁出")):
            return (
                "流线越粗代表什么，必须先看图例；只有图例明确规定线宽表示迁移人数时，粗线才能说明该条起讫路径的迁移规模更大。"
                "它仍不等于一个地区的全部迁入量。净迁入要用所有迁入量减去所有迁出量，"
                "因此只看到单向流线或几条示意流线，不能判断净迁入；还需要完整的双向流量、统计时期和人口口径。"
            )

        if _contains_any(text, ("七普", "2020年", "2020 年")) and _contains_any(
            text, ("当前数据", "历史数据", "现在", "最新", "时效", "实时")
        ):
            return (
                "课堂上应把它明确称为“2020年第七次全国人口普查数据”，用来说明2020年的空间格局，而不要简称为“当前人口数据”。"
                "讲解时可以先用七普数据比较区域分布，再单独提醒学生：格局判断有明确的数据时点，后续人口变化需要另找更新的官方统计。"
                "课件、图例和口播都应同时标注年份、常住人口或户籍人口口径、统计单位和来源；没有完成最新核验时，不补写现时人口数。"
            )

        return ""

    @staticmethod
    def _unverified_timely_answer(question: str, entry: Optional[Dict[str, Any]]) -> str:
        stable_answer = str((entry or {}).get("canonical_answer") or "").strip()
        if stable_answer:
            return (
                f"{stable_answer}"
                "不过，你问到的“今天、最新或当前”部分需要用带明确统计日期和口径的在线资料核验。"
                "本次没有取得包含具体事实的有效在线结果，因此不能据此断言现状仍然相同，也不提供未经核实的现时比例、排名或人口数。"
            )
        return (
            "这个问题需要最新或当前资料，但本次没有取得包含具体事实、统计日期和口径的有效在线结果。"
            "因此我暂时不能给出当前数值或肯定结论；机构主页只能作为继续查找的入口，不能当作已经完成核验。"
        )

    def _match_entry(self, question: str) -> Optional[Dict[str, Any]]:
        lowered = (question or "").lower()
        lowered = (
            lowered.replace("hu huanyong line", "胡焕庸线")
            .replace("hu huanyong", "胡焕庸")
            .replace("heihe-tengchong line", "胡焕庸线")
            .replace("heihe-tengchong", "胡焕庸")
        )
        for item in self.knowledge_units:
            title = str(item.get("title") or "").strip().lower()
            tags = [str(tag or "").strip().lower() for tag in item.get("tags", [])]
            meaningful_tags = [tag for tag in tags if len(tag) >= 2 and tag not in MATCH_STOP_WORDS]
            if (len(title) >= 2 and title in lowered) or any(tag in lowered for tag in meaningful_tags):
                return item
            query_tokens = {
                token
                for token in re.findall(r"[a-z0-9_-]{3,}|[\u4e00-\u9fff]{2,}", lowered)
                if token not in MATCH_STOP_WORDS
            }
            haystack_tokens = {
                token
                for token in re.findall(r"[a-z0-9_-]{3,}|[\u4e00-\u9fff]{2,}", " ".join([title, *meaningful_tags]))
                if token not in MATCH_STOP_WORDS
            }
            if query_tokens and len(query_tokens & haystack_tokens) >= 2:
                return item
        return None

    def _retrieval_mode(
        self,
        question: str,
        answer_type: str,
        entry: Optional[Dict[str, Any]],
        map_context: Dict[str, Any],
    ) -> str:
        if answer_type in META_ANSWER_TYPES:
            return "none"
        wants_local = _contains_any(question, LOCAL_RETRIEVAL_HINTS) or entry is not None
        wants_web = answer_type == "timely_fact" or _contains_any(question, WEB_RETRIEVAL_HINTS)
        teaching_context = map_context.get("teaching_context") if isinstance(map_context.get("teaching_context"), dict) else {}
        if str((teaching_context or {}).get("phase") or "") == "in_class" and not _contains_any(question, WEB_RETRIEVAL_HINTS):
            wants_web = False
        if map_context.get("image_attachment"):
            # An image question is grounded in the image by default. Merely
            # mentioning words such as "current data" or "source" (including
            # in a negation) must not silently turn visual reading into a web
            # lookup. Only an explicit request to combine or verify newer
            # material enables online retrieval.
            wants_local = _contains_any(question, LOCAL_RETRIEVAL_HINTS)
            wants_web = _contains_any(question, IMAGE_WEB_RETRIEVAL_HINTS)
        if wants_local and wants_web:
            return "local_web"
        if wants_local:
            return "local"
        if wants_web:
            return "web"
        return "none"

    def _visible_layer_names(self, map_context: Dict[str, Any], limit: int = 6) -> List[str]:
        names: List[str] = []
        for item in list(map_context.get("visible_layers") or [])[:limit]:
            if isinstance(item, dict):
                name = str(item.get("name") or item.get("layer_id") or "").strip()
            else:
                name = str(item or "").strip()
            if name:
                names.append(name)
        return names

    def _map_context_brief(self, map_context: Dict[str, Any]) -> str:
        parts: List[str] = []
        layer_names = self._visible_layer_names(map_context)
        if layer_names:
            parts.append(f"可见图层包括 {', '.join(layer_names)}")
        selected_region = map_context.get("selected_region") or {}
        if isinstance(selected_region, dict) and selected_region.get("label"):
            parts.append(f"当前聚焦区域为 {selected_region.get('label')}")
        selected_feature = str(map_context.get("selected_feature_summary") or "").strip()
        if selected_feature:
            parts.append(f"已选要素：{selected_feature[:160]}")
        vision_summary = str(map_context.get("vision_summary") or "").strip()
        if vision_summary:
            parts.append("已结合图片内容")
        elif map_context.get("vision_reason"):
            parts.append("图片识别当前不可用")
        active_materials = map_context.get("active_lesson_materials") or []
        if active_materials:
            material_titles = [
                str(item.get("title") or item.get("id") or "").strip()
                for item in list(active_materials)[:4]
                if isinstance(item, dict)
            ]
            material_titles = [title for title in material_titles if title]
            if material_titles:
                parts.append(f"已绑定教学资料：{', '.join(material_titles)}")
        return "；".join(parts)

    def _map_reading_direct_answer(self, question: str, map_context: Dict[str, Any]) -> str:
        lowered = (question or "").lower()
        layer_names = self._visible_layer_names(map_context)
        map_brief = self._map_context_brief(map_context)
        vision_summary = str(
            map_context.get("vision_summary")
            or map_context.get("screen_analysis")
            or map_context.get("screenshot_summary")
            or ""
        ).strip()

        if vision_summary:
            summary_text = vision_summary
            for prefix in ("视觉读图：", "视觉读图:"):
                if summary_text.startswith(prefix):
                    summary_text = summary_text[len(prefix):].strip()
            return f"从当前地图画面可判读：{summary_text}"

        if _contains_any(lowered, ("地貌", "地形", "地势", "等高线")):
            answer = (
                "当前视图的地貌特征应从地势起伏、地形单元边界、水系切割和人类活动分布四个方面判读。"
                "课堂讲解时可以先指出主要高低起伏区，再说明山地、丘陵、平原、盆地或河谷等地貌单元如何影响河流、交通和聚落布局。"
            )
        else:
            answer = (
                "当前视图可以按“位置范围、图层主题、空间分布、异常区域、成因解释”的顺序判读。"
                "先说明地图展示的区域和主题，再抓住高值/低值、密集/稀疏、连续/破碎等空间格局，最后联系自然条件和人类活动解释原因。"
            )

        if map_brief:
            answer += f"\n\n本次判读依据当前地图状态：{map_brief}。"
        elif layer_names:
            answer += f"\n\n本次判读依据当前可见图层：{', '.join(layer_names)}。"
        else:
            answer += "\n\n本次请求没有携带可见图层、选区或截图信息，因此只能给出通用读图框架；若要识别图面颜色、图例数值或具体地貌边界，请使用“读图讲解”截图识别。"
        if map_context.get("vision_reason"):
            answer += "\n\n当前没有取得可用的图片识别结果，因此不能把图层状态当成画面内容继续推断。"
        return answer

    def _mechanism_text(self, question: str, entry: Optional[Dict[str, Any]], answer_type: str) -> str:
        if answer_type == "gis_method":
            return "GIS 方法类问题通常要先明确分析对象、空间规则和解释目标。"
        if answer_type == "map_reading":
            if _contains_any(question, ("地貌", "地形", "地势", "等高线")):
                return "地貌判读的核心是把图面符号转化为地势起伏和外力作用过程：颜色分层、等高线疏密、水系形态和交通聚落分布，都可以作为判断山地、平原、盆地、河谷等地貌单元的依据。"
            return "地图判读不能只描述形状，还要把符号、位置、尺度和区域联系串起来。"
        if entry:
            return " ".join(entry.get("teaching_points", [])[:2]).strip()
        return "地理解释通常要同时说明空间分布、形成过程和区域差异。"

    def _default_teaching_points(self, answer_type: str) -> List[str]:
        if answer_type == "gis_method":
            return [
                "先定义分析对象和分析单元。",
                "把技术步骤和地理解释分开说明。",
                "同时解释空间格局和成因机制。",
            ]
        if answer_type == "map_reading":
            return [
                "先确定图名、图例、比例尺和区域位置。",
                "再判读高低起伏、地貌单元、空间格局和异常区。",
                "最后联系水系、气候、人类活动解释成因与影响。",
            ]
        return [
            "先概括空间现象或核心概念。",
            "再解释主要影响因素。",
            "最后收束到课堂结论。",
        ]

    def _map_grounding(self, map_context: Dict[str, Any], answer_type: str = "") -> str:
        if map_context.get("image_attachment") or map_context.get("vision_summary"):
            # The natural-language answer already explains the attached image.
            # Do not append an internal-looking "based on current map" footer.
            return ""
        map_brief = self._map_context_brief(map_context)
        if map_brief:
            return f"基于当前地图：{map_brief}。"
        if answer_type == "map_reading":
            return "当前问题需要地图判读，但本次请求没有携带可见图层、选区或截图信息；可刷新地图状态，或使用“读图讲解”获取截图识别。"
        return "当前回答没有必须依赖的地图画面依据。"


class ToolPlanner:
    def __init__(self, llm_planner: LLMPlanner, assistant_service: AssistantService):
        self.llm_planner = llm_planner
        self.assistant_service = assistant_service

    def plan(
        self,
        message: str,
        project: ProjectRecord,
        map_context: Dict[str, Any],
        target: str,
        input_mode: str,
        intent: str = "",
    ) -> Dict[str, Any]:
        if intent == "interaction":
            # 智能交互：语音/文字都直达分层规划（规则快通道 → MiniMax），
            # 不做 tool 模式的 clarification 降级。
            return self.llm_planner.plan_actions(
                message,
                project,
                map_context=map_context,
                target=target,
                input_mode=input_mode,
                assistant_mode="interaction",
            )
        if input_mode == "voice" and target == "webgis":
            return self.llm_planner.plan_actions(
                message,
                project,
                map_context=map_context,
                target=target,
                input_mode=input_mode,
            )
        if intent == "teaching_action":
            # Teaching mode never answers with "switch to knowledge mode"; an
            # explain-only plan is a legitimate teaching action.
            return self.llm_planner.plan_actions(
                message,
                project,
                map_context=map_context,
                target=target,
                input_mode=input_mode,
            )
        if not _contains_any(message, TOOL_ACTION_HINTS) and not _contains_any(message, EXPLANATION_HINTS):
            return {
                "assistant_message": "Tool mode needs a concrete action. Please specify the operation or switch to knowledge mode.",
                "target": target,
                "actions": [],
                "planner": "clarification",
            }
        plan = self.llm_planner.plan_actions(
            message,
            project,
            map_context=map_context,
            target=target,
            input_mode=input_mode,
        )
        if plan.get("actions") == [{"tool_name": "explain_current_view", "tool_params": {"focus": message.strip()}}] and not _contains_any(
            message, EXPLANATION_HINTS
        ):
            return {
                "assistant_message": "Tool mode needs a concrete action. Please specify the operation or switch to knowledge mode.",
                "target": target,
                "actions": [],
                "planner": "clarification",
            }
        return plan


class ToolExecutor:
    def __init__(
        self,
        store: RuntimeStore,
        execute_webgis: Callable[[str, Dict[str, Any], Dict[str, Any]], Dict[str, Any]],
    ):
        self.store = store
        self.execute_webgis = execute_webgis
        self.tool_registry = self._build_registry()

    def assess(
        self,
        target: str,
        actions: List[Dict[str, Any]],
        pinned_state: Optional[Dict[str, Any]] = None,
        assistant_mode: str = "tool",
        project_state: Optional[Dict[str, Any]] = None,
        map_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        permission_context = ToolPermissionContext.from_pinned_state(pinned_state)
        descriptors = []
        highest = "low"
        requires_confirmation = False
        for action in actions:
            descriptor = self._describe_tool(target, action, assistant_mode, project_state or {}, map_context or {})
            descriptor["permission_decision"] = permission_context.decision_for(descriptor["risk_level"], descriptor["name"])
            descriptors.append(descriptor)
            if descriptor["permission_decision"] == "deny" or descriptor["risk_level"] == "blocked":
                highest = "blocked"
            elif descriptor["risk_level"] == "high":
                highest = "high"
                requires_confirmation = True
            elif descriptor["risk_level"] == "medium" and highest == "low":
                highest = "medium"
        return {
            "actions_planned": descriptors,
            "risk_level": highest,
            "requires_confirmation": requires_confirmation,
            "permission_context": permission_context.to_dict(),
        }

    def execute(
        self,
        project_id: str,
        target: str,
        actions: List[Dict[str, Any]],
        map_context: Dict[str, Any],
        allow_high_risk: bool = False,
        pinned_state: Optional[Dict[str, Any]] = None,
        assistant_mode: str = "tool",
        project_state: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        permission_context = ToolPermissionContext.from_pinned_state(pinned_state)
        executed = []
        for action in actions:
            descriptor = self._describe_tool(target, action, assistant_mode, project_state or {}, map_context)
            decision = permission_context.decision_for(descriptor["risk_level"], descriptor["name"])
            if descriptor.get("validation_error"):
                raise ValueError(str(descriptor["validation_error"]))
            if decision == "deny":
                raise ValueError(f"Blocked action: {action['tool_name']}")
            if decision == "ask" and not allow_high_risk:
                raise PermissionError(f"Confirmation required: {action['tool_name']}")
            result = self.execute_webgis(project_id, action, map_context)
            executed.append({"action": action, "result": result, "risk_level": descriptor["risk_level"]})
        return executed

    def _build_registry(self) -> Dict[str, Dict[str, Any]]:
        registry = {
            "set_view": {"target": "webgis", "category": "view", "risk_level": "low", "reversible": True, "requires_confirmation": False, "requires_map_context": False},
            "toggle_layer": {"target": "webgis", "category": "layer", "risk_level": "low", "reversible": True, "requires_confirmation": False, "validator": self._require_layer_id},
            "reorder_layer": {"target": "webgis", "category": "layer", "risk_level": "medium", "reversible": True, "requires_confirmation": False, "validator": self._require_layer_id},
            "style_layer": {"target": "webgis", "category": "layer", "risk_level": "medium", "reversible": True, "requires_confirmation": False, "validator": self._require_layer_id},
            "query_features": {"target": "webgis", "category": "analysis", "risk_level": "low", "reversible": True, "requires_confirmation": False, "validator": self._require_layer_id},
            "draw_annotation": {"target": "webgis", "category": "annotation", "risk_level": "low", "reversible": True, "requires_confirmation": False},
            "measure": {"target": "webgis", "category": "analysis", "risk_level": "low", "reversible": True, "requires_confirmation": False, "requires_map_context": True},
            "apply_template": {"target": "webgis", "category": "template", "risk_level": "medium", "reversible": True, "requires_confirmation": False},
            "export_snapshot": {"target": "webgis", "category": "export", "risk_level": "medium", "reversible": False, "requires_confirmation": False, "validator": self._require_export_path},
            "explain_current_view": {"target": "webgis", "category": "explain", "risk_level": "low", "reversible": True, "requires_confirmation": False, "requires_map_context": True},
            "switch_basemap": {"target": "webgis", "category": "view", "risk_level": "low", "reversible": True, "requires_confirmation": False},
            "search_poi": {"target": "webgis", "category": "search", "risk_level": "low", "reversible": True, "requires_confirmation": False, "requires_map_context": True},
            "toggle_teaching_map": {"target": "webgis", "category": "teaching_map", "risk_level": "low", "reversible": True, "requires_confirmation": False},
            "open_material": {"target": "webgis", "category": "material", "risk_level": "low", "reversible": True, "requires_confirmation": False},
            "generate_image": {"target": "webgis", "category": "paid_generation", "risk_level": "high", "reversible": False, "requires_confirmation": True, "validator": self._require_image_generation_prompt},
            "run_visual_query": {"target": "webgis", "category": "analysis", "risk_level": "medium", "reversible": True, "requires_confirmation": False},
            # 课堂学情/提问工具只属于教学智能体；interaction 模式调用会被
            # visible_in_mode 门控为 blocked（默认列表不含 interaction）。
            "record_observation": {"target": "webgis", "category": "classroom", "risk_level": "medium", "reversible": False, "requires_confirmation": False, "validator": self._require_active_session, "visible_in_mode": ["tool", "hybrid", "knowledge", "teaching", "teaching_action"]},
            "launch_question": {"target": "webgis", "category": "classroom", "risk_level": "medium", "reversible": False, "requires_confirmation": False, "validator": self._require_active_session, "visible_in_mode": ["tool", "hybrid", "knowledge", "teaching", "teaching_action"]},
            # --- 智能交互（interaction）专用操控工具 ---
            "switch_view_mode": {"target": "webgis", "category": "view", "risk_level": "low", "reversible": True, "requires_confirmation": False, "visible_in_mode": ["interaction"], "validator": self._require_view_mode_param},
            "open_panel": {"target": "webgis", "category": "ui", "risk_level": "low", "reversible": True, "requires_confirmation": False, "visible_in_mode": ["interaction"], "validator": self._require_panel_param},
            "focus_layer": {"target": "webgis", "category": "layer", "risk_level": "low", "reversible": True, "requires_confirmation": False, "visible_in_mode": ["interaction"], "validator": self._require_layer_ref},
            "set_layer_opacity": {"target": "webgis", "category": "layer", "risk_level": "low", "reversible": True, "requires_confirmation": False, "visible_in_mode": ["interaction"], "validator": self._require_layer_opacity},
            "enter_lesson_stage": {"target": "webgis", "category": "classroom", "risk_level": "medium", "reversible": True, "requires_confirmation": False, "visible_in_mode": ["interaction"], "validator": self._require_active_session},
            "run_workflow": {"target": "webgis", "category": "analysis", "risk_level": "medium", "reversible": True, "requires_confirmation": False, "visible_in_mode": ["interaction"], "validator": self._require_workflow_template},
            "start_class_session": {"target": "webgis", "category": "classroom", "risk_level": "medium", "reversible": False, "requires_confirmation": False, "visible_in_mode": ["interaction"], "validator": self._require_no_active_session},
            "end_class_session": {"target": "webgis", "category": "classroom", "risk_level": "high", "reversible": False, "requires_confirmation": True, "visible_in_mode": ["interaction"], "validator": self._require_active_session},
        }
        return registry

    def _describe_tool(
        self,
        target: str,
        action: Dict[str, Any],
        assistant_mode: str,
        project_state: Dict[str, Any],
        map_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        tool_name = str(action.get("tool_name") or "")
        metadata = dict(self.tool_registry.get(tool_name) or {})
        if not metadata:
            metadata = {
                "target": target,
                "category": "unknown",
                "risk_level": "blocked",
                "reversible": False,
                "requires_confirmation": True,
            }
        validation_error = ""
        requires_map_context = bool(metadata.get("requires_map_context"))
        if metadata.get("target") not in {target, "auto"}:
            validation_error = f"Tool target mismatch for {tool_name}: expected {metadata.get('target')}, got {target}"
        elif assistant_mode not in metadata.get("visible_in_mode", ["tool", "hybrid", "knowledge", "teaching", "teaching_action"]):
            validation_error = f"Tool {tool_name} is not visible in {assistant_mode} mode"
        elif requires_map_context and not map_context:
            validation_error = f"Tool {tool_name} requires current map context"
        elif callable(metadata.get("validator")):
            validation_error = str(metadata["validator"](action.get("tool_params", {}), project_state, map_context) or "")
        return {
            "name": tool_name,
            "target": metadata["target"],
            "category": metadata["category"],
            "risk_level": "blocked" if validation_error else metadata["risk_level"],
            "reversible": metadata["reversible"],
            "requires_confirmation": metadata["requires_confirmation"],
            "requires_map_context": requires_map_context,
            "tool_params": action.get("tool_params", {}),
            "validation_error": validation_error,
        }

    def _require_layer_id(self, params: Dict[str, Any], project_state: Dict[str, Any], map_context: Dict[str, Any]) -> str:
        if str(params.get("layer_id") or "").strip():
            return ""
        if str(map_context.get("active_layer_id") or "").strip():
            return ""
        return "layer_id is required for this action"

    def _require_export_path(self, params: Dict[str, Any], project_state: Dict[str, Any], map_context: Dict[str, Any]) -> str:
        for key in ("file_path", "path", "output_path"):
            if str(params.get(key) or "").strip():
                return ""
        return "an explicit output path is required for this action"

    def _require_active_session(self, params: Dict[str, Any], project_state: Dict[str, Any], map_context: Dict[str, Any]) -> str:
        teaching_context = map_context.get("teaching_context") if isinstance(map_context.get("teaching_context"), dict) else {}
        session_id = str((teaching_context or {}).get("session_id") or "").strip()
        if not session_id:
            return "该操作需要正在进行的班课，请先在课中面板开始上课"
        session = self.store.get_class_session(session_id)
        if session is None or session.status != "running":
            return "当前班课已结束，课堂工具（发布提问/记录学情）只在进行中的班课可用"
        return ""

    def _require_image_generation_prompt(self, params: Dict[str, Any], project_state: Dict[str, Any], map_context: Dict[str, Any]) -> str:
        del project_state, map_context
        prompt = str(params.get("prompt") or "").strip()
        if not prompt:
            return "图片生成需要明确的 prompt"
        if len(prompt) > 1500:
            return "图片生成 prompt 不能超过 1500 个字符"
        return ""

    def _require_view_mode_param(self, params: Dict[str, Any], project_state: Dict[str, Any], map_context: Dict[str, Any]) -> str:
        del project_state, map_context
        mode = str(params.get("mode") or "").strip().lower()
        if mode not in {"plane", "globe"}:
            return "切换视图需要 mode 取 plane 或 globe"
        return ""

    def _require_panel_param(self, params: Dict[str, Any], project_state: Dict[str, Any], map_context: Dict[str, Any]) -> str:
        del project_state, map_context
        panel = str(params.get("panel") or "").strip().lower()
        if panel not in {"layers", "database", "workflow"}:
            return "open_panel 的 panel 取值需为 layers、database 或 workflow"
        return ""

    def _require_layer_ref(self, params: Dict[str, Any], project_state: Dict[str, Any], map_context: Dict[str, Any]) -> str:
        del project_state
        if str(params.get("layer_id") or "").strip() or str(params.get("layer_name") or "").strip():
            return ""
        if str(map_context.get("active_layer_id") or "").strip():
            return ""
        return "定位图层需要 layer_id、layer_name 或当前激活图层"

    def _require_layer_opacity(self, params: Dict[str, Any], project_state: Dict[str, Any], map_context: Dict[str, Any]) -> str:
        del project_state
        has_ref = (
            str(params.get("layer_id") or "").strip()
            or str(params.get("layer_name") or "").strip()
            or str(map_context.get("active_layer_id") or "").strip()
        )
        if not has_ref:
            return "调整透明度需要 layer_id、layer_name 或当前激活图层"
        try:
            opacity = float(params.get("opacity"))
        except (TypeError, ValueError):
            return "透明度需要 0 到 1 之间的数值"
        if not (0.0 <= opacity <= 1.0):
            return "透明度需要 0 到 1 之间的数值"
        return ""

    def _require_workflow_template(self, params: Dict[str, Any], project_state: Dict[str, Any], map_context: Dict[str, Any]) -> str:
        del project_state, map_context
        template_id = str(params.get("template_id") or "").strip()
        description = str(params.get("description") or "").strip()
        if template_id:
            if template_id not in INTERACTION_ALLOWED_TEMPLATES:
                return f"语音分析暂只支持模板：{ '、'.join(INTERACTION_ALLOWED_TEMPLATES) }"
            return ""
        if not description:
            return "run_workflow 需要 template_id 或分析描述 description"
        return ""

    def _require_no_active_session(self, params: Dict[str, Any], project_state: Dict[str, Any], map_context: Dict[str, Any]) -> str:
        teaching_context = map_context.get("teaching_context") if isinstance(map_context.get("teaching_context"), dict) else {}
        lesson_id = str((teaching_context or {}).get("lesson_id") or "").strip()
        if not lesson_id and not str(params.get("lesson_id") or "").strip() and not str(params.get("lesson_title") or "").strip():
            return "开始上课需要当前课堂绑定的教案（teaching_context.lesson_id）或显式 lesson_id"
        project_id = str(project_state.get("project_id") or "").strip()
        if project_id:
            running = self.store.list_class_sessions(project_id=project_id, status="running")
            if running:
                return "已有一节进行中的班课，请先结束当前课再开始新课"
        return ""


class AssistantSessionEngine:
    def __init__(
        self,
        config: AppConfig,
        store: RuntimeStore,
        llm_planner: LLMPlanner,
        assistant_service: AssistantService,
        execute_webgis: Callable[[str, Dict[str, Any], Dict[str, Any]], Dict[str, Any]],
        vision_service: Any = None,
    ):
        self.config = config
        self.store = store
        self.prompt_registry = PromptRegistry()
        self.router = AssistantRouter()
        self.knowledge = KnowledgeEngine(
            config,
            minimax_client=llm_planner.minimax_client,
            resource_search=None,  # wired later via set_resource_search()
        )
        self.tool_planner = ToolPlanner(llm_planner, assistant_service)
        self.tool_executor = ToolExecutor(store, execute_webgis)
        self.memory = ConversationMemory(store)
        self.vision_service = vision_service
        self.session_stats_provider: Optional[Callable[[str], Dict[str, Any]]] = None

    def set_resource_search(self, resource_search: Any) -> None:
        """Wire the resource search service into the knowledge engine for online search."""
        self.knowledge.resource_search = resource_search

    def set_session_stats_provider(self, provider: Callable[[str], Dict[str, Any]]) -> None:
        """Wire a callable(session_id) -> statistics dict so reflection and
        in-class commentary can quote real classroom records."""
        self.session_stats_provider = provider

    def handle(
        self,
        job_id: str,
        project: ProjectRecord,
        message: str,
        assistant_mode: str,
        conversation_id: str,
        history: Optional[List[Dict[str, Any]]],
        map_context: Optional[Dict[str, Any]],
        target: str,
        input_mode: str,
        stage_callback: Callable[[str, str, str, str], None],
    ) -> Dict[str, Any]:
        normalized_mode = assistant_mode if assistant_mode in {"teaching", "knowledge", "tool", "interaction"} else "teaching"
        # Heavy GIS work moved to /workflow/*; the in-classroom assistant is WebGIS-only.
        normalized_target = "webgis"
        effective_target = "webgis"
        del target  # ignored (kept for API back-compat)
        map_context = map_context or {}

        conversation = self.memory.get_or_create(
            project.project_id,
            normalized_mode,
            conversation_id=conversation_id,
            history=history,
            map_context=map_context,
        )
        attachments = list(map_context.get("image_attachments") or [])
        image_attachment = attachments[0] if attachments and isinstance(attachments[0], dict) else None
        if image_attachment is None and _contains_any(message, IMAGE_FOLLOW_UP_HINTS):
            remembered = conversation.pinned_state.get("last_image_attachment")
            if isinstance(remembered, dict) and remembered.get("path"):
                image_attachment = dict(remembered)
        if image_attachment is not None:
            map_context = {**map_context, "image_attachment": image_attachment}
        self.memory.append(
            conversation.conversation_id,
            "user",
            message,
            normalized_mode,
            metadata={
                "job_id": job_id,
                "image_attachment": {
                    "artifact_id": image_attachment.get("artifact_id", ""),
                    "title": image_attachment.get("title", ""),
                    "public_url": image_attachment.get("public_url", ""),
                }
                if image_attachment
                else {},
            },
        )

        if normalized_mode == "interaction":
            # 智能交互：全程中文阶段反馈，让教师在等待 LLM 规划时也能看到
            # 系统正在做什么（SSE stages → 前端思考指示器/光晕副文案）。
            stage_callback("routing", "running", "正在解析语音指令…", "")
        else:
            stage_callback("routing", "running", "Routing request", "")
        context = self.memory.build_context(conversation)
        route = self.router.route(normalized_mode, message, context["raw_messages"], map_context, {"project_id": project.project_id})
        intent = route["intent"]
        if image_attachment is not None:
            intent = "knowledge" if normalized_mode == "knowledge" else "teaching_explain"
            route = {**route, "intent": intent, "reason": "image attachment requires visual understanding"}
        if intent == "interaction":
            stage_callback("routing", "success", "已识别为系统操控指令", route["reason"])
        else:
            stage_callback("routing", "success", f"Intent: {intent}", route["reason"])

        if intent == "knowledge" or (intent in TEACHING_TASKS and intent != "teaching_action"):
            teaching_task = intent if intent.startswith("teaching") else ""
            return self._handle_knowledge(project, conversation, message, map_context, stage_callback, teaching_task=teaching_task)

        if intent == "interaction":
            stage_callback("planning", "running", "正在理解指令并匹配操作…", "")
        else:
            stage_callback("planning", "running", "Planning GIS actions", "")
        plan = self.tool_planner.plan(message, project, map_context, effective_target, input_mode, intent=intent)
        if intent == "interaction":
            planner_label = str(plan.get("planner") or "unknown")
            if planner_label == "interaction_rule":
                stage_callback("planning", "success", "快速通道命中，无需等待", plan.get("assistant_message", ""))
            else:
                stage_callback("planning", "success", "AI 已完成操作规划", plan.get("assistant_message", ""))
        else:
            stage_callback("planning", "success", f"Planner: {plan.get('planner', 'unknown')}", plan.get("assistant_message", ""))

        actions = list(plan.get("actions") or [])
        assessment = self.tool_executor.assess(
            effective_target,
            actions,
            pinned_state=context.get("pinned_state"),
            assistant_mode=intent,
            project_state={"project_id": project.project_id},
            map_context=map_context,
        )
        prompt_parts = self.prompt_registry.build(intent, map_context, retrieval=None, conversation_context=context)

        if not actions:
            if normalized_mode == "teaching":
                # Teaching mode never surfaces "switch to knowledge mode"; a
                # request without a concrete map action becomes an explanation.
                return self._handle_knowledge(project, conversation, message, map_context, stage_callback, teaching_task="teaching_explain")
            assistant_message = str(plan.get("assistant_message") or "No action was planned.")
            self.memory.append(
                conversation.conversation_id,
                "assistant",
                assistant_message,
                normalized_mode,
                metadata={"intent": intent, "planner": plan.get("planner", "clarification")},
            )
            self.memory.update_task_memory(
                conversation,
                {"last_intent": intent},
                map_context,
                pinned_state_updates={"last_route": route, "last_clarification": assistant_message},
            )
            return {
                "intent": intent,
                "assistant_message": assistant_message,
                "knowledge": None,
                "citations": [],
                "actions_planned": assessment["actions_planned"],
                "actions_executed": [],
                "requires_confirmation": False,
                "confirmation_id": "",
                "planner": plan.get("planner", "clarification"),
                "retrieval_trace": [],
                "conversation_id": conversation.conversation_id,
                "prompt_parts": prompt_parts,
            }

        if assessment["risk_level"] == "blocked":
            blocked_action = next((item for item in assessment["actions_planned"] if item.get("risk_level") == "blocked"), {})
            assistant_message = str(blocked_action.get("validation_error") or f"Action blocked: {blocked_action.get('name') or 'unknown'}")
            self.memory.append(
                conversation.conversation_id,
                "assistant",
                assistant_message,
                normalized_mode,
                metadata={"intent": intent, "planner": "blocked"},
            )
            self.memory.update_task_memory(
                conversation,
                {"last_intent": intent},
                map_context,
                pinned_state_updates={"last_route": route},
            )
            return {
                "intent": intent,
                "assistant_message": assistant_message,
                "knowledge": None,
                "citations": [],
                "actions_planned": assessment["actions_planned"],
                "actions_executed": [],
                "requires_confirmation": False,
                "confirmation_id": "",
                "planner": "blocked",
                "retrieval_trace": [],
                "conversation_id": conversation.conversation_id,
                "prompt_parts": prompt_parts,
                "permission_context": assessment["permission_context"],
            }

        if assessment["requires_confirmation"]:
            previous_confirmation = str((context.get("pinned_state") or {}).get("last_pending_confirmation", {}).get("confirmation_id") or "")
            if previous_confirmation:
                previous = self.store.get_confirmation(previous_confirmation)
                if previous and previous.status == "pending":
                    self.store.resolve_confirmation(previous_confirmation, "orphaned")
            frozen_plan = {
                "target": effective_target,
                "actions": actions,
                "assistant_message": plan.get("assistant_message", ""),
                "intent": intent,
                "message": message,
                "map_context": map_context,
                "planner": plan.get("planner", "unknown"),
                "prompt_fingerprint": prompt_parts["context_fingerprint"],
            }
            plan_fingerprint = _fingerprint(frozen_plan)
            expires_at = _utc_timestamp(minutes_from_now=15)
            stage_callback("confirmation", "running", "Waiting for user confirmation", "")
            confirm_title = "High-risk GIS action"
            confirm_reason = "One or more planned actions are high risk and require confirmation."
            launch_action = next((item for item in actions if str(item.get("tool_name") or "") == "launch_question"), None)
            if launch_action is not None:
                launch_params = launch_action.get("tool_params") or {}
                question_text = str(launch_params.get("text") or launch_params.get("question_id") or "").strip()
                confirm_title = "课堂投屏提问"
                confirm_reason = (
                    f"即将把题目投屏到课堂大屏：{question_text}。发送后开始计时，请确认。"
                    if question_text
                    else "即将把题目投屏到课堂大屏，发送后开始计时，请确认。"
                )
            image_action = next((item for item in actions if str(item.get("tool_name") or "") == "generate_image"), None)
            if image_action is not None:
                image_params = image_action.get("tool_params") or {}
                image_prompt = str(image_params.get("prompt") or "").strip()
                confirm_title = "使用 MiniMax 生成图片"
                confirm_reason = (
                    f"即将使用普通余额 API 生成并保存一张 AI 示意图：{image_prompt[:120]}。此操作会产生 API 费用，请确认。"
                    if image_prompt
                    else "即将使用普通余额 API 生成并保存一张 AI 示意图。此操作会产生 API 费用，请确认。"
                )
            end_session_action = next((item for item in actions if str(item.get("tool_name") or "") == "end_class_session"), None)
            if end_session_action is not None:
                confirm_title = "结束本节课"
                confirm_reason = "即将结束当前进行中的班课并生成课堂小结。结束后课堂工具将不可用，请确认。"
            confirmation = self.store.create_confirmation(
                project.project_id,
                conversation.conversation_id,
                job_id,
                normalized_mode,
                title=confirm_title,
                reason=confirm_reason,
                plan_fingerprint=plan_fingerprint,
                payload={
                    "frozen_plan": frozen_plan,
                    "target": effective_target,
                    "actions": actions,
                    "assistant_message": plan.get("assistant_message", ""),
                    "intent": intent,
                    "map_context": map_context,
                    "message": message,
                    "prompt_parts": prompt_parts,
                    "planner": plan.get("planner", "unknown"),
                    "plan_fingerprint": plan_fingerprint,
                },
                expires_at=expires_at,
            )
            stage_callback("confirmation", "success", "Confirmation created", confirmation.confirmation_id)
            assistant_message = (
                f"{plan.get('assistant_message', '').strip()}\n\n"
                "该操作会产生外部影响，正在等待你确认后执行。"
            ).strip()
            self.memory.append(
                conversation.conversation_id,
                "assistant",
                assistant_message,
                normalized_mode,
                metadata={"intent": intent, "confirmation_id": confirmation.confirmation_id},
            )
            permission_context = ToolPermissionContext.from_pinned_state(context.get("pinned_state"))
            if previous_confirmation:
                permission_context.mark_orphaned(previous_confirmation)
            self.memory.update_task_memory(
                conversation,
                {"last_intent": intent, "pending_confirmation_id": confirmation.confirmation_id},
                map_context,
                pinned_state_updates={
                    "last_route": route,
                    "active_plan_fingerprint": plan_fingerprint,
                    "last_pending_confirmation": {
                        "confirmation_id": confirmation.confirmation_id,
                        "plan_fingerprint": plan_fingerprint,
                        "expires_at": expires_at,
                    },
                    "orphaned_confirmation": permission_context.orphaned_confirmation,
                },
            )
            return {
                "intent": intent,
                "assistant_message": assistant_message,
                "knowledge": None,
                "citations": [],
                "actions_planned": assessment["actions_planned"],
                "actions_executed": [],
                "requires_confirmation": True,
                "confirmation_id": confirmation.confirmation_id,
                "confirmation_expires_at": expires_at,
                "plan_fingerprint": plan_fingerprint,
                "planner": plan.get("planner", "unknown"),
                "retrieval_trace": [],
                "conversation_id": conversation.conversation_id,
                "prompt_parts": prompt_parts,
                "permission_context": permission_context.to_dict(),
            }

        executed = self._execute_actions(
            project.project_id,
            effective_target,
            actions,
            map_context,
            stage_callback,
            pinned_state=context.get("pinned_state"),
            assistant_mode=intent,
        )
        knowledge = None
        citations: List[Dict[str, Any]] = []
        assistant_message = str(plan.get("assistant_message") or "").strip()
        teaching_contract: Optional[Dict[str, str]] = None

        if intent == "hybrid" or normalized_mode == "teaching":
            stage_callback("grounding", "running", "Explaining executed result", "")
            if normalized_mode == "teaching":
                map_context = self._inject_session_digest(map_context, "teaching_action")
                knowledge = self.knowledge.answer(message, map_context=map_context, teaching_task="teaching_action")
                citations = knowledge["citations"]
                grounding_text = self.knowledge.render_public_answer(knowledge, include_teaching_points=True)
            else:
                knowledge = self.knowledge.answer(message, map_context=map_context)
                citations = knowledge["citations"]
                grounding_text = self.knowledge.render_public_answer(knowledge, include_teaching_points=False)
            assistant_message = "\n\n".join(part for part in [assistant_message, grounding_text] if part).strip()
            stage_callback("grounding", "success", "Explanation completed", "")

        self.memory.append(
            conversation.conversation_id,
            "assistant",
            assistant_message,
            normalized_mode,
            metadata={"intent": intent, "planner": plan.get("planner", "unknown")},
        )
        self.memory.update_task_memory(
            conversation,
            {"last_intent": intent, "pending_confirmation_id": ""},
            map_context,
            pinned_state_updates={
                "last_route": route,
                "active_plan_fingerprint": "",
                "last_pending_confirmation": {},
                "last_execution": {
                    "target": effective_target,
                    "actions": actions,
                    "intent": intent,
                },
            },
        )
        return {
            "intent": intent,
            "assistant_message": assistant_message,
            "knowledge": knowledge,
            "citations": citations,
            "actions_planned": assessment["actions_planned"],
            "actions_executed": executed,
            "requires_confirmation": False,
            "confirmation_id": "",
            "planner": plan.get("planner", "unknown"),
            "retrieval_trace": knowledge["retrieval_trace"] if knowledge else [],
            "conversation_id": conversation.conversation_id,
            "prompt_parts": prompt_parts,
            "teaching_contract": teaching_contract,
            "permission_context": assessment["permission_context"],
        }

    def execute_confirmation(
        self,
        confirmation_id: str,
        stage_callback: Callable[[str, str, str, str], None],
    ) -> Dict[str, Any]:
        confirmation = self.store.get_confirmation(confirmation_id)
        if confirmation is None:
            raise KeyError(f"Unknown confirmation: {confirmation_id}")
        if confirmation.status != "pending":
            raise ValueError(f"Confirmation is already {confirmation.status}")
        payload = confirmation.payload or {}
        conversation = self.store.get_conversation(confirmation.conversation_id)
        if confirmation.expires_at:
            expires_at = _parse_timestamp(confirmation.expires_at)
            if expires_at and expires_at <= datetime.now(timezone.utc):
                self.store.resolve_confirmation(confirmation_id, "expired")
                if conversation:
                    self.memory.update_task_memory(
                        conversation,
                        {"pending_confirmation_id": ""},
                        conversation.last_map_grounding,
                        pinned_state_updates={"last_pending_confirmation": {}, "active_plan_fingerprint": ""},
                    )
                raise ValueError("Confirmation has expired")
        frozen_plan = payload.get("frozen_plan") or {}
        expected_fingerprint = str(payload.get("plan_fingerprint") or confirmation.plan_fingerprint or "")
        actual_fingerprint = _fingerprint(frozen_plan or payload)
        if expected_fingerprint and actual_fingerprint != expected_fingerprint:
            self.store.resolve_confirmation(confirmation_id, "invalidated")
            raise ValueError("Confirmation plan fingerprint mismatch")
        if conversation:
            current_pending = conversation.pinned_state.get("last_pending_confirmation", {})
            current_confirmation_id = str(current_pending.get("confirmation_id") or "")
            if current_confirmation_id and current_confirmation_id != confirmation_id:
                self.store.resolve_confirmation(confirmation_id, "orphaned")
                raise ValueError("Confirmation is no longer the active plan for this conversation")
        actions = list((frozen_plan or payload).get("actions") or payload.get("actions") or [])
        target = str((frozen_plan or payload).get("target") or payload.get("target") or "webgis")
        map_context = dict((frozen_plan or payload).get("map_context") or payload.get("map_context") or {})
        confirmed_plan_intent = str((frozen_plan or payload).get("intent") or payload.get("intent") or "tool")
        revalidation = self.tool_executor.assess(
            target,
            actions,
            pinned_state=conversation.pinned_state if conversation else {},
            assistant_mode=confirmed_plan_intent,
            project_state={"project_id": confirmation.project_id},
            map_context=map_context,
        )
        if revalidation["risk_level"] == "blocked":
            self.store.resolve_confirmation(confirmation_id, "invalidated")
            if conversation:
                self.memory.update_task_memory(
                    conversation,
                    {"pending_confirmation_id": ""},
                    map_context,
                    pinned_state_updates={"last_pending_confirmation": {}, "active_plan_fingerprint": ""},
                )
            blocked = next((item for item in revalidation["actions_planned"] if item.get("risk_level") == "blocked"), {})
            raise ValueError(str(blocked.get("validation_error") or "计划已失效，无法执行"))
        self.store.resolve_confirmation(confirmation_id, "approved")
        stage_callback("execution", "running", "Executing confirmed action", "")
        executed = self.tool_executor.execute(
            confirmation.project_id,
            target,
            actions,
            map_context=map_context,
            allow_high_risk=True,
            pinned_state=conversation.pinned_state if conversation else {},
            assistant_mode=str((frozen_plan or payload).get("intent") or payload.get("intent") or "tool"),
            project_state={"project_id": confirmation.project_id},
        )
        stage_callback("execution", "success", "Confirmed action executed", "")

        knowledge = None
        citations: List[Dict[str, Any]] = []
        assistant_message = "Confirmed action executed successfully."
        teaching_contract: Optional[Dict[str, str]] = None
        confirmed_intent = str((frozen_plan or payload).get("intent") or payload.get("intent") or "tool")
        if confirmed_intent == "hybrid" or confirmed_intent.startswith("teaching"):
            stage_callback("grounding", "running", "Explaining confirmed result", "")
            confirmed_message = str((frozen_plan or payload).get("message") or "")
            if confirmed_intent.startswith("teaching"):
                map_context = self._inject_session_digest(map_context, "teaching_action")
                knowledge = self.knowledge.answer(confirmed_message, map_context=map_context, teaching_task="teaching_action")
                citations = list(knowledge.get("citations") or [])
                grounding_text = self.knowledge.render_public_answer(knowledge, include_teaching_points=True)
            else:
                knowledge = self.knowledge.answer(confirmed_message, map_context=map_context)
                citations = list(knowledge.get("citations") or [])
                grounding_text = self.knowledge.render_public_answer(knowledge, include_teaching_points=False)
            assistant_message = "\n\n".join(
                [
                    "Confirmed action executed successfully.",
                    grounding_text,
                ]
            ).strip()
            stage_callback("grounding", "success", "Confirmed explanation completed", "")
        if conversation:
            self.memory.append(
                conversation.conversation_id,
                "assistant",
                assistant_message,
                confirmation.assistant_mode,
                metadata={"confirmation_id": confirmation_id, "executed": True},
            )
            self.memory.update_task_memory(
                conversation,
                {"pending_confirmation_id": ""},
                map_context,
                pinned_state_updates={
                    "last_pending_confirmation": {},
                    "active_plan_fingerprint": "",
                    "last_execution": {"target": target, "actions": actions, "confirmed": True},
                },
            )
        return {
            "confirmation_id": confirmation_id,
            "project_id": confirmation.project_id,
            "conversation_id": confirmation.conversation_id,
            "assistant_message": assistant_message,
            "actions_executed": executed,
            "actions_planned": self.tool_executor.assess(
                target,
                actions,
                pinned_state=conversation.pinned_state if conversation else {},
                assistant_mode=confirmed_intent,
                project_state={"project_id": confirmation.project_id},
                map_context=map_context,
            )["actions_planned"],
            "requires_confirmation": False,
            "intent": confirmed_intent,
            "citations": citations,
            "knowledge": knowledge,
            "planner": "confirmation",
            "teaching_contract": teaching_contract,
            "retrieval_trace": knowledge["retrieval_trace"] if knowledge else [],
        }

    def reject_confirmation(
        self,
        confirmation_id: str,
    ) -> Dict[str, Any]:
        confirmation = self.store.get_confirmation(confirmation_id)
        if confirmation is None:
            raise KeyError(f"Unknown confirmation: {confirmation_id}")
        if confirmation.status != "pending":
            raise ValueError(f"Confirmation is already {confirmation.status}")
        payload = confirmation.payload or {}
        frozen_plan = payload.get("frozen_plan") or {}
        actions = list((frozen_plan or payload).get("actions") or payload.get("actions") or [])
        target = str((frozen_plan or payload).get("target") or payload.get("target") or "webgis")
        self.store.resolve_confirmation(confirmation_id, "rejected")
        conversation = self.store.get_conversation(confirmation.conversation_id)
        permission_context = ToolPermissionContext.from_pinned_state(conversation.pinned_state if conversation else {})
        for action in actions:
            permission_context.remember_denial(str(action.get("tool_name") or ""), "user_rejected_confirmation")
        assistant_message = "The high-risk plan was rejected. I will not run these actions unless you ask again."
        if conversation:
            self.memory.append(
                conversation.conversation_id,
                "assistant",
                assistant_message,
                confirmation.assistant_mode,
                metadata={"confirmation_id": confirmation_id, "executed": False, "decision": "reject"},
            )
            self.memory.update_task_memory(
                conversation,
                {"pending_confirmation_id": ""},
                conversation.last_map_grounding,
                pinned_state_updates={
                    "last_pending_confirmation": {},
                    "active_plan_fingerprint": "",
                    "denials": permission_context.denials,
                    "rejected_tools": permission_context.rejected_tools,
                },
            )
        return {
            "confirmation_id": confirmation_id,
            "project_id": confirmation.project_id,
            "conversation_id": confirmation.conversation_id,
            "assistant_message": assistant_message,
            "actions_executed": [],
            "actions_planned": self.tool_executor.assess(
                target,
                actions,
                pinned_state=conversation.pinned_state if conversation else {},
                assistant_mode=str((frozen_plan or payload).get("intent") or payload.get("intent") or "tool"),
                project_state={"project_id": confirmation.project_id},
                map_context=dict((frozen_plan or payload).get("map_context") or payload.get("map_context") or {}),
            )["actions_planned"],
            "requires_confirmation": False,
            "intent": str((frozen_plan or payload).get("intent") or payload.get("intent") or "tool"),
            "citations": [],
            "knowledge": None,
            "planner": "confirmation_rejected",
            "retrieval_trace": [],
            "permission_context": permission_context.to_dict(),
        }

    def _enrich_image_attachment_with_vision(
        self,
        message: str,
        map_context: Dict[str, Any],
        stage_callback: Callable[[str, str, str, str], None],
    ) -> Dict[str, Any]:
        attachment = map_context.get("image_attachment")
        if not isinstance(attachment, dict) or not attachment.get("path"):
            return map_context
        if self.vision_service is None:
            return {**map_context, "vision_reason": "图片识别服务暂时不可用，请稍后重试。"}

        stage_callback("grounding", "running", "正在识别图片内容", "")
        try:
            result = self.vision_service.understand_image(
                image_path=str(attachment.get("path") or ""),
                question=message,
            )
        except Exception as exc:  # pragma: no cover - defensive runtime branch
            result = {"used_vision": False, "reason": f"图片识别失败：{exc}"}

        enriched = {**map_context, "vision_result": result}
        if result.get("used_vision") and str(result.get("summary") or "").strip():
            summary = str(result.get("summary") or "").strip()
            stage_callback("grounding", "success", "图片识别完成", summary[:180])
            enriched.update(
                {
                    "vision_used": True,
                    "vision_summary": summary,
                    "vision_provider": result.get("provider", ""),
                    "vision_snapshot_path": result.get("snapshot_path", ""),
                }
            )
            return enriched

        reason = str(result.get("reason") or "图片识别服务没有返回可用结果，请稍后重试。")
        stage_callback("grounding", "success", "图片识别暂不可用", reason)
        enriched.update(
            {
                "vision_used": False,
                "vision_reason": reason,
                "vision_snapshot_path": result.get("snapshot_path", ""),
            }
        )
        return enriched

    def _enrich_map_reading_with_vision(
        self,
        project: ProjectRecord,
        message: str,
        map_context: Dict[str, Any],
        stage_callback: Callable[[str, str, str, str], None],
    ) -> Dict[str, Any]:
        if self.knowledge._classify(message) != "map_reading":
            return map_context
        screen_snapshot = map_context.get("screen_snapshot") if isinstance(map_context.get("screen_snapshot"), dict) else {}
        if not screen_snapshot:
            return map_context
        if self.vision_service is None:
            return {**map_context, "vision_reason": "后端未挂载地图视觉读图服务。"}

        stage_callback("grounding", "running", "正在读取当前地图截图", "")
        try:
            vision_result = self.vision_service.understand_map(
                project_id=project.project_id,
                project=project,
                map_context=map_context,
                focus=message,
                screen_snapshot=screen_snapshot,
            )
        except Exception as exc:  # pragma: no cover - defensive runtime branch
            reason = f"地图图片识别服务暂时不可用：{exc}"
            stage_callback("grounding", "success", "截图识别暂不可用", reason)
            return {**map_context, "vision_reason": reason}

        enriched = {**map_context, "vision_result": vision_result}
        if vision_result.get("used_vision") and vision_result.get("summary"):
            summary = str(vision_result.get("summary") or "").strip()
            stage_callback("grounding", "success", "截图读图完成", summary[:180])
            enriched.update(
                {
                    "vision_used": True,
                    "vision_summary": summary,
                    "vision_provider": vision_result.get("provider", ""),
                    "vision_snapshot_path": vision_result.get("snapshot_path", ""),
                }
            )
            return enriched

        reason = str(vision_result.get("reason") or "地图图片识别服务暂时不可用，请稍后重试。")
        stage_callback("grounding", "success", "截图识别暂不可用", reason)
        enriched.update(
            {
                "vision_used": False,
                "vision_reason": reason,
                "vision_snapshot_path": vision_result.get("snapshot_path", ""),
            }
        )
        return enriched

    def _inject_session_digest(self, map_context: Dict[str, Any], teaching_task: str) -> Dict[str, Any]:
        """Attach a compact digest of the live class session so answers can
        quote real tallies, misconceptions and stage timings.

        Reflection (or any post-class message) gets the full statistics digest;
        in-class messages get a much smaller brief (latest question tally and
        observation counts). Without a session handle the context is returned
        unchanged, preserving the existing "no records, say so" behaviour.
        """
        if self.session_stats_provider is None:
            return map_context
        teaching_context = map_context.get("teaching_context") if isinstance(map_context.get("teaching_context"), dict) else {}
        session_id = str((teaching_context or {}).get("session_id") or "").strip()
        phase = str((teaching_context or {}).get("phase") or "")
        if not session_id:
            return map_context
        wants_full = teaching_task == "teaching_reflect" or phase == "post_class"
        if not wants_full and phase != "in_class":
            return map_context
        try:
            statistics = self.session_stats_provider(session_id)
        except Exception:
            return map_context
        if not isinstance(statistics, dict):
            return map_context
        if wants_full:
            question_rows = []
            for item in list(statistics.get("questions") or []):
                if not isinstance(item, dict):
                    continue
                question_rows.append(
                    {
                        "text": str(item.get("text") or "")[:60],
                        "type": item.get("type"),
                        "stage_id": item.get("stage_id"),
                        "collection_mode": item.get("collection_mode"),
                        "response_count": item.get("response_count"),
                        "correct_rate": item.get("correct_rate"),
                        "option_counts": item.get("option_counts"),
                    }
                )
            stage_rows = [
                {
                    "stage_id": item.get("stage_id"),
                    "title": item.get("title"),
                    "planned_minutes": item.get("planned_minutes"),
                    "actual_minutes": item.get("actual_minutes"),
                }
                for item in list(statistics.get("stages") or [])
                if isinstance(item, dict)
            ]
            # Small, high-signal fields first so a trailing truncation can only
            # ever drop the bulky per-question/per-stage rows.
            digest = {
                "lesson_title": statistics.get("lesson_title"),
                "duration_minutes": statistics.get("duration_minutes"),
                "participant_count": statistics.get("participant_count"),
                "response_data_collected": bool(statistics.get("response_data_collected")),
                "observations": statistics.get("observations"),
                "assistant_exchange_count": statistics.get("assistant_exchange_count"),
                "snapshot_count": statistics.get("snapshot_count"),
                "questions": question_rows,
                "stages": stage_rows,
            }
            payload = json.dumps(digest, ensure_ascii=False, default=str)
            return {**map_context, "session_digest": payload[:4000]}
        questions = list(statistics.get("questions") or [])
        brief = {
            "participant_count": statistics.get("participant_count"),
            "last_question": questions[-1] if questions else None,
            "observations": statistics.get("observations"),
        }
        payload = json.dumps(brief, ensure_ascii=False, default=str)
        return {**map_context, "session_digest": payload[:600]}

    def _handle_knowledge(
        self,
        project: ProjectRecord,
        conversation: ConversationRecord,
        message: str,
        map_context: Dict[str, Any],
        stage_callback: Callable[[str, str, str, str], None],
        teaching_task: str = "",
    ) -> Dict[str, Any]:
        map_context = self._enrich_image_attachment_with_vision(message, map_context, stage_callback)
        if not map_context.get("image_attachment"):
            map_context = self._enrich_map_reading_with_vision(project, message, map_context, stage_callback)
        map_context = self._inject_session_digest(map_context, teaching_task)
        llm_available = self.knowledge.minimax_client is not None and self.config.minimax_enabled()
        if (map_context.get("image_attachment") or map_context.get("screen_snapshot")) and not map_context.get("vision_summary"):
            reason = str(map_context.get("vision_reason") or "图片识别服务暂时不可用，请稍后重试。")
            knowledge = {
                "direct_answer": reason,
                "mechanism_explanation": "",
                "map_grounding": "",
                "teaching_points": [],
                "citations": [],
                "confidence": 0.0,
                "answer_type": "map_reading",
                "retrieval_trace": [{"source": "map_vision", "status": "error", "reason": reason}],
                "presentation": {"show_mechanism": False, "show_map_grounding": False, "show_teaching_points": False},
                "llm_used": False,
                "retrieval_mode": "none",
            }
        else:
            knowledge = self.knowledge.answer(message, map_context=map_context, teaching_task=teaching_task)
        retrieval_mode = str(knowledge.get("retrieval_mode") or "none")
        stage_label = {
            "local": "正在查找项目知识库",
            "web": "正在核对在线资料",
            "local_web": "正在结合知识库与在线资料",
        }.get(retrieval_mode, "正在组织回答")
        stage_callback("retrieval", "running", stage_label, "")
        if teaching_task in {"teaching_question", "teaching_reflect"}:
            knowledge["presentation"] = {
                **dict(knowledge.get("presentation") or {}),
                "teaching_points_title": "课堂教学要点",
            }
        llm_used = knowledge.get("llm_used", False)
        source_label = "AI 回答" if llm_used else "本地知识库"
        stage_callback("retrieval", "success", f"{source_label} · {knowledge['answer_type']}", "")
        stage_callback("grounding", "running", "Composing grounded answer", "")
        assistant_message = self.knowledge.render_public_answer(
            knowledge,
            include_teaching_points=teaching_task in {"teaching_question", "teaching_reflect"},
        )
        teaching_contract: Optional[Dict[str, str]] = None
        stage_callback("grounding", "success", "Knowledge answer completed", "")
        result_intent = teaching_task or "knowledge"
        self.memory.append(
            conversation.conversation_id,
            "assistant",
            assistant_message,
            conversation.assistant_mode,
            metadata={"intent": result_intent, "answer_type": knowledge["answer_type"], "llm_used": llm_used},
        )
        self.memory.update_task_memory(
            conversation,
            {"last_intent": result_intent},
            map_context,
            pinned_state_updates={
                "last_answer_type": knowledge["answer_type"],
                **(
                    {"last_image_attachment": dict(map_context.get("image_attachment") or {})}
                    if map_context.get("image_attachment")
                    else {}
                ),
            },
        )
        planner_label = "knowledge_llm" if llm_used else "knowledge_engine"
        return {
            "intent": result_intent,
            "assistant_message": assistant_message,
            "teaching_contract": teaching_contract,
            "knowledge": knowledge,
            "citations": knowledge["citations"],
            "actions_planned": [],
            "actions_executed": [],
            "requires_confirmation": False,
            "confirmation_id": "",
            "planner": planner_label,
            "retrieval_trace": knowledge["retrieval_trace"],
            "conversation_id": conversation.conversation_id,
            "prompt_parts": self.prompt_registry.build(
                result_intent,
                map_context,
                retrieval=knowledge["citations"],
                conversation_context=self.memory.build_context(conversation),
            ),
        }

    def _execute_actions(
        self,
        project_id: str,
        target: str,
        actions: List[Dict[str, Any]],
        map_context: Dict[str, Any],
        stage_callback: Callable[[str, str, str, str], None],
        pinned_state: Optional[Dict[str, Any]] = None,
        assistant_mode: str = "tool",
    ) -> List[Dict[str, Any]]:
        stage_callback("execution", "running", "Executing planned actions", "")
        executed = self.tool_executor.execute(
            project_id,
            target,
            actions,
            map_context,
            pinned_state=pinned_state,
            assistant_mode=assistant_mode,
            project_state={"project_id": project_id},
        )
        stage_callback("execution", "success", f"Executed {len(executed)} action(s)", "")
        return executed
