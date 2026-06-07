"""Fix invalid geometries via QGIS native:fixgeometries."""
from __future__ import annotations

from typing import Any, Dict

from ..errors import WorkflowExecutionError
from ..workspace import Workspace
from . import _common


def execute(params: Dict[str, Any], workspace: Workspace) -> Dict[str, Any]:
    resolved = workspace.resolve_reference(params)
    layer = _common.require_layer(workspace, resolved.get("input"))

    import processing  # type: ignore

    try:
        result = processing.run(
            "native:fixgeometries",
            {"INPUT": layer, "OUTPUT": "memory:fixed"},
        )
    except Exception as exc:
        raise WorkflowExecutionError(
            code="PROCESSING_FAILED",
            message=f"native:fixgeometries failed: {exc}",
            user_friendly="几何修复失败。",
            details={"reason": repr(exc)},
        ) from exc

    out = result["OUTPUT"]
    alias = _common.make_layer_alias(workspace, "fix_geometries", out)
    return {
        "layer": alias,
        "crs": out.crs().authid() if out.crs().isValid() else "",
        "extent": _common.layer_extent_to_list(out),
        "fields": _common.layer_field_names(out),
        "feature_count": out.featureCount(),
    }
