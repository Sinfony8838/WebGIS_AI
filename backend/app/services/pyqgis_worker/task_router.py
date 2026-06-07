"""Dispatcher mapping ``op`` strings to handler callables.

Imported only inside the worker subprocess. Each handler module exposes an
``execute(params: dict, workspace: Workspace) -> dict`` function that returns
the standard ``outputs`` dict (no QGIS objects allowed, only paths/numbers/
strings/dicts).
"""
from __future__ import annotations

from typing import Any, Callable, Dict

from .errors import WorkflowExecutionError
from .workspace import Workspace


def _load_handlers() -> Dict[str, Callable[[Dict[str, Any], Workspace], Dict[str, Any]]]:
    """Lazily import handlers so missing optional ones don't break the worker."""
    from .handlers import (
        load_layer,
        inspect_layer,
        reproject,
        fix_geometries,
        filter_features,
        calculate_field,
        buffer as buffer_handler,
        choropleth,
        aggregate_stats,
        export_geojson,
        export_style_json,
        export_map_png,
        clip as clip_handler,
        intersection as intersection_handler,
        spatial_join as spatial_join_handler,
        classify as classify_handler,
    )

    return {
        "load_layer": load_layer.execute,
        "inspect_layer": inspect_layer.execute,
        "reproject": reproject.execute,
        "fix_geometries": fix_geometries.execute,
        "filter_features": filter_features.execute,
        "calculate_field": calculate_field.execute,
        "buffer": buffer_handler.execute,
        "choropleth": choropleth.execute,
        "aggregate_stats": aggregate_stats.execute,
        "export_geojson": export_geojson.execute,
        "export_style_json": export_style_json.execute,
        "export_map_png": export_map_png.execute,
        "clip": clip_handler.execute,
        "intersection": intersection_handler.execute,
        "spatial_join": spatial_join_handler.execute,
        "classify": classify_handler.execute,
    }


_handlers_cache: Dict[str, Callable[[Dict[str, Any], Workspace], Dict[str, Any]]] | None = None


def dispatch(op: str, params: Dict[str, Any], workspace: Workspace) -> Dict[str, Any]:
    """Resolve ``op`` and execute the handler. Returns outputs dict."""
    global _handlers_cache
    if _handlers_cache is None:
        _handlers_cache = _load_handlers()
    handler = _handlers_cache.get(op)
    if handler is None:
        raise WorkflowExecutionError(
            code="UNKNOWN_OP",
            message=f"no handler registered for op: {op}",
            user_friendly=f"暂不支持的工作流操作：{op}",
            details={"op": op},
        )
    return handler(params, workspace)
