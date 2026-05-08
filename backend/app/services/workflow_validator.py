"""Workflow JSON validator for the PyQGIS workflow pipeline.

The validator only inspects the workflow JSON structure:
* whitelist of operations,
* required parameters per op,
* uniqueness of step ids,
* ``${stepId.key}`` reference legality,
* basic parameter sanity (CRS, distance, classes...).

It does NOT touch QGIS, the filesystem (beyond rejecting absolute paths in
restricted slots) or any external service. It returns a structured list of
``WorkflowError`` items so callers can render them as user-friendly messages.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field as dataclass_field
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Operation registry (Phase 1 minimum)
# ---------------------------------------------------------------------------

#: Whitelist of allowed operation names. Anything else is rejected up-front.
ALLOWED_OPS: Tuple[str, ...] = (
    "load_layer",
    "inspect_layer",
    "reproject",
    "fix_geometries",
    "filter_features",
    "calculate_field",
    "buffer",
    "choropleth",
    "aggregate_stats",
    "export_geojson",
    "export_style_json",
    "export_map_png",
)

#: Operations that are reserved but not yet implemented; validator allows them
#: to pass but the executor will report a clear "not implemented" error.
RESERVED_OPS: Tuple[str, ...] = (
    "spatial_join",
    "intersection",
    "clip",
    "classify",
    "heatmap",
    "add_label",
    "export_layout_pdf",
)

#: Required parameter keys per op.
REQUIRED_PARAMS: Dict[str, Tuple[str, ...]] = {
    "load_layer": ("source",),
    "inspect_layer": ("input",),
    "reproject": ("input", "target_crs"),
    "fix_geometries": ("input",),
    "filter_features": ("input", "expression"),
    "calculate_field": ("input", "field", "expression"),
    "buffer": ("input", "distance"),
    "choropleth": ("input", "field"),
    "aggregate_stats": ("input",),
    "export_geojson": ("input",),
    "export_style_json": ("input",),
    "export_map_png": ("layers",),
}

#: Allowed classification methods used by ``choropleth`` / ``classify``.
ALLOWED_CLASSIFY_METHODS = {"jenks", "equal", "quantile", "stddev", "natural_breaks"}

#: Pattern matching ``${stepId.outputKey}`` references.
REFERENCE_PATTERN = re.compile(r"^\$\{([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)\}$")


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------


@dataclass
class ValidationError:
    code: str
    message: str
    user_friendly: str
    step_id: str = ""
    field: str = ""
    details: Dict[str, Any] = dataclass_field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "user_friendly": self.user_friendly,
            "step_id": self.step_id,
            "field": self.field,
            "details": dict(self.details),
        }


@dataclass
class ValidationResult:
    valid: bool
    errors: List[ValidationError] = dataclass_field(default_factory=list)
    warnings: List[ValidationError] = dataclass_field(default_factory=list)
    normalized: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": [e.to_dict() for e in self.errors],
            "warnings": [w.to_dict() for w in self.warnings],
            "normalized": self.normalized,
        }


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _is_safe_relative_source(source: str) -> bool:
    """Return True if a ``load_layer.source`` value looks safe.

    The validator forbids absolute paths and parent traversals here. The
    executor itself will refuse to dereference paths outside known data dirs
    when running in a real workflow. Symbolic dataset ids (``china_provinces``,
    ``builtin:cities``) are allowed.
    """
    if not isinstance(source, str) or not source.strip():
        return False
    candidate = source.strip()
    if candidate.startswith(("/", "\\")):
        return False
    if re.match(r"^[A-Za-z]:[\\/]", candidate):
        return False  # Windows drive letter
    parts = PurePosixPath(candidate.replace("\\", "/")).parts
    if any(part == ".." for part in parts):
        return False
    return True


def _looks_like_reference(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("${") and value.endswith("}")


def _parse_reference(value: str) -> Optional[Tuple[str, str]]:
    match = REFERENCE_PATTERN.match(value)
    if not match:
        return None
    return match.group(1), match.group(2)


def _walk_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk_strings(item)


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


class WorkflowValidator:
    """Validate a workflow JSON document. Returns a :class:`ValidationResult`."""

    def __init__(
        self,
        allowed_ops: Optional[Tuple[str, ...]] = None,
        reserved_ops: Optional[Tuple[str, ...]] = None,
    ) -> None:
        self.allowed_ops = set(allowed_ops or ALLOWED_OPS)
        self.reserved_ops = set(reserved_ops or RESERVED_OPS)

    # -- public ---------------------------------------------------------

    def validate(self, workflow: Any) -> ValidationResult:
        errors: List[ValidationError] = []
        warnings: List[ValidationError] = []

        if not isinstance(workflow, dict):
            errors.append(ValidationError(
                code="WORKFLOW_NOT_OBJECT",
                message="workflow must be a JSON object",
                user_friendly="工作流必须是一个 JSON 对象。",
            ))
            return ValidationResult(valid=False, errors=errors, warnings=warnings)

        steps = workflow.get("steps")
        if not isinstance(steps, list) or not steps:
            errors.append(ValidationError(
                code="WORKFLOW_NO_STEPS",
                message="workflow.steps must be a non-empty list",
                user_friendly="工作流至少需要包含一个步骤。",
            ))
            return ValidationResult(valid=False, errors=errors, warnings=warnings)

        seen_ids: Set[str] = set()
        valid_step_outputs: Dict[str, Set[str]] = {}
        normalized_steps: List[Dict[str, Any]] = []

        # First pass: per-step structural validation.
        for index, step in enumerate(steps):
            step_errors = self._validate_step(step, index, seen_ids)
            if step_errors:
                errors.extend(step_errors)
                continue
            step_id = str(step["id"])
            seen_ids.add(step_id)
            op_name = str(step["op"])
            output_keys = self._infer_output_keys(op_name, step.get("output_bindings"))
            valid_step_outputs[step_id] = output_keys
            normalized_steps.append(self._normalize_step(step))

        # Second pass: reference validation (we need the full id table).
        for step in normalized_steps:
            errors.extend(self._validate_references(step, valid_step_outputs))

        # Validate outputs section (optional but if present must reference real steps).
        outputs_section = workflow.get("outputs")
        if outputs_section is not None:
            if not isinstance(outputs_section, dict):
                errors.append(ValidationError(
                    code="OUTPUTS_NOT_OBJECT",
                    message="workflow.outputs must be an object",
                    user_friendly="workflow.outputs 必须是对象。",
                ))
            else:
                for raw in _walk_strings(outputs_section):
                    if _looks_like_reference(raw):
                        ref = _parse_reference(raw)
                        if ref is None:
                            errors.append(ValidationError(
                                code="OUTPUTS_BAD_REFERENCE",
                                message=f"invalid reference syntax: {raw}",
                                user_friendly=f"输出引用 {raw} 格式不正确。",
                            ))
                            continue
                        step_id, key = ref
                        if step_id not in valid_step_outputs:
                            errors.append(ValidationError(
                                code="OUTPUTS_UNKNOWN_STEP",
                                message=f"outputs reference unknown step: {step_id}",
                                user_friendly=f"输出引用了不存在的步骤 {step_id}。",
                            ))
                        elif key not in valid_step_outputs[step_id]:
                            warnings.append(ValidationError(
                                code="OUTPUTS_UNKNOWN_KEY",
                                message=f"outputs reference unknown key: {step_id}.{key}",
                                user_friendly=f"输出键 {step_id}.{key} 在该步骤的产出中不可见。",
                            ))

        is_valid = not errors
        normalized = None
        if is_valid:
            normalized = dict(workflow)
            normalized["steps"] = normalized_steps
        return ValidationResult(
            valid=is_valid,
            errors=errors,
            warnings=warnings,
            normalized=normalized,
        )

    # -- step-level checks ---------------------------------------------

    def _validate_step(
        self,
        step: Any,
        index: int,
        seen_ids: Set[str],
    ) -> List[ValidationError]:
        errors: List[ValidationError] = []
        if not isinstance(step, dict):
            errors.append(ValidationError(
                code="STEP_NOT_OBJECT",
                message=f"step #{index} is not an object",
                user_friendly=f"第 {index + 1} 个步骤不是对象。",
            ))
            return errors

        step_id_raw = step.get("id")
        if not isinstance(step_id_raw, str) or not step_id_raw.strip():
            errors.append(ValidationError(
                code="STEP_NO_ID",
                message=f"step #{index} missing id",
                user_friendly=f"第 {index + 1} 个步骤缺少 id。",
            ))
        step_id = (step_id_raw or "").strip() if isinstance(step_id_raw, str) else ""
        if step_id and step_id in seen_ids:
            errors.append(ValidationError(
                code="STEP_DUPLICATE_ID",
                message=f"duplicate step id: {step_id}",
                user_friendly=f"步骤 id 重复：{step_id}。",
                step_id=step_id,
            ))

        op = step.get("op")
        if not isinstance(op, str) or not op.strip():
            errors.append(ValidationError(
                code="STEP_NO_OP",
                message=f"step {step_id or index} missing op",
                user_friendly=f"步骤 {step_id or index} 缺少 op 字段。",
                step_id=step_id,
            ))
            return errors  # cannot continue without op
        if op in self.reserved_ops:
            # reserved but not implemented yet — not a hard error in validator
            return errors  # short-circuit: param schema not yet defined here
        if op not in self.allowed_ops:
            errors.append(ValidationError(
                code="STEP_OP_NOT_ALLOWED",
                message=f"op '{op}' is not allowed",
                user_friendly=f"暂不支持的操作类型：{op}。",
                step_id=step_id,
            ))
            return errors

        params = step.get("params")
        if not isinstance(params, dict):
            errors.append(ValidationError(
                code="STEP_PARAMS_NOT_OBJECT",
                message=f"step {step_id} params must be an object",
                user_friendly=f"步骤 {step_id} 的 params 必须是对象。",
                step_id=step_id,
            ))
            return errors

        for required in REQUIRED_PARAMS.get(op, ()):
            if required not in params or params[required] in (None, ""):
                errors.append(ValidationError(
                    code="STEP_PARAM_MISSING",
                    message=f"step {step_id} missing param '{required}'",
                    user_friendly=f"步骤 {step_id} 缺少参数 {required}。",
                    step_id=step_id,
                    field=required,
                ))

        # op-specific extra validation
        errors.extend(self._validate_op_specific(op, step_id, params))

        depends_on = step.get("depends_on", [])
        if depends_on is not None and not isinstance(depends_on, list):
            errors.append(ValidationError(
                code="STEP_DEPENDS_ON_INVALID",
                message=f"step {step_id} depends_on must be a list",
                user_friendly=f"步骤 {step_id} 的 depends_on 必须是数组。",
                step_id=step_id,
            ))

        bindings = step.get("output_bindings")
        if bindings is not None and not isinstance(bindings, dict):
            errors.append(ValidationError(
                code="STEP_BINDINGS_INVALID",
                message=f"step {step_id} output_bindings must be an object",
                user_friendly=f"步骤 {step_id} 的 output_bindings 必须是对象。",
                step_id=step_id,
            ))
        return errors

    def _validate_op_specific(
        self, op: str, step_id: str, params: Dict[str, Any]
    ) -> List[ValidationError]:
        errors: List[ValidationError] = []

        if op == "load_layer":
            source = params.get("source")
            if isinstance(source, str) and not _looks_like_reference(source):
                if not _is_safe_relative_source(source):
                    errors.append(ValidationError(
                        code="LOAD_LAYER_UNSAFE_SOURCE",
                        message=f"unsafe source path: {source}",
                        user_friendly="数据源路径不允许使用绝对路径或包含 '..'。",
                        step_id=step_id,
                        field="source",
                    ))

        if op == "buffer":
            distance = params.get("distance")
            try:
                distance_value = float(distance)
                if distance_value <= 0:
                    raise ValueError("non-positive")
            except (TypeError, ValueError):
                errors.append(ValidationError(
                    code="BUFFER_BAD_DISTANCE",
                    message="buffer.distance must be a positive number",
                    user_friendly="缓冲区距离必须是正数。",
                    step_id=step_id,
                    field="distance",
                ))

        if op == "reproject":
            crs = params.get("target_crs")
            if not isinstance(crs, str) or not re.match(r"^EPSG:\d+$", crs.strip(), re.I):
                errors.append(ValidationError(
                    code="REPROJECT_BAD_CRS",
                    message=f"invalid target_crs: {crs}",
                    user_friendly="目标坐标系必须形如 EPSG:4326。",
                    step_id=step_id,
                    field="target_crs",
                ))

        if op == "choropleth":
            classes = params.get("classes", 5)
            try:
                classes_value = int(classes)
                if not 2 <= classes_value <= 12:
                    raise ValueError("out of range")
            except (TypeError, ValueError):
                errors.append(ValidationError(
                    code="CHOROPLETH_BAD_CLASSES",
                    message="choropleth.classes must be int in [2,12]",
                    user_friendly="分级数必须是 2 到 12 之间的整数。",
                    step_id=step_id,
                    field="classes",
                ))
            method = params.get("method", "jenks")
            if isinstance(method, str) and method.strip().lower() not in ALLOWED_CLASSIFY_METHODS:
                errors.append(ValidationError(
                    code="CHOROPLETH_BAD_METHOD",
                    message=f"unknown classification method: {method}",
                    user_friendly=f"暂不支持的分级方法：{method}。",
                    step_id=step_id,
                    field="method",
                ))

        if op == "calculate_field":
            field_name = params.get("field")
            if isinstance(field_name, str) and not re.match(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$", field_name):
                errors.append(ValidationError(
                    code="CALCULATE_FIELD_BAD_NAME",
                    message=f"invalid field name: {field_name}",
                    user_friendly="字段名只能包含字母、数字、下划线，且不能以数字开头。",
                    step_id=step_id,
                    field="field",
                ))

        return errors

    # -- references ----------------------------------------------------

    def _validate_references(
        self,
        step: Dict[str, Any],
        valid_step_outputs: Dict[str, Set[str]],
    ) -> List[ValidationError]:
        errors: List[ValidationError] = []
        step_id = str(step.get("id", ""))
        params = step.get("params", {}) or {}
        for raw in _walk_strings(params):
            if not _looks_like_reference(raw):
                continue
            ref = _parse_reference(raw)
            if ref is None:
                errors.append(ValidationError(
                    code="REFERENCE_BAD_SYNTAX",
                    message=f"bad reference: {raw}",
                    user_friendly=f"步骤 {step_id} 包含格式不正确的引用 {raw}。",
                    step_id=step_id,
                ))
                continue
            target_step, target_key = ref
            if target_step == step_id:
                errors.append(ValidationError(
                    code="REFERENCE_SELF",
                    message=f"step {step_id} references itself",
                    user_friendly=f"步骤 {step_id} 不能引用自身。",
                    step_id=step_id,
                ))
                continue
            if target_step not in valid_step_outputs:
                errors.append(ValidationError(
                    code="REFERENCE_UNKNOWN_STEP",
                    message=f"reference {raw} points to unknown step",
                    user_friendly=f"步骤 {step_id} 引用了不存在的步骤 {target_step}。",
                    step_id=step_id,
                ))
                continue
            if target_key not in valid_step_outputs[target_step]:
                errors.append(ValidationError(
                    code="REFERENCE_UNKNOWN_KEY",
                    message=f"reference {raw} points to unknown output key",
                    user_friendly=(
                        f"步骤 {step_id} 引用了步骤 {target_step} 不存在的输出 {target_key}。"
                    ),
                    step_id=step_id,
                ))
        return errors

    # -- helpers --------------------------------------------------------

    @staticmethod
    def _infer_output_keys(op: str, output_bindings: Any) -> Set[str]:
        """Infer the set of valid ``${stepId.key}`` keys an op produces."""
        defaults: Dict[str, Set[str]] = {
            "load_layer": {"layer", "extent", "crs", "path"},
            "inspect_layer": {"layer", "summary", "extent", "crs", "fields"},
            "reproject": {"layer", "extent", "crs", "path"},
            "fix_geometries": {"layer", "extent", "crs", "path"},
            "filter_features": {"layer", "extent", "crs", "path", "count"},
            "calculate_field": {"layer", "extent", "crs", "path"},
            "buffer": {"layer", "extent", "crs", "path"},
            "choropleth": {"layer", "geojson", "style", "extent", "crs", "path"},
            "aggregate_stats": {"layer", "stats", "path"},
            "export_geojson": {"geojson", "path", "extent", "crs"},
            "export_style_json": {"style", "path"},
            "export_map_png": {"png", "path", "extent", "crs"},
        }
        keys = set(defaults.get(op, {"path"}))
        if isinstance(output_bindings, dict):
            for alias_key in output_bindings.keys():
                keys.add(str(alias_key))
        return keys

    @staticmethod
    def _normalize_step(step: Dict[str, Any]) -> Dict[str, Any]:
        """Ensure step has the expected canonical shape."""
        return {
            "id": str(step["id"]).strip(),
            "op": str(step["op"]).strip(),
            "params": dict(step.get("params") or {}),
            "depends_on": list(step.get("depends_on") or []),
            "output_bindings": dict(step.get("output_bindings") or {}),
            "on_error": str(step.get("on_error") or "abort"),
        }


def validate_workflow(workflow: Any) -> ValidationResult:
    """Module-level shortcut returning a :class:`ValidationResult`."""
    return WorkflowValidator().validate(workflow)
