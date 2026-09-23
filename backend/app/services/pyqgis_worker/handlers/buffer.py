"""Ground-distance buffers: ellipsoidal point circles and local AEQD for lines/areas."""
from __future__ import annotations

import math
from typing import Any, Dict

from ..errors import WorkflowExecutionError
from ..workspace import Workspace
from . import _common


def _unsupported(message: str) -> None:
    raise WorkflowExecutionError(code="CRS_NOT_SUPPORTED", message=message, user_friendly=message)


def execute(params: Dict[str, Any], workspace: Workspace) -> Dict[str, Any]:
    resolved = workspace.resolve_reference(params)
    layer = _common.require_layer(workspace, resolved.get("input"))
    distance = float(resolved.get("distance", 0))
    if not math.isfinite(distance) or distance <= 0:
        raise WorkflowExecutionError(code="VALIDATION_FAILED", message="invalid buffer distance",
                                     user_friendly="缓冲区距离必须是大于 0 的有限数值。")
    segments = max(16, min(180, int(resolved.get("segments", 16) or 16)))
    dissolve = bool(resolved.get("dissolve", False))

    from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsDistanceArea,
                           QgsFeature, QgsGeometry, QgsPointXY, QgsProject, QgsVectorLayer, QgsWkbTypes)

    if not layer.crs().isValid():
        _unsupported("输入图层缺少有效坐标系，请先指定坐标系。")
    original = layer.crs()
    geographic = QgsCoordinateReferenceSystem("EPSG:4326")
    context = QgsProject.instance().transformContext()
    to_geo = QgsCoordinateTransform(original, geographic, context)
    to_original = QgsCoordinateTransform(geographic, original, context)
    geod = QgsDistanceArea()
    geod.setSourceCrs(geographic, context)
    geod.setEllipsoid("WGS84")
    final = QgsVectorLayer("MultiPolygon", "buffered", "memory")
    final.setCrs(original)
    provider = final.dataProvider()
    provider.addAttributes(layer.fields())
    final.updateFields()
    buffered = []
    first_attributes = None

    for feature in layer.getFeatures():
        geom = QgsGeometry(feature.geometry())
        if geom.isEmpty():
            continue
        geom.transform(to_geo)
        bounds = geom.boundingBox()
        if bounds.width() > 180 or max(abs(bounds.yMinimum()), abs(bounds.yMaximum())) >= 85:
            _unsupported("当前缓冲暂不支持跨日期变更线或极区要素，请拆分区域后重试。")
        if distance > 500000:
            _unsupported("当前地表缓冲距离上限为 500 公里，请缩小分析范围。")
        if geom.type() == QgsWkbTypes.PointGeometry:
            points = geom.asMultiPoint() if geom.isMultipart() else [geom.asPoint()]
            circles = []
            for point in points:
                ring = [geod.computeSpheroidProject(QgsPointXY(point), distance, 2 * math.pi * i / (4 * segments))
                        for i in range(4 * segments)]
                ring.append(ring[0])
                circle = QgsGeometry.fromPolygonXY([ring])
                if circle.boundingBox().width() > 180 or max(abs(p.y()) for p in ring) >= 85:
                    _unsupported("缓冲结果跨越日期变更线或进入极区，请减小距离。")
                circles.append(circle)
            result = QgsGeometry.unaryUnion(circles)
        else:
            center = bounds.center()
            vertices = [QgsPointXY(p) for p in geom.vertices()]
            if max((geod.measureLine(center, p) for p in vertices), default=0) + distance > 500000:
                _unsupported("线面要素及其缓冲超出局部等距投影的 500 公里范围，请分区处理。")
            local = QgsCoordinateReferenceSystem()
            local.createFromProj(f"+proj=aeqd +lat_0={center.y()} +lon_0={center.x()} +datum=WGS84 +units=m +no_defs")
            if not local.isValid():
                _unsupported("无法建立局部等距投影。")
            geom = geom.densifyByDistance(0.05)
            geom.transform(QgsCoordinateTransform(geographic, local, context))
            result = geom.buffer(distance, segments)
            result.transform(QgsCoordinateTransform(local, geographic, context))
        result_bounds = result.boundingBox()
        if result_bounds.width() > 180 or max(abs(result_bounds.yMinimum()), abs(result_bounds.yMaximum())) >= 85:
            _unsupported("缓冲结果跨越日期变更线或进入极区，请减小距离。")
        if result.isEmpty() or not result.isGeosValid():
            raise WorkflowExecutionError(code="GEOMETRY_INVALID", message="invalid buffer result",
                                         user_friendly="缓冲结果几何无效，请检查输入范围。")
        if first_attributes is None:
            first_attributes = feature.attributes()
        buffered.append((result, feature.attributes()))

    if dissolve and buffered:
        buffered = [(QgsGeometry.unaryUnion([item[0] for item in buffered]), first_attributes)]
    for geom, attributes in buffered:
        geom.transform(to_original)
        geom.convertToMultiType()
        output = QgsFeature(final.fields())
        output.setGeometry(geom)
        output.setAttributes(attributes)
        provider.addFeatures([output])
    final.updateExtents()
    alias = _common.make_layer_alias(workspace, "buffer", final)
    return {"layer": alias, "crs": original.authid() or original.toWkt(),
            "extent": _common.layer_extent_to_list(final), "fields": _common.layer_field_names(final),
            "feature_count": final.featureCount(), "distance_m": distance,
            "buffer_method": "WGS84 geodesic points / local AEQD lines and polygons"}
