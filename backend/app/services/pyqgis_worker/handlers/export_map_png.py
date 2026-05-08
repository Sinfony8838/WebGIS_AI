"""Render a basic PNG snapshot of one or more layers.

For v1 we use ``QgsMapSettings`` + ``QgsMapRendererCustomPainterJob`` which
works headless without a real layout. The rendering is intentionally simple
(transparent background, no legend / scale bar) — richer layout export is
deferred to ``export_layout_pdf``.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

from ..errors import WorkflowExecutionError
from ..workspace import Workspace
from . import _common


def _resolve_layer_list(workspace: Workspace, layer_refs: Any) -> List[Any]:
    if not isinstance(layer_refs, list):
        layer_refs = [layer_refs]
    layers = []
    for ref in layer_refs:
        layer = _common.require_layer(workspace, ref)
        if layer is not None:
            layers.append(layer)
    if not layers:
        raise WorkflowExecutionError(
            code="VALIDATION_FAILED",
            message="export_map_png needs at least one layer",
            user_friendly="导出地图至少需要一个图层。",
        )
    return layers


def execute(params: Dict[str, Any], workspace: Workspace) -> Dict[str, Any]:
    resolved = workspace.resolve_reference(params)
    layers = _resolve_layer_list(workspace, resolved.get("layers"))
    width = int(resolved.get("width", 1200) or 1200)
    height = int(resolved.get("height", 900) or 900)
    name = str(resolved.get("name") or "map")
    extent_param = resolved.get("extent")
    background_hex = str(resolved.get("background") or "#ffffff")

    try:
        from qgis.core import (  # type: ignore
            QgsMapSettings,
            QgsMapRendererCustomPainterJob,
            QgsRectangle,
            QgsCoordinateReferenceSystem,
        )
        from qgis.PyQt.QtCore import QSize  # type: ignore
        from qgis.PyQt.QtGui import QImage, QPainter, QColor  # type: ignore
    except Exception as exc:
        raise WorkflowExecutionError(
            code="QGIS_ENV_NOT_READY",
            message=f"failed to import QGIS PyQt: {exc}",
            user_friendly="缺少 QGIS PyQt 渲染依赖，无法导出 PNG。",
        ) from exc

    settings = QgsMapSettings()
    settings.setLayers(layers)
    settings.setOutputSize(QSize(width, height))
    settings.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:4326"))

    if isinstance(extent_param, list) and len(extent_param) == 4:
        rect = QgsRectangle(*[float(v) for v in extent_param])
    else:
        # Use union of all layer extents
        rect = layers[0].extent()
        for layer in layers[1:]:
            rect.combineExtentWith(layer.extent())
    settings.setExtent(rect)
    settings.setBackgroundColor(QColor(background_hex))

    image = QImage(width, height, QImage.Format_ARGB32)
    image.fill(QColor(background_hex))
    painter = QPainter(image)
    job = QgsMapRendererCustomPainterJob(settings, painter)
    job.start()
    job.waitForFinished()
    painter.end()

    output_path = workspace.alloc_output_path(name, ".png")
    if not image.save(str(output_path), "PNG"):
        raise WorkflowExecutionError(
            code="EXPORT_FAILED",
            message=f"PNG save failed at {output_path}",
            user_friendly="导出 PNG 失败。",
        )

    return {
        "png": str(output_path),
        "png_relative": workspace.relative(output_path),
        "path": str(output_path),
        "extent": [rect.xMinimum(), rect.yMinimum(), rect.xMaximum(), rect.yMaximum()],
        "crs": "EPSG:4326",
        "width": width,
        "height": height,
    }
