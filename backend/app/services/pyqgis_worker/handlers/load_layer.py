"""``load_layer`` handler.

Resolves the user-supplied dataset id / path and loads the corresponding
QGIS layer (vector or raster). Stores the layer under a worker-internal
alias and returns the alias plus on-disk path metadata.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from ..errors import WorkflowExecutionError
from ..workspace import Workspace
from . import _common


def execute(params: Dict[str, Any], workspace: Workspace) -> Dict[str, Any]:
    resolved = workspace.resolve_reference(params)
    source = resolved.get("source")
    project_id = str(resolved.get("project_id") or "")
    layer_name = str(resolved.get("layer_name") or "").strip() or None

    if isinstance(source, str):
        path = _common.resolve_dataset_path(workspace, source, project_id=project_id)
    else:
        raise WorkflowExecutionError(
            code="DATASET_NOT_FOUND",
            message="load_layer.source must be a string",
            user_friendly="数据集来源必须是字符串。",
        )

    layer = _common._load_layer_from_path(str(path))
    if layer_name:
        layer.setName(layer_name)
    alias = _common.make_layer_alias(workspace, "load_layer", layer)

    crs = layer.crs().authid() if layer.crs().isValid() else "EPSG:4326"
    return {
        "layer": alias,
        "path": str(path),
        "crs": crs,
        "extent": _common.layer_extent_to_list(layer),
        "fields": _common.layer_field_names(layer),
        "feature_count": layer.featureCount() if hasattr(layer, "featureCount") else None,
        "kind": "raster" if "Raster" in type(layer).__name__ else "vector",
    }
