"""Calculate / add a new field via native:fieldcalculator."""
from __future__ import annotations

from typing import Any, Dict

from ..errors import WorkflowExecutionError
from ..workspace import Workspace
from . import _common


_FIELD_TYPE_MAP = {
    # processing's FieldCalculator FIELD_TYPE: 0=Float,1=Int,2=String,3=Date
    "double": 0,
    "float": 0,
    "real": 0,
    "int": 1,
    "integer": 1,
    "long": 1,
    "string": 2,
    "text": 2,
    "date": 3,
}


def execute(params: Dict[str, Any], workspace: Workspace) -> Dict[str, Any]:
    resolved = workspace.resolve_reference(params)
    layer = _common.require_layer(workspace, resolved.get("input"))
    field_name = str(resolved.get("field") or "").strip()
    expression = str(resolved.get("expression") or "").strip()
    field_type_raw = str(resolved.get("type") or "double").lower()
    field_type = _FIELD_TYPE_MAP.get(field_type_raw, 0)

    if not field_name or not expression:
        raise WorkflowExecutionError(
            code="VALIDATION_FAILED",
            message="calculate_field requires field and expression",
            user_friendly="字段计算需要字段名和表达式。",
        )

    import processing  # type: ignore

    try:
        result = processing.run(
            "native:fieldcalculator",
            {
                "INPUT": layer,
                "FIELD_NAME": field_name,
                "FIELD_TYPE": field_type,
                "FIELD_LENGTH": int(resolved.get("field_length", 20) or 20),
                "FIELD_PRECISION": int(resolved.get("field_precision", 6) or 6),
                "FORMULA": expression,
                "OUTPUT": "memory:calculated",
            },
        )
    except Exception as exc:
        raise WorkflowExecutionError(
            code="PROCESSING_FAILED",
            message=f"field calculation failed: {exc}",
            user_friendly=f"字段计算失败：{expression}",
            details={"expression": expression, "reason": repr(exc)},
        ) from exc

    out = result["OUTPUT"]
    alias = _common.make_layer_alias(workspace, "calculate_field", out)
    return {
        "layer": alias,
        "crs": out.crs().authid() if out.crs().isValid() else "",
        "extent": _common.layer_extent_to_list(out),
        "fields": _common.layer_field_names(out),
        "feature_count": out.featureCount(),
    }
