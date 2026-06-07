"""Persist a style.json blob.

Most callers should produce styles via :mod:`choropleth`; this handler exists
for cases where the caller wants to ship a pre-built style payload through
a workflow output.
"""
from __future__ import annotations

import json
from typing import Any, Dict

from ..errors import WorkflowExecutionError
from ..workspace import Workspace


def execute(params: Dict[str, Any], workspace: Workspace) -> Dict[str, Any]:
    resolved = workspace.resolve_reference(params)
    style_payload = resolved.get("input")
    if isinstance(style_payload, str):
        # if input is a path to an existing JSON, load it for re-emit
        from pathlib import Path
        candidate = Path(style_payload)
        if candidate.exists():
            try:
                style_payload = json.loads(candidate.read_text(encoding="utf-8"))
            except Exception as exc:
                raise WorkflowExecutionError(
                    code="EXPORT_FAILED",
                    message=f"failed to load style: {exc}",
                    user_friendly="样式 JSON 无效。",
                ) from exc
    if not isinstance(style_payload, dict):
        raise WorkflowExecutionError(
            code="VALIDATION_FAILED",
            message="export_style_json.input must be a style object or a json file path",
            user_friendly="export_style_json 需要样式对象。",
        )

    name = str(resolved.get("name") or "style")
    output_path = workspace.alloc_output_path(name, ".json")
    output_path.write_text(json.dumps(style_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "style": str(output_path),
        "style_relative": workspace.relative(output_path),
        "path": str(output_path),
    }
