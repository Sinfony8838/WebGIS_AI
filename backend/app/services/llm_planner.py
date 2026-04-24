from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional

from ..models import ProjectRecord
from .assistant import ASSISTANT_TOOL_SCHEMA, AssistantService
from .minimax_client import MiniMaxClient
from .qgis_bridge import QGIS_ALLOWED_TOOLS, QGIS_TOOL_SCHEMA, QgisBridgeClient


WEBGIS_ALLOWED_TOOLS = {item["name"] for item in ASSISTANT_TOOL_SCHEMA}
MAX_LLM_ACTIONS = 12


class LLMPlanner:
    def __init__(self, minimax_client: MiniMaxClient, fallback_planner: AssistantService, qgis_bridge: QgisBridgeClient):
        self.minimax_client = minimax_client
        self.fallback_planner = fallback_planner
        self.qgis_bridge = qgis_bridge

    def plan_actions(
        self,
        message: str,
        project: ProjectRecord,
        map_context: Optional[Dict[str, Any]] = None,
        target: str = "webgis",
    ) -> Dict[str, Any]:
        normalized_target = target if target in {"webgis", "qgis", "auto"} else "webgis"
        try:
            raw_content = self.minimax_client.chat_completion(
                self._messages(message, project, map_context or {}, normalized_target),
                temperature=0.15,
            )
            parsed = self._parse_json(raw_content)
            return self._validate_plan(parsed, normalized_target)
        except Exception as exc:
            fallback = self._fallback(message, project, map_context or {}, normalized_target)
            fallback["llm_fallback_reason"] = str(exc)
            return fallback

    def _messages(self, message: str, project: ProjectRecord, map_context: Dict[str, Any], target: str) -> List[Dict[str, str]]:
        visible_layers = [
            {"layer_id": layer.layer_id, "name": layer.name, "kind": layer.kind, "geometry_type": layer.geometry_type}
            for layer in project.layers
            if layer.visible
        ]
        context = {
            "target": target,
            "project": {
                "project_id": project.project_id,
                "active_layer_id": project.active_layer_id,
                "enabled_templates": project.enabled_templates,
                "visible_layers": visible_layers,
                "view": project.view,
            },
            "map_context": map_context,
            "webgis_tools": ASSISTANT_TOOL_SCHEMA,
            "qgis_tools": QGIS_TOOL_SCHEMA,
        }
        system = (
            "You are a geography classroom GIS copilot. Return only valid JSON. "
            "The JSON schema is {\"assistant_message\": string, \"target\": \"webgis\"|\"qgis\", "
            "\"actions\": [{\"tool_name\": string, \"tool_params\": object}]}. "
            "Use only the provided tool names. Do not invent tools. Do not write Python code. "
            "For target=webgis, use only webgis_tools. For target=qgis, use only qgis_tools. "
            "Prefer safe, reversible actions and concise classroom-ready Chinese explanations."
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
            {"role": "user", "content": message},
        ]

    def _parse_json(self, content: str) -> Dict[str, Any]:
        cleaned = content.strip()
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

    def _validate_plan(self, payload: Dict[str, Any], requested_target: str) -> Dict[str, Any]:
        plan_target = str(payload.get("target") or requested_target)
        if plan_target == "auto":
            plan_target = requested_target if requested_target in {"webgis", "qgis"} else "webgis"
        if plan_target not in {"webgis", "qgis"}:
            raise ValueError(f"Unsupported LLM target: {plan_target}")

        allowed_tools = QGIS_ALLOWED_TOOLS if plan_target == "qgis" else WEBGIS_ALLOWED_TOOLS
        raw_actions = payload.get("actions")
        if not isinstance(raw_actions, list):
            raise ValueError("LLM plan does not contain actions[]")

        actions = []
        for item in raw_actions:
            if not isinstance(item, dict):
                raise ValueError("LLM action must be an object")
            tool_name = str(item.get("tool_name") or "")
            if tool_name not in allowed_tools:
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
            "target": plan_target,
            "actions": actions,
            "planner": "minimax",
        }

    def _extract_json_object(self, content: str) -> str:
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

    def _fallback(self, message: str, project: ProjectRecord, map_context: Dict[str, Any], target: str) -> Dict[str, Any]:
        if target == "qgis":
            fallback = self.qgis_bridge.fallback_plan(message)
            fallback["planner"] = "rule_fallback"
            return fallback
        fallback = self.fallback_planner.plan_actions(message, project, map_context=map_context)
        fallback["target"] = "webgis"
        fallback["planner"] = "rule_fallback"
        return fallback


def allowed_tool_names(target: str) -> Iterable[str]:
    return QGIS_ALLOWED_TOOLS if target == "qgis" else WEBGIS_ALLOWED_TOOLS
