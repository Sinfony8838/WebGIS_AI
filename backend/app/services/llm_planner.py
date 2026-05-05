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
        input_mode: str = "text",
    ) -> Dict[str, Any]:
        normalized_target = target if target in {"webgis", "qgis", "auto"} else "webgis"
        normalized_input_mode = input_mode if input_mode in {"text", "voice"} else "text"
        if normalized_input_mode == "voice" and normalized_target == "webgis":
            plan = self.fallback_planner.plan_voice_actions(message, project, map_context=map_context or {})
            plan["target"] = "webgis"
            plan["planner"] = "voice_rule" if plan.get("actions") else "voice_clarification"
            return plan
        if normalized_target == "webgis":
            rule_plan = self.fallback_planner.plan_actions(message, project, map_context=map_context or {})
            if self._should_use_rule_preflight(rule_plan):
                rule_plan["target"] = "webgis"
                rule_plan["planner"] = "rule_preflight"
                return rule_plan

        # Pre-fetch QGIS layers so the LLM (and fallback) know what data is available
        qgis_layers: Optional[List[Dict[str, Any]]] = None
        if normalized_target == "qgis":
            qgis_layers = self._prefetch_qgis_layers()
            if self._should_use_qgis_rule_preflight(message):
                qgis_rule_plan = self._fallback(message, project, map_context or {}, normalized_target, qgis_layers=qgis_layers)
                qgis_rule_plan["planner"] = "qgis_rule_preflight"
                return qgis_rule_plan

        try:
            raw_content = self.minimax_client.chat_completion(
                self._messages(message, project, map_context or {}, normalized_target, qgis_layers=qgis_layers),
                temperature=0.15,
            )
            parsed = self._parse_json(raw_content)
            plan = self._validate_plan(parsed, normalized_target)
            # Guard: if LLM only planned get_layers for QGIS, enrich with fallback actions
            if normalized_target == "qgis" and self._is_get_layers_only(plan):
                enriched = self._fallback(message, project, map_context or {}, normalized_target, qgis_layers=qgis_layers)
                enriched["planner"] = "minimax_enriched"
                enriched["assistant_message"] = plan.get("assistant_message") or enriched.get("assistant_message", "")
                return enriched
            return plan
        except Exception as exc:
            fallback = self._fallback(message, project, map_context or {}, normalized_target, qgis_layers=qgis_layers)
            fallback["llm_fallback_reason"] = str(exc)
            return fallback

    def _prefetch_qgis_layers(self) -> Optional[List[Dict[str, Any]]]:
        """Pre-fetch current QGIS layers so the LLM can plan with full context."""
        try:
            response = self.qgis_bridge.layers()
            if response.get("status") == "success":
                layers = response.get("layers") or response.get("data") or []
                if isinstance(layers, list):
                    return layers
        except Exception:
            pass
        return None

    @staticmethod
    def _is_get_layers_only(plan: Dict[str, Any]) -> bool:
        """Check if a plan only contains get_layers with no real actions."""
        actions = plan.get("actions") or []
        return all(str(a.get("tool_name") or "") == "get_layers" for a in actions)

    def _messages(
        self,
        message: str,
        project: ProjectRecord,
        map_context: Dict[str, Any],
        target: str,
        qgis_layers: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, str]]:
        visible_layers = [
            {"layer_id": layer.layer_id, "name": layer.name, "kind": layer.kind, "geometry_type": layer.geometry_type}
            for layer in project.layers
            if layer.visible
        ]
        context: Dict[str, Any] = {
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
        if qgis_layers is not None:
            context["qgis_current_layers"] = qgis_layers
        qgis_layer_instruction = ""
        if qgis_layers is not None:
            qgis_layer_instruction = (
                "\n\nIMPORTANT: The field 'qgis_current_layers' in the context below lists ALL layers "
                "currently loaded in the QGIS project. You already know what data is available — "
                "do NOT plan only get_layers. Instead, pick the most relevant layer from qgis_current_layers "
                "and immediately plan the visualization or analysis actions the user requested. "
                "Avoid set_style because the connected QGIS plugin rejects generic thematic styling. "
                "Prefer dedicated operations such as create_heatmap / create_flow_arrows / run_algorithm, "
                "or use set_active_layer + set_layer_visibility + zoom_to_layer for navigation and presentation. "
                "Use the actual layer_name or layer_id values from qgis_current_layers."
            )
        else:
            qgis_layer_instruction = (
                "\n\nFor QGIS target: Plan a COMPLETE action sequence. If you must call get_layers, "
                "also include the visualization actions the user requested (create_heatmap, create_flow_arrows, run_algorithm, etc.) "
                "with your best guess at layer_name based on the user's description."
            )
        system = (
            "You are a geography classroom GIS copilot. Return only valid JSON. "
            "The JSON schema is {\"assistant_message\": string, \"target\": \"webgis\"|\"qgis\", "
            "\"actions\": [{\"tool_name\": string, \"tool_params\": object}]}. "
            "Use only the provided tool names. Do not invent tools. Do not write Python code. "
            "For target=webgis, use only webgis_tools. For target=qgis, use only qgis_tools. "
            "Prefer safe, reversible actions and concise classroom-ready Chinese explanations."
            + qgis_layer_instruction
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

    def _fallback(
        self,
        message: str,
        project: ProjectRecord,
        map_context: Dict[str, Any],
        target: str,
        qgis_layers: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        if target == "qgis":
            fallback = self.qgis_bridge.fallback_plan(message, qgis_layers=qgis_layers)
            fallback["planner"] = "rule_fallback"
            return fallback
        fallback = self.fallback_planner.plan_actions(message, project, map_context=map_context)
        fallback["target"] = "webgis"
        fallback["planner"] = "rule_fallback"
        return fallback

    def _should_use_rule_preflight(self, plan: Dict[str, Any]) -> bool:
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
        return any(str(action.get("tool_name") or "") in deterministic_tools for action in actions if isinstance(action, dict))

    @staticmethod
    def _should_use_qgis_rule_preflight(message: str) -> bool:
        lowered = (message or "").lower()
        has_population_topic = any(token in lowered for token in ("人口", "population", "density"))
        has_distribution_intent = any(token in lowered for token in ("分布", "密度", "分布图", "专题图", "choropleth"))
        has_map_create_intent = any(token in lowered for token in ("制作", "生成", "创建", "绘制", "渲染", "create", "generate", "draw", "render"))
        return bool(has_population_topic and (has_distribution_intent or has_map_create_intent))


def allowed_tool_names(target: str) -> Iterable[str]:
    return QGIS_ALLOWED_TOOLS if target == "qgis" else WEBGIS_ALLOWED_TOOLS
