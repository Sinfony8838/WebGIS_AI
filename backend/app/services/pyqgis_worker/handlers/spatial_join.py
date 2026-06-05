"""Attribute join two vector layers by spatial relationship.

Wraps ``native:joinattributesbylocation``. For each feature in ``input``,
finds features in ``join_layer`` that satisfy the given spatial predicate
and copies the join layer's attributes onto the input feature.

Phase 1.1 defaults are teacher-friendly:
- ``method = "1_to_1"`` (only the first matching join feature is used) to
  avoid silent row duplication.
- ``discard_no_match = False`` so input features without a match are kept
  (with NULLs for join fields), preserving downstream geometry continuity.
- ``predicate = "intersects"`` if not provided.

Supported predicates (str → QGIS integer code):
intersects=0, contains=1, equals=2, touches=3, overlaps=4, within=5, crosses=6.
"""
from __future__ import annotations

from typing import Any, Dict, List

from ..errors import WorkflowExecutionError
from ..workspace import Workspace
from . import _common


_PREDICATE_CODES: Dict[str, int] = {
    "intersects": 0,
    "contains": 1,
    "equals": 2,
    "touches": 3,
    "overlaps": 4,
    "within": 5,
    "crosses": 6,
}

_METHOD_CODES: Dict[str, int] = {
    "1_to_many": 0,
    "1_to_1": 1,
}

ALLOWED_PREDICATES = frozenset(_PREDICATE_CODES.keys())
ALLOWED_METHODS = frozenset(_METHOD_CODES.keys())


def _normalize_predicate(raw: Any) -> int:
    if isinstance(raw, str):
        key = raw.strip().lower()
        if key in _PREDICATE_CODES:
            return _PREDICATE_CODES[key]
    if isinstance(raw, int) and 0 <= raw <= 6:
        return raw
    raise WorkflowExecutionError(
        code="VALIDATION_FAILED",
        message=f"unsupported spatial predicate: {raw!r}",
        user_friendly=f"不支持的空间关系：{raw}",
        details={"allowed": sorted(ALLOWED_PREDICATES)},
    )


def _normalize_method(raw: Any) -> int:
    if isinstance(raw, str):
        key = raw.strip().lower()
        if key in _METHOD_CODES:
            return _METHOD_CODES[key]
    if isinstance(raw, int) and raw in (0, 1):
        return raw
    return 1  # default: 1_to_1


def execute(params: Dict[str, Any], workspace: Workspace) -> Dict[str, Any]:
    resolved = workspace.resolve_reference(params)
    input_layer = _common.require_layer(workspace, resolved.get("input"))
    join_layer = _common.require_layer(workspace, resolved.get("join_layer"))

    predicate_code = _normalize_predicate(resolved.get("predicate", "intersects"))
    method_code = _normalize_method(resolved.get("method", "1_to_1"))
    discard_no_match = bool(resolved.get("discard_no_match", False))
    raw_fields = resolved.get("fields_to_keep") or resolved.get("join_fields") or []
    if isinstance(raw_fields, str):
        raw_fields = [raw_fields]
    join_fields: List[str] = [str(f) for f in raw_fields if str(f).strip()]
    prefix = str(resolved.get("prefix") or "")

    import processing  # type: ignore

    original_crs = input_layer.crs().authid() if input_layer.crs().isValid() else "EPSG:4326"

    try:
        result = processing.run(
            "native:joinattributesbylocation",
            {
                "INPUT": input_layer,
                "JOIN": join_layer,
                "PREDICATE": [predicate_code],
                "JOIN_FIELDS": join_fields,
                "METHOD": method_code,
                "DISCARD_NONMATCHING": discard_no_match,
                "PREFIX": prefix,
                "OUTPUT": "memory:spatial_joined",
            },
        )
    except Exception as exc:
        raise WorkflowExecutionError(
            code="PROCESSING_FAILED",
            message=f"native:joinattributesbylocation failed: {exc}",
            user_friendly="空间连接失败。",
            details={"reason": repr(exc)},
        ) from exc

    joined = result["OUTPUT"]
    alias = _common.make_layer_alias(workspace, "spatial_join", joined)

    # Best-effort: surface a match count for the report panel.
    input_count = input_layer.featureCount() if hasattr(input_layer, "featureCount") else 0
    joined_count = joined.featureCount() if hasattr(joined, "featureCount") else 0
    match_count = joined_count if method_code == 1 else 0  # only meaningful for 1_to_1

    return {
        "layer": alias,
        "crs": joined.crs().authid() if joined.crs().isValid() else original_crs,
        "extent": _common.layer_extent_to_list(joined),
        "fields": _common.layer_field_names(joined),
        "feature_count": joined_count,
        "join_stats": {
            "input_features": input_count,
            "joined_features": joined_count,
            "method": "1_to_1" if method_code == 1 else "1_to_many",
            "predicate": next((k for k, v in _PREDICATE_CODES.items() if v == predicate_code), str(predicate_code)),
            "matched_features_in_1to1": match_count,
        },
    }
