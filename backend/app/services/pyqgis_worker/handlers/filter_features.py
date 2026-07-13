"""Filter features by a QGIS expression and return a new memory layer."""
from __future__ import annotations

from typing import Any, Dict

from ..errors import WorkflowExecutionError
from ..workspace import Workspace
from . import _common


def execute(params: Dict[str, Any], workspace: Workspace) -> Dict[str, Any]:
    resolved = workspace.resolve_reference(params)
    layer = _common.require_layer(workspace, resolved.get("input"))
    expression = str(resolved.get("expression") or "").strip()
    if not expression:
        raise WorkflowExecutionError(
            code="VALIDATION_FAILED",
            message="filter_features.expression is empty",
            user_friendly="过滤表达式不能为空。",
        )

    import processing  # type: ignore

    try:
        result = processing.run(
            "native:extractbyexpression",
            {"INPUT": layer, "EXPRESSION": expression, "OUTPUT": "memory:filtered"},
        )
    except Exception as exc:
        raise WorkflowExecutionError(
            code="PROCESSING_FAILED",
            message=f"native:extractbyexpression failed: {exc}",
            user_friendly=f"过滤表达式无效或执行失败：{expression}",
            details={"expression": expression, "reason": repr(exc)},
        ) from exc

    out = result["OUTPUT"]
    alias = _common.make_layer_alias(workspace, "filter_features", out)
    return {
        "layer": alias,
        "crs": out.crs().authid() if out.crs().isValid() else "",
        "extent": _common.layer_extent_to_list(out),
        "fields": _common.layer_field_names(out),
        "count": out.featureCount(),
        "feature_count": out.featureCount(),
    }
