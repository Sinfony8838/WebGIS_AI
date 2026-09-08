"""Runtime policy and observability for the WebGIS teaching agent.

The product deliberately keeps a small, single-agent execution model.  This
module supplies the cross-cutting pieces that otherwise tend to leak into the
router and tool executor: bounded runs, cheap loop detection, structured
events, privacy-safe traces, and verify-on-stop contracts.

It is intentionally framework-free.  The WebGIS assistant already has a
domain-specific planner, permission model, persistent conversation store, and
classroom UI; replacing those with a general agent framework would add a
second source of truth without improving the classroom workflow.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4


HARNESS_ID = "webgis-teaching-agent"
HARNESS_VERSION = "3.0"
TRACE_SCHEMA_VERSION = "1.0"


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def fingerprint(value: Any, salt: str = "") -> str:
    """Return a compact one-way identifier for trace-local correlation."""

    payload = f"{salt}:{_stable_json(value)}" if salt else _stable_json(value)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def validate_json_contract(value: Any, schema: Dict[str, Any], path: str = "tool_params") -> str:
    """Validate the small JSON-Schema subset used by assistant tools.

    Keeping this validator local avoids adding a runtime dependency solely for
    eighteen compact tool contracts.  Unsupported schema keywords are ignored;
    the supported subset is covered by tests and intentionally matches
    ``ASSISTANT_TOOL_INPUT_SCHEMAS``.
    """

    expected_type = schema.get("type")
    if expected_type:
        type_names = [expected_type] if isinstance(expected_type, str) else list(expected_type)

        def matches(type_name: str) -> bool:
            if type_name == "object":
                return isinstance(value, dict)
            if type_name == "array":
                return isinstance(value, list)
            if type_name == "string":
                return isinstance(value, str)
            if type_name == "boolean":
                return isinstance(value, bool)
            if type_name == "integer":
                return isinstance(value, int) and not isinstance(value, bool)
            if type_name == "number":
                return isinstance(value, (int, float)) and not isinstance(value, bool)
            return False

        if not any(matches(str(type_name)) for type_name in type_names):
            return f"{path} 类型错误，应为 {'/'.join(str(item) for item in type_names)}"

    if "enum" in schema and value not in schema["enum"]:
        return f"{path} 取值不在允许范围内"

    if isinstance(value, dict):
        required = [str(item) for item in schema.get("required", [])]
        missing = [key for key in required if key not in value]
        if missing:
            return f"{path} 缺少必填字段：{', '.join(missing)}"

        any_of = schema.get("anyOf") or []
        if any_of:
            matched = False
            choices: List[str] = []
            for option in any_of:
                option_required = [str(item) for item in option.get("required", [])]
                if option_required:
                    choices.append("+".join(option_required))
                if all(key in value for key in option_required):
                    matched = True
            if not matched:
                return f"{path} 至少需要一组字段：{' 或 '.join(choices)}"

        min_properties = schema.get("minProperties")
        if isinstance(min_properties, int) and len(value) < min_properties:
            return f"{path} 至少需要 {min_properties} 个字段"

        properties = schema.get("properties") or {}
        if schema.get("additionalProperties") is False:
            unknown = sorted(str(key) for key in value if key not in properties)
            if unknown:
                return f"{path} 包含未声明字段：{', '.join(unknown)}"
        for key, item in value.items():
            child_schema = properties.get(key)
            if isinstance(child_schema, dict):
                error = validate_json_contract(item, child_schema, f"{path}.{key}")
                if error:
                    return error

    if isinstance(value, list):
        min_items = schema.get("minItems")
        max_items = schema.get("maxItems")
        if isinstance(min_items, int) and len(value) < min_items:
            return f"{path} 至少需要 {min_items} 项"
        if isinstance(max_items, int) and len(value) > max_items:
            return f"{path} 最多允许 {max_items} 项"
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                error = validate_json_contract(item, item_schema, f"{path}[{index}]")
                if error:
                    return error

    if isinstance(value, str):
        min_length = schema.get("minLength")
        max_length = schema.get("maxLength")
        if isinstance(min_length, int) and len(value.strip()) < min_length:
            return f"{path} 不能为空"
        if isinstance(max_length, int) and len(value) > max_length:
            return f"{path} 最长允许 {max_length} 个字符"

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, (int, float)) and value < minimum:
            return f"{path} 不能小于 {minimum}"
        if isinstance(maximum, (int, float)) and value > maximum:
            return f"{path} 不能大于 {maximum}"

    return ""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class HarnessPolicy:
    """Configuration-owned policy applied to every assistant run."""

    max_actions_per_run: int = 8
    max_identical_actions: int = 2
    max_tool_failures: int = 1
    max_seconds: float = 180.0
    max_trace_events: int = 64

    @classmethod
    def from_config(cls, config: Any) -> "HarnessPolicy":
        return cls(
            max_actions_per_run=max(1, min(int(getattr(config, "assistant_harness_max_actions", 8)), 32)),
            max_identical_actions=max(1, min(int(getattr(config, "assistant_harness_max_identical_actions", 2)), 5)),
            max_tool_failures=max(1, min(int(getattr(config, "assistant_harness_max_tool_failures", 1)), 8)),
            max_seconds=max(5.0, min(float(getattr(config, "assistant_harness_max_seconds", 180.0)), 900.0)),
            max_trace_events=max(16, min(int(getattr(config, "assistant_harness_max_trace_events", 64)), 256)),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_actions_per_run": self.max_actions_per_run,
            "max_identical_actions": self.max_identical_actions,
            "max_tool_failures": self.max_tool_failures,
            "max_seconds": self.max_seconds,
            "max_trace_events": self.max_trace_events,
        }


class HarnessContractError(RuntimeError):
    """Raised when the harness itself detects an invalid run boundary."""


class HarnessExecutionError(RuntimeError):
    """Preserve a privacy-safe trace when a run fails inside a worker thread."""

    def __init__(self, cause: Exception, report: Dict[str, Any]):
        super().__init__(str(cause))
        self.cause = cause
        self.report = report


@dataclass
class AgentRun:
    """One bounded, observable assistant invocation.

    Raw messages, prompts, tool arguments, tool outputs, file paths, and API
    credentials are deliberately absent from the trace.  Per-run salted
    fingerprints permit correlation inside one trace without persisting
    classroom data.
    """

    policy: HarnessPolicy
    job_id: str
    input_payload: Dict[str, Any]
    parent_run_id: str = ""
    run_id: str = field(default_factory=lambda: f"run_{uuid4().hex}")
    started_at: str = field(default_factory=_utc_now)
    _started_monotonic: float = field(default_factory=time.monotonic, repr=False)
    _trace_salt: str = field(default_factory=lambda: uuid4().hex, repr=False)
    _events: List[Dict[str, Any]] = field(default_factory=list, repr=False)
    _open_stages: Dict[str, float] = field(default_factory=dict, repr=False)
    _action_counts: Dict[str, int] = field(default_factory=dict, repr=False)
    _tool_spans: Dict[str, float] = field(default_factory=dict, repr=False)
    _dropped_events: int = field(default=0, repr=False)
    _usage: Dict[str, int] = field(
        default_factory=lambda: {
            "actions_planned": 0,
            "tool_calls": 0,
            "tool_failures": 0,
            "guardrail_trips": 0,
        },
        repr=False,
    )

    def _elapsed_seconds(self) -> float:
        return max(0.0, time.monotonic() - self._started_monotonic)

    def _fingerprint(self, value: Any) -> str:
        # The per-run salt prevents low-entropy prompts/arguments from being
        # recovered through a precomputed dictionary while keeping events in
        # the same trace correlatable.
        return fingerprint(value, salt=self._trace_salt)

    def check_deadline(self) -> None:
        if self._elapsed_seconds() > self.policy.max_seconds:
            self._usage["guardrail_trips"] += 1
            self.event("guardrail", "wall_clock", "blocked", {"limit_seconds": self.policy.max_seconds})
            raise HarnessContractError("智能体运行已达到时间上限，未继续执行后续工具。")

    def record_guardrail(self, name: str, attributes: Optional[Dict[str, Any]] = None) -> None:
        self._usage["guardrail_trips"] += 1
        self.event("guardrail", name, "blocked", attributes)

    def event(self, event_type: str, name: str, status: str, attributes: Optional[Dict[str, Any]] = None) -> str:
        event_id = f"evt_{uuid4().hex}"
        event = {
            "sequence": len(self._events) + self._dropped_events + 1,
            "event_id": event_id,
            "type": event_type,
            "name": name,
            "status": status,
            "attributes": dict(attributes or {}),
        }
        if len(self._events) < self.policy.max_trace_events:
            self._events.append(event)
        else:
            self._dropped_events += 1
        return event_id

    def record_stage(self, name: str, status: str) -> None:
        """Translate the existing stage callback into trace spans."""

        if status == "running":
            self.check_deadline()
            self._open_stages[name] = time.monotonic()
            self.event("stage", name, "running")
            return
        started = self._open_stages.pop(name, None)
        attributes: Dict[str, Any] = {}
        if started is not None:
            attributes["duration_ms"] = round((time.monotonic() - started) * 1000, 3)
        self.event("stage", name, status, attributes)

    def inspect_plan(self, actions: List[Dict[str, Any]]) -> str:
        """Return a fail-closed validation error, or an empty string."""

        self.check_deadline()
        self._usage["actions_planned"] = len(actions)
        if len(actions) > self.policy.max_actions_per_run:
            self._usage["guardrail_trips"] += 1
            self.event(
                "guardrail",
                "action_budget",
                "blocked",
                {"planned": len(actions), "limit": self.policy.max_actions_per_run},
            )
            return f"单次请求计划了 {len(actions)} 个动作，超过上限 {self.policy.max_actions_per_run}；请缩小操作范围。"

        fingerprints: List[str] = []
        for action in actions:
            if not isinstance(action, dict):
                self._usage["guardrail_trips"] += 1
                self.event("guardrail", "plan_contract", "blocked", {"reason": "action_not_object"})
                return "工具计划格式无效：每个动作必须是对象。"
            action_fingerprint = self._fingerprint(
                {
                    "tool_name": str(action.get("tool_name") or ""),
                    "tool_params": action.get("tool_params") or {},
                }
            )
            fingerprints.append(action_fingerprint)
            count = self._action_counts.get(action_fingerprint, 0) + 1
            self._action_counts[action_fingerprint] = count
            if count > self.policy.max_identical_actions:
                self._usage["guardrail_trips"] += 1
                self.event(
                    "guardrail",
                    "repeated_action",
                    "blocked",
                    {"action_fingerprint": action_fingerprint, "count": count},
                )
                return "检测到重复工具调用，已停止执行以避免循环或重复写入。"

        self.event(
            "plan",
            "tool_plan",
            "validated",
            {"action_count": len(actions), "action_fingerprints": fingerprints},
        )
        return ""

    def before_tool(self, action: Dict[str, Any]) -> str:
        self.check_deadline()
        if self._usage["tool_calls"] >= self.policy.max_actions_per_run:
            self._usage["guardrail_trips"] += 1
            raise HarnessContractError("智能体工具调用已达到单次运行上限。")
        if self._usage["tool_failures"] >= self.policy.max_tool_failures:
            self._usage["guardrail_trips"] += 1
            raise HarnessContractError("智能体工具失败次数已达到上限。")
        self._usage["tool_calls"] += 1
        tool_name = str(action.get("tool_name") or "unknown")
        action_fingerprint = self._fingerprint({"tool_name": tool_name, "tool_params": action.get("tool_params") or {}})
        event_id = self.event(
            "tool",
            tool_name,
            "running",
            {"action_fingerprint": action_fingerprint},
        )
        self._tool_spans[event_id] = time.monotonic()
        return event_id

    def after_tool(self, event_id: str, tool_name: str, result: Any) -> None:
        if not isinstance(result, dict):
            raise HarnessContractError(f"工具 {tool_name} 返回了无效结果。")
        if not isinstance(result.get("assistant_message", ""), str):
            raise HarnessContractError(f"工具 {tool_name} 的 assistant_message 无效。")
        if not isinstance(result.get("artifacts", []), list):
            raise HarnessContractError(f"工具 {tool_name} 的 artifacts 无效。")
        started = self._tool_spans.pop(event_id, None)
        attributes = {"result_fingerprint": self._fingerprint(result)}
        if started is not None:
            attributes["duration_ms"] = round((time.monotonic() - started) * 1000, 3)
        self.event("tool", tool_name, "success", attributes)

    def fail_tool(self, event_id: str, tool_name: str, error: Exception) -> None:
        self._usage["tool_failures"] += 1
        started = self._tool_spans.pop(event_id, None)
        attributes: Dict[str, Any] = {
            "error_class": type(error).__name__,
            "error_fingerprint": self._fingerprint({"type": type(error).__name__, "message": str(error)}),
        }
        if started is not None:
            attributes["duration_ms"] = round((time.monotonic() - started) * 1000, 3)
        self.event("tool", tool_name, "error", attributes)

    def verify_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        self.check_deadline()
        result_is_object = isinstance(result, dict)
        checks = {
            "result_is_object": result_is_object,
            "assistant_message_is_string": result_is_object and isinstance(result.get("assistant_message"), str),
            "planned_actions_is_list": result_is_object and isinstance(result.get("actions_planned", []), list),
            "executed_actions_is_list": result_is_object and isinstance(result.get("actions_executed", []), list),
            "approval_has_id": result_is_object
            and (not result.get("requires_confirmation") or bool(result.get("confirmation_id"))),
            "approval_has_no_execution": result_is_object
            and (not result.get("requires_confirmation") or not result.get("actions_executed")),
        }
        valid = all(checks.values())
        self.event("verification", "verify_on_stop", "success" if valid else "error", checks)
        if not valid:
            raise HarnessContractError("智能体结束状态未通过一致性校验。")
        return {"valid": True, "checks": checks}

    def finish(
        self,
        status: str,
        stop_reason: str,
        conversation_id: str = "",
        verification: Optional[Dict[str, Any]] = None,
        error: Optional[Exception] = None,
    ) -> Dict[str, Any]:
        for stage_name in list(self._open_stages):
            self.record_stage(stage_name, "error" if status == "failed" else "stopped")
        error_payload: Dict[str, Any] = {}
        if error is not None:
            error_payload = {
                "class": type(error).__name__,
                "fingerprint": self._fingerprint({"type": type(error).__name__, "message": str(error)}),
            }
        return {
            "schema_version": TRACE_SCHEMA_VERSION,
            "harness_id": HARNESS_ID,
            "harness_version": HARNESS_VERSION,
            "run_id": self.run_id,
            "parent_run_id": self.parent_run_id,
            "job_id": self.job_id,
            "conversation_id": conversation_id,
            "status": status,
            "stop_reason": stop_reason,
            "started_at": self.started_at,
            "finished_at": _utc_now(),
            "duration_ms": round(self._elapsed_seconds() * 1000, 3),
            "input_fingerprint": self._fingerprint(self.input_payload),
            "policy": self.policy.to_dict(),
            "usage": dict(self._usage),
            "verification": verification or {"valid": False, "checks": {}},
            "events": list(self._events),
            "dropped_events": self._dropped_events,
            "error": error_payload,
        }


def infer_stop_reason(result: Dict[str, Any]) -> str:
    if result.get("requires_confirmation"):
        return "approval_required"
    planner = str(result.get("planner") or "")
    if planner in {"blocked", "harness_guardrail"}:
        return "policy_blocked"
    if "clarification" in planner:
        return "needs_clarification"
    if planner == "confirmation_rejected":
        return "rejected"
    return "completed"
