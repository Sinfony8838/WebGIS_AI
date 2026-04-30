from __future__ import annotations

import hashlib
import json
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
from .qgis_bridge import QGIS_ALLOWED_TOOLS


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
    "apply",
    "switch",
    "hide",
    "show",
    "export",
    "zoom",
    "load",
)

EXPLANATION_HINTS = ("解释", "讲解", "分析", "为什么", "说明", "读图", "原因", "explain", "analysis", "why")
TIME_SENSITIVE_HINTS = ("最新", "目前", "当前", "今天", "近年", "recent", "latest", "today")


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
        if tool_name and tool_name in self.rejected_tools:
            return "deny"
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
            "knowledge_mode": "Answer geography questions with authoritative citations and concise teaching points."
            if mode == "knowledge"
            else "",
            "tool_mode": "Plan and execute only safe, validated GIS actions."
            if mode == "tool"
            else "",
            "hybrid_mode": "Execute approved GIS actions first, then explain the spatial meaning."
            if mode == "hybrid"
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


class KnowledgeEngine:
    def __init__(self, config: AppConfig):
        self.config = config
        self.knowledge_units = self._load_units()

    def answer(self, question: str, map_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        map_context = map_context or {}
        answer_type = self._classify(question)
        if answer_type in {"assistant_identity", "assistant_model", "assistant_capability"}:
            return self._meta_answer(answer_type)
        entry = self._match_entry(question)
        citations = list(entry.get("citations", [])) if entry else []
        retrieval_trace = []
        if citations:
            retrieval_trace.extend(self._score_sources(citations, source_type="local_kb", timely=answer_type == "timely_fact"))
        else:
            citations = self._default_citations(answer_type)
            retrieval_trace.extend(self._score_sources(citations, source_type="authority_fallback", timely=answer_type == "timely_fact"))

        direct_answer = (
            entry.get("canonical_answer")
            if entry
            else "这个问题属于地理相关范围，但本地知识库里还没有完全对应的现成条目。"
            "我可以先按地理学的一般分析框架给出解释。"
        )
        if answer_type == "timely_fact":
            direct_answer = (
                "这个问题具有时效性。系统应先核对权威实时来源，再给出最终结论。"
                "下面列出优先参考的权威来源。"
            )

        mechanism_explanation = self._mechanism_text(question, entry, answer_type)
        map_grounding = self._map_grounding(map_context)
        teaching_points = list(entry.get("teaching_points", [])) if entry else self._default_teaching_points(answer_type)
        confidence = 0.92 if entry else (0.45 if answer_type == "timely_fact" else 0.68)
        return {
            "direct_answer": direct_answer,
            "mechanism_explanation": mechanism_explanation,
            "map_grounding": map_grounding,
            "teaching_points": teaching_points,
            "citations": citations,
            "confidence": confidence,
            "answer_type": answer_type,
            "retrieval_trace": retrieval_trace,
            "presentation": self._presentation_policy(answer_type),
        }

    def _meta_answer(self, answer_type: str) -> Dict[str, Any]:
        llm_status = self.config.llm_status()
        provider = str(llm_status.get("provider") or "unknown")
        model = str(llm_status.get("model") or "unknown")
        configured = bool(llm_status.get("configured"))

        if answer_type == "assistant_identity":
            return {
                "direct_answer": "我是本系统里的“超级地理助手”，负责地理知识问答，以及 WebGIS / QGIS 场景下的操作辅助。",
                "mechanism_explanation": "",
                "map_grounding": "",
                "teaching_points": [
                    "我可以回答地理概念、区域地理、地图判读和 GIS 方法问题。",
                    "我也可以协助执行课堂地图操作、图层控制和 QGIS 工具操作。",
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
            "show_map_grounding": True,
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
        if _contains_any(lowered, TIME_SENSITIVE_HINTS):
            return "timely_fact"
        if _contains_any(lowered, ("遥感", "gis", "rs", "空间分析", "buffer", "overlay")):
            return "gis_method"
        if _contains_any(lowered, ("读图", "判读", "图上", "视图", "地图")):
            return "map_reading"
        if _contains_any(lowered, ("地区", "区域", "沿海", "中国", "亚洲")):
            return "regional_geography"
        return "geo_concept"

    def _match_entry(self, question: str) -> Optional[Dict[str, Any]]:
        lowered = (question or "").lower()
        for item in self.knowledge_units:
            haystack = " ".join([item.get("title", ""), *item.get("tags", [])]).lower()
            if any(tag.lower() in lowered for tag in item.get("tags", [])) or item.get("title", "").lower() in lowered:
                return item
            if haystack and any(token in haystack for token in lowered.split()):
                return item
        return None

    def _default_citations(self, answer_type: str) -> List[Dict[str, str]]:
        if answer_type == "timely_fact":
            return [
                {"title": "World Bank Data", "url": "https://data.worldbank.org/"},
                {"title": "UN Data", "url": "https://data.un.org/"},
            ]
        return [
            {"title": "USGS", "url": "https://www.usgs.gov/"},
            {"title": "NOAA", "url": "https://www.noaa.gov/"},
        ]

    def _mechanism_text(self, question: str, entry: Optional[Dict[str, Any]], answer_type: str) -> str:
        if entry:
            return " ".join(entry.get("teaching_points", [])[:2]).strip()
        if answer_type == "gis_method":
            return "GIS 方法类问题通常要先明确分析对象、空间规则和解释目标。"
        if answer_type == "map_reading":
            return "地图判读不能只描述形状，还要把符号、位置、尺度和区域联系串起来。"
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
                "先看位置与分布。",
                "再解释格局、趋势和原因。",
                "最后回扣课堂目标。",
            ]
        return [
            "先概括空间现象或核心概念。",
            "再解释主要影响因素。",
            "最后收束到课堂结论。",
        ]

    def _map_grounding(self, map_context: Dict[str, Any]) -> str:
        visible_layers = map_context.get("visible_layers") or []
        if not visible_layers:
            return "当前回答没有必须依赖的地图画面依据。"
        layer_names = ", ".join(str(item.get("name") or item.get("layer_id") or "") for item in visible_layers[:4] if item)
        zoom = map_context.get("zoom")
        return f"可结合当前地图视图理解：缩放级别 {zoom}，可见图层包括 {layer_names}。"


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
    ) -> Dict[str, Any]:
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
        execute_qgis: Callable[[Dict[str, Any]], Dict[str, Any]],
    ):
        self.store = store
        self.execute_webgis = execute_webgis
        self.execute_qgis = execute_qgis
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
            if target == "qgis":
                result = self.execute_qgis(action)
            else:
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
        }
        for tool_name in QGIS_ALLOWED_TOOLS:
            registry.setdefault(
                tool_name,
                {
                    "target": "qgis",
                    "category": "qgis",
                    "risk_level": "low",
                    "reversible": True,
                    "requires_confirmation": False,
                    "visible_in_mode": ["tool", "hybrid"],
                },
            )
        for tool_name in ("export_map", "export_layer_to_file", "create_heatmap", "create_flow_arrows", "run_algorithm", "add_layer_from_path"):
            if tool_name in registry:
                registry[tool_name]["risk_level"] = "high"
                registry[tool_name]["reversible"] = False
                registry[tool_name]["requires_confirmation"] = True
                registry[tool_name]["validator"] = self._require_export_path if "export" in tool_name or "path" in tool_name else None
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
        elif assistant_mode not in metadata.get("visible_in_mode", ["tool", "hybrid", "knowledge"]):
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


class AssistantSessionEngine:
    def __init__(
        self,
        config: AppConfig,
        store: RuntimeStore,
        llm_planner: LLMPlanner,
        assistant_service: AssistantService,
        execute_webgis: Callable[[str, Dict[str, Any], Dict[str, Any]], Dict[str, Any]],
        execute_qgis: Callable[[Dict[str, Any]], Dict[str, Any]],
    ):
        self.config = config
        self.store = store
        self.prompt_registry = PromptRegistry()
        self.router = AssistantRouter()
        self.knowledge = KnowledgeEngine(config)
        self.tool_planner = ToolPlanner(llm_planner, assistant_service)
        self.tool_executor = ToolExecutor(store, execute_webgis, execute_qgis)
        self.memory = ConversationMemory(store)

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
        normalized_mode = assistant_mode if assistant_mode in {"knowledge", "tool"} else "tool"
        normalized_target = target if target in {"webgis", "qgis", "auto"} else "webgis"
        effective_target = "webgis" if normalized_target == "auto" else normalized_target
        map_context = map_context or {}

        conversation = self.memory.get_or_create(
            project.project_id,
            normalized_mode,
            conversation_id=conversation_id,
            history=history,
            map_context=map_context,
        )
        self.memory.append(conversation.conversation_id, "user", message, normalized_mode, metadata={"job_id": job_id})

        stage_callback("routing", "running", "Routing request", "")
        context = self.memory.build_context(conversation)
        route = self.router.route(normalized_mode, message, context["raw_messages"], map_context, {"project_id": project.project_id})
        intent = route["intent"]
        stage_callback("routing", "success", f"Intent: {intent}", route["reason"])

        if intent == "knowledge":
            return self._handle_knowledge(conversation, message, map_context, stage_callback)

        stage_callback("planning", "running", "Planning GIS actions", "")
        plan = self.tool_planner.plan(message, project, map_context, effective_target, input_mode)
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
            confirmation = self.store.create_confirmation(
                project.project_id,
                conversation.conversation_id,
                job_id,
                normalized_mode,
                title="High-risk GIS action",
                reason="One or more planned actions are high risk and require confirmation.",
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
                "The planned action is high risk and awaits confirmation before execution."
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

        if intent == "hybrid":
            stage_callback("grounding", "running", "Explaining executed result", "")
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
        if str((frozen_plan or payload).get("intent") or payload.get("intent") or "tool") == "hybrid":
            stage_callback("grounding", "running", "Explaining confirmed result", "")
            knowledge = self.knowledge.answer(str((frozen_plan or payload).get("message") or ""), map_context=map_context)
            citations = list(knowledge.get("citations") or [])
            assistant_message = "\n\n".join(
                [
                    "Confirmed action executed successfully.",
                    self.knowledge.render_public_answer(knowledge, include_teaching_points=False),
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
                assistant_mode=str((frozen_plan or payload).get("intent") or payload.get("intent") or "tool"),
                project_state={"project_id": confirmation.project_id},
                map_context=map_context,
            )["actions_planned"],
            "requires_confirmation": False,
            "intent": str((frozen_plan or payload).get("intent") or payload.get("intent") or "tool"),
            "citations": citations,
            "knowledge": knowledge,
            "planner": "confirmation",
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

    def _handle_knowledge(
        self,
        conversation: ConversationRecord,
        message: str,
        map_context: Dict[str, Any],
        stage_callback: Callable[[str, str, str, str], None],
    ) -> Dict[str, Any]:
        stage_callback("retrieval", "running", "Retrieving authoritative knowledge", "")
        knowledge = self.knowledge.answer(message, map_context=map_context)
        stage_callback("retrieval", "success", f"Answer type: {knowledge['answer_type']}", "")
        stage_callback("grounding", "running", "Composing grounded answer", "")
        assistant_message = self.knowledge.render_public_answer(knowledge, include_teaching_points=True)
        stage_callback("grounding", "success", "Knowledge answer completed", "")
        self.memory.append(
            conversation.conversation_id,
            "assistant",
            assistant_message,
            conversation.assistant_mode,
            metadata={"intent": "knowledge", "answer_type": knowledge["answer_type"]},
        )
        self.memory.update_task_memory(
            conversation,
            {"last_intent": "knowledge"},
            map_context,
            pinned_state_updates={"last_answer_type": knowledge["answer_type"]},
        )
        return {
            "intent": "knowledge",
            "assistant_message": assistant_message,
            "knowledge": knowledge,
            "citations": knowledge["citations"],
            "actions_planned": [],
            "actions_executed": [],
            "requires_confirmation": False,
            "confirmation_id": "",
            "planner": "knowledge_engine",
            "retrieval_trace": knowledge["retrieval_trace"],
            "conversation_id": conversation.conversation_id,
            "prompt_parts": self.prompt_registry.build(
                "knowledge",
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
