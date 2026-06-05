"""LLM planner for the in-classroom WebGIS assistant.

After the migration to the backend GIS workflow, the planner is
WebGIS-only: it produces ``{tool_name, tool_params}`` actions that the
existing :class:`AssistantService` knows how to execute on the OpenLayers
map (basemap switching, layer toggles, view changes, POI search, teaching
maps, etc.). Heavy GIS work is now handled by the workflow pipeline
(``/workflow/*``), not by this module.

Two paths remain:

* **Voice** input — handed to ``AssistantService.plan_voice_actions``
  (deterministic, no LLM).
* **Text** input — first tried by ``AssistantService.plan_actions``;
  if any of the rule-based actions are recognised the rule plan wins
  ("rule_preflight"). Otherwise the message is sent to MiniMax which
  returns a JSON plan; on any failure we fall back to the rule planner
  again ("rule_fallback").
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional

from ..models import ProjectRecord
from .assistant import ASSISTANT_TOOL_SCHEMA, AssistantService
from .minimax_client import MiniMaxClient


WEBGIS_ALLOWED_TOOLS = {item["name"] for item in ASSISTANT_TOOL_SCHEMA}
MAX_LLM_ACTIONS = 12


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
    ) -> Dict[str, Any]:
        """Return a WebGIS action plan dict.

        ``target`` is kept for backward compatibility with existing callers,
        but the only valid value after the migration is ``"webgis"``. Any
        other value is normalised down to ``"webgis"`` so the assistant
        keeps working on the existing UI.
        """
        normalized_target = "webgis"
        normalized_input_mode = input_mode if input_mode in {"text", "voice"} else "text"
        map_context = map_context or {}

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

    def _validate_plan(self, payload: Dict[str, Any]) -> Dict[str, Any]:
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
            "planner": "minimax",
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
