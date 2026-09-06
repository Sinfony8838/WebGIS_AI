"""LLM planner for the in-classroom WebGIS assistant.

After the migration to the backend GIS workflow, the planner is
WebGIS-only: it produces ``{tool_name, tool_params}`` actions that the
existing :class:`AssistantService` knows how to execute on the OpenLayers
map (basemap switching, layer toggles, view changes, POI search, teaching
maps, etc.). Heavy GIS work is now handled by the workflow pipeline
(``/workflow/*``), not by this module.

Paths:

* **Voice** input — handed to ``AssistantService.plan_voice_actions``
  (deterministic, no LLM).
* **Text** input — first tried by ``AssistantService.plan_actions``;
  if any of the rule-based actions are recognised the rule plan wins
  ("rule_preflight"). Otherwise the message is sent to MiniMax which
  returns a JSON plan; on any failure we fall back to the rule planner
  again ("rule_fallback").
* **interaction** mode (智能交互, voice-driven system control) — the
  deterministic ``plan_interaction_actions`` fast path answers
  high-frequency commands in milliseconds ("interaction_rule"); anything
  unmatched escalates to MiniMax with an interaction-filtered tool table
  ("interaction_minimax") and a speech-tolerant prompt. Legacy teaching /
  tool / knowledge modes are unaffected.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional

from ..models import ProjectRecord
from .assistant import ASSISTANT_TOOL_SCHEMA, AssistantService
from .minimax_client import MiniMaxClient
from .workflow_templates import INTERACTION_ALLOWED_TEMPLATES, list_templates


WEBGIS_ALLOWED_TOOLS = {item["name"] for item in ASSISTANT_TOOL_SCHEMA}
MAX_LLM_ACTIONS = 12
# Voice turns must feel instant in a live classroom; a slow plan is worse
# than no plan (the clarification fallback answers immediately).
VOICE_LLM_TIMEOUT_SECONDS = 12.0


def _tools_for_mode(assistant_mode: str) -> List[Dict[str, Any]]:
    """Prompt-layer tool visibility: specs whose ``modes`` include the mode.

    Specs without a ``modes`` key stay visible everywhere (backward
    compatibility for hand-written specs).
    """
    return [
        item
        for item in ASSISTANT_TOOL_SCHEMA
        if assistant_mode in item.get("modes", ["teaching", "tool", "knowledge", "interaction"])
    ]


class LLMPlanner:
    """Plan WebGIS map actions for the assistant copilot."""

    def __init__(self, minimax_client: MiniMaxClient, fallback_planner: AssistantService):
        self.minimax_client = minimax_client
        self.fallback_planner = fallback_planner

    def plan_actions(
        self,
        message: str,
        project: ProjectRecord,
        map_context: Optional[Dict[str, Any]] = None,
        target: str = "webgis",
        input_mode: str = "text",
        assistant_mode: str = "tool",
    ) -> Dict[str, Any]:
        """Return a WebGIS action plan dict.

        ``target`` is kept for backward compatibility with existing callers,
        but the only valid value after the migration is ``"webgis"``. Any
        other value is normalised down to ``"webgis"`` so the assistant
        keeps working on the existing UI. ``assistant_mode`` gates the
        interaction fast path and prompt tool table; legacy modes default
        to ``"tool"`` and behave exactly as before.
        """
        normalized_target = "webgis"
        normalized_input_mode = input_mode if input_mode in {"text", "voice"} else "text"
        map_context = map_context or {}

        if assistant_mode == "interaction":
            return self._plan_interaction(message, project, map_context, normalized_target, normalized_input_mode)

        if normalized_input_mode == "voice":
            plan = self.fallback_planner.plan_voice_actions(message, project, map_context=map_context)
            plan["target"] = normalized_target
            plan["planner"] = "voice_rule" if plan.get("actions") else "voice_clarification"
            return plan

        rule_plan = self.fallback_planner.plan_actions(message, project, map_context=map_context)
        if self._should_use_rule_preflight(rule_plan):
            rule_plan["target"] = normalized_target
            rule_plan["planner"] = "rule_preflight"
            return rule_plan

        try:
            raw_content = self.minimax_client.chat_completion(
                self._messages(message, project, map_context),
                temperature=0.15,
            )
            parsed = self._parse_json(raw_content)
            return self._validate_plan(parsed)
        except Exception as exc:
            fallback = dict(rule_plan)
            fallback["target"] = normalized_target
            fallback["planner"] = "rule_fallback"
            fallback["llm_fallback_reason"] = str(exc)
            return fallback

    # ------------------------------------------------------------------
    # Interaction mode (智能交互): rule fast path, then MiniMax
    # ------------------------------------------------------------------

    def _plan_interaction(
        self,
        message: str,
        project: ProjectRecord,
        map_context: Dict[str, Any],
        normalized_target: str,
        normalized_input_mode: str,
    ) -> Dict[str, Any]:
        rule_plan = self.fallback_planner.plan_interaction_actions(message, project, map_context=map_context)
        rule_plan["target"] = normalized_target
        if rule_plan.get("actions"):
            rule_plan["planner"] = "interaction_rule"
            return rule_plan

        is_voice = normalized_input_mode == "voice"
        try:
            messages = (
                self._voice_interaction_messages(message, project, map_context)
                if is_voice
                else self._interaction_messages(message, project, map_context)
            )
            raw_content = self.minimax_client.chat_completion(
                messages,
                temperature=0.15,
                timeout=VOICE_LLM_TIMEOUT_SECONDS,
            )
            parsed = self._parse_json(raw_content)
            plan = self._validate_plan(parsed, planner="interaction_minimax")
            plan["target"] = normalized_target
            return plan
        except Exception as exc:
            fallback = dict(rule_plan)
            fallback["target"] = normalized_target
            fallback["planner"] = "voice_clarification" if is_voice else "interaction_clarification"
            fallback["llm_fallback_reason"] = str(exc)
            return fallback

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _messages(
        self,
        message: str,
        project: ProjectRecord,
        map_context: Dict[str, Any],
    ) -> List[Dict[str, str]]:
        visible_layers = [
            {
                "layer_id": layer.layer_id,
                "name": layer.name,
                "kind": layer.kind,
                "geometry_type": layer.geometry_type,
            }
            for layer in project.layers
            if layer.visible
        ]
        context: Dict[str, Any] = {
            "project": {
                "project_id": project.project_id,
                "active_layer_id": project.active_layer_id,
                "enabled_templates": project.enabled_templates,
                "visible_layers": visible_layers,
                "view": project.view,
            },
            "map_context": map_context,
            "webgis_tools": ASSISTANT_TOOL_SCHEMA,
        }
        system = (
            "You are a geography classroom WebGIS copilot. Return only valid JSON. "
            "The JSON schema is {\"assistant_message\": string, \"actions\": "
            "[{\"tool_name\": string, \"tool_params\": object}]}. "
            "Use only the tool names listed in webgis_tools. Do not invent tools. "
            "Do not produce QGIS-specific operations — heavy spatial analysis is "
            "handled by the separate /workflow pipeline and returned to the WebGIS map. "
            "Prefer safe, reversible actions and concise classroom-ready Chinese "
            "explanations."
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
            {"role": "user", "content": message},
        ]

    def _interaction_context(self, project: ProjectRecord, map_context: Dict[str, Any]) -> Dict[str, Any]:
        # Interaction commands frequently target *hidden* layers ("显示人口迁移
        # 图层"), so the LLM needs the full catalogue with visibility flags —
        # not just what is currently on screen.
        all_layers = [
            {
                "layer_id": layer.layer_id,
                "name": layer.name,
                "kind": layer.kind,
                "geometry_type": layer.geometry_type,
                "visible": layer.visible,
                "opacity": layer.opacity,
            }
            for layer in project.layers
        ]
        allowed_templates = [item for item in list_templates() if item["id"] in INTERACTION_ALLOWED_TEMPLATES]
        return {
            "project": {
                "project_id": project.project_id,
                "active_layer_id": project.active_layer_id,
                "enabled_templates": project.enabled_templates,
                "all_layers": all_layers,
                "view": project.view,
            },
            "map_context": map_context,
            "webgis_tools": _tools_for_mode("interaction"),
            "workflow_templates": allowed_templates,
        }

    def _interaction_messages(
        self,
        message: str,
        project: ProjectRecord,
        map_context: Dict[str, Any],
    ) -> List[Dict[str, str]]:
        context = self._interaction_context(project, map_context)
        system = (
            "You are the voice-control brain of a classroom WebGIS platform (智能交互模式). "
            "The teacher issues spoken-style commands; you translate them into tool calls. "
            "Return only valid JSON: {\"assistant_message\": string, \"actions\": "
            "[{\"tool_name\": string, \"tool_params\": object}]}. "
            "Use only tools listed in webgis_tools; layer ids must come from all_layers "
            "(match by name if the id is unknown). run_workflow only accepts template ids "
            "from workflow_templates. If the request is unclear or not an actionable "
            "command, return exactly one explain_current_view action with a short "
            "Chinese hint. Keep assistant_message concise and classroom-ready."
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
            {"role": "user", "content": message},
        ]

    def _voice_interaction_messages(
        self,
        message: str,
        project: ProjectRecord,
        map_context: Dict[str, Any],
    ) -> List[Dict[str, str]]:
        messages = self._interaction_messages(message, project, map_context)
        voice_addendum = (
            " The input comes from speech recognition: expect homophone typos and "
            "short colloquial phrases (e.g. 三位地球 → 三维地球). assistant_message "
            "must be at most 150 Chinese characters, spoken-style, no markdown. "
            "Prefer reversible actions; never invent layer ids."
        )
        messages[0]["content"] = messages[0]["content"] + voice_addendum
        return messages

    # ------------------------------------------------------------------
    # JSON parsing and validation
    # ------------------------------------------------------------------

    def _parse_json(self, content: str) -> Dict[str, Any]:
        cleaned = (content or "").strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
            cleaned = re.sub(r"```$", "", cleaned).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            extracted = self._extract_json_object(cleaned)
            if not extracted:
                raise
            return json.loads(extracted)

    def _validate_plan(self, payload: Dict[str, Any], planner: str = "minimax") -> Dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("LLM plan must be an object")
        raw_actions = payload.get("actions")
        if not isinstance(raw_actions, list):
            raise ValueError("LLM plan does not contain actions[]")

        actions: List[Dict[str, Any]] = []
        for item in raw_actions:
            if not isinstance(item, dict):
                raise ValueError("LLM action must be an object")
            tool_name = str(item.get("tool_name") or "")
            if tool_name not in WEBGIS_ALLOWED_TOOLS:
                raise ValueError(f"LLM requested unsupported tool: {tool_name}")
            tool_params = item.get("tool_params") or {}
            if not isinstance(tool_params, dict):
                raise ValueError(f"LLM tool_params must be an object for {tool_name}")
            actions.append({"tool_name": tool_name, "tool_params": tool_params})

        if not actions:
            raise ValueError("LLM plan did not produce any actions")
        if len(actions) > MAX_LLM_ACTIONS:
            actions = actions[:MAX_LLM_ACTIONS]

        return {
            "assistant_message": str(payload.get("assistant_message") or "我将按当前地图上下文执行操作。"),
            "target": "webgis",
            "actions": actions,
            "planner": planner,
        }

    @staticmethod
    def _extract_json_object(content: str) -> str:
        start = content.find("{")
        while start != -1:
            depth = 0
            in_string = False
            escaped = False
            for index in range(start, len(content)):
                char = content[index]
                if in_string:
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == '"':
                        in_string = False
                    continue
                if char == '"':
                    in_string = True
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        return content[start : index + 1]
            start = content.find("{", start + 1)
        return ""

    @staticmethod
    def _should_use_rule_preflight(plan: Dict[str, Any]) -> bool:
        deterministic_tools = {
            "switch_basemap",
            "apply_template",
            "toggle_layer",
            "reorder_layer",
            "style_layer",
            "draw_annotation",
            "measure",
            "export_snapshot",
            "search_poi",
            "toggle_teaching_map",
            "open_material",
            "generate_image",
        }
        actions = plan.get("actions") or []
        return any(
            str(action.get("tool_name") or "") in deterministic_tools
            for action in actions
            if isinstance(action, dict)
        )


def allowed_tool_names(target: str = "webgis") -> Iterable[str]:
    """Return the WebGIS-only tool whitelist (kept for callers that still
    expect a ``target`` argument)."""
    return WEBGIS_ALLOWED_TOOLS
