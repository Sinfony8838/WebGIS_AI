from __future__ import annotations

import csv
import datetime as _datetime
import importlib.util
import io
import json
import math
import re
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from uuid import uuid4

from ..config import AppConfig
from ..models import LayerRecord
from ..store import RuntimeStore
from . import crs_detector, crs_reprojector


# Project-wide working CRS. All vector geometry stored in LayerRecord.data
# is normalised to this CRS; LayerRecord.metadata.source_crs preserves the
# original for traceability and re-export.
PROJECT_WORKING_CRS = "EPSG:4326"

# Safety limits for ZIP extraction (defence against decompression bombs).
MAX_ZIP_ENTRIES = 2000
MAX_ZIP_UNCOMPRESSED_BYTES = 512 * 1024 * 1024  # 512 MB total uncompressed
MAX_SINGLE_ENTRY_BYTES = 256 * 1024 * 1024  # 256 MB per entry

# Encoding fallbacks for text uploads. utf-8-sig also strips a UTF-8 BOM;
# gb18030 is a superset of GBK/GB2312 and covers Chinese Excel exports.
_TEXT_ENCODINGS = ("utf-8-sig", "gb18030")

# Canonical + Chinese aliases accepted for CSV coordinate columns.
_LAT_FIELD_ALIASES = ("lat", "latitude", "y", "纬度")
_LON_FIELD_ALIASES = ("lon", "lng", "longitude", "x", "经度")


def _slugify_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return cleaned or "dataset"


def _decode_text(raw_bytes: bytes) -> Tuple[str, str]:
    """Decode upload bytes to text using the shared encoding fallback chain.

    Returns ``(text, encoding_name)``. UTF-16 (Excel "Unicode 文本" exports)
    is honoured via its BOM; otherwise UTF-8 (with BOM) is tried first and
    GB18030 second. latin-1 is the never-fails last resort so a slightly
    broken byte still imports instead of dying with a traceback.
    """
    if raw_bytes.startswith(b"\xff\xfe") or raw_bytes.startswith(b"\xfe\xff"):
        return raw_bytes.decode("utf-16"), "utf-16"
    for encoding in _TEXT_ENCODINGS:
        try:
            return raw_bytes.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw_bytes.decode("latin-1"), "latin-1"


def _json_safe(value: Any) -> Any:
    """Coerce DBF-sourced values into JSON-serialisable equivalents."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, (_datetime.date, _datetime.datetime)):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


class CrsAssumptionError(ValueError):
    """Raised when a CSV upload contains numeric coordinates that clearly
    are NOT EPSG:4326 lon/lat (e.g. projected meters). We surface this
    instead of silently dropping all rows so the user knows why.
    """


@dataclass
class _ImportOutcome:
    """Result of an in-memory import build, ready to persist.

    Import builders validate and convert everything BEFORE any byte is
    written under ``uploads/`` — a failed import leaves no half-finished
    files behind. ``sibling_geojson_collection`` (if set) is written next to
    the stored upload once validation has passed, so the PyQGIS worker can
    ingest the layer via OGR.
    """

    layer: LayerRecord
    crs_report: Dict[str, Any]
    message: str = ""
    row_report: Optional[Dict[str, Any]] = None
    feature_report: Optional[Dict[str, Any]] = None
    # Written as a streamed ``json.dump`` next to the stored upload after
    # validation — no whole-document string copy for large datasets.
    sibling_geojson_collection: Optional[Dict[str, Any]] = None


class DatasetService:
    def __init__(self, config: AppConfig, store: RuntimeStore):
        self.config = config
        self.store = store

    def import_upload(
        self,
        project_id: str,
        filename: str,
        raw_bytes: bytes,
        dataset_name: str = "",
        lat_field: str = "",
        lon_field: str = "",
        image_bounds: Optional[Iterable[float]] = None,
    ) -> Dict[str, Any]:
        suffix = Path(filename).suffix.lower()
        safe_name = _slugify_filename(filename)
        display_name = (dataset_name or Path(filename).stem).strip() or safe_name

        # Phase 1 — parse, validate and convert fully in memory. Any
        # exception below aborts the import without touching the uploads
        # directory, so a failed upload can never leave a half-registered
        # layer or orphan file behind.
        if suffix in {".geojson", ".json"}:
            outcome = self._build_geojson_import(raw_bytes, display_name)
        elif suffix == ".csv":
            outcome = self._build_csv_import(raw_bytes, display_name, lat_field=lat_field, lon_field=lon_field)
        elif suffix == ".zip":
            outcome = self._build_shapefile_zip_import(raw_bytes, display_name)
        elif suffix in {".png", ".jpg", ".jpeg"}:
            outcome = self._build_image_overlay_import(raw_bytes, display_name, image_bounds or [])
        else:
            raise ValueError(
                f"不支持的文件类型：{suffix or filename}。支持 GeoJSON（.geojson/.json）、"
                "CSV、ZIP Shapefile 和 PNG/JPG 图片叠加。"
            )

        # Phase 2 — everything validated; persist the upload + siblings.
        upload_dir = self.config.project_upload_dir(project_id)
        file_path = self.config.unique_path(upload_dir, safe_name)
        file_path.write_bytes(raw_bytes)
        if outcome.sibling_geojson_collection is not None:
            with file_path.with_suffix(".geojson").open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(outcome.sibling_geojson_collection, handle, ensure_ascii=False)

        layer = outcome.layer
        layer.layer_id = f"upload_{file_path.stem}"
        layer.metadata["source_file"] = file_path.name
        layer.metadata["qgis_source_file"] = file_path.with_suffix(".geojson").name

        # Explicit duplicate-import behaviour: the stored file is kept in
        # full (both uploads remain available on disk) and the new layer is
        # renamed “名称 (2)”、“(3)”… so the layer list never shows two
        # indistinguishable entries.
        project = self.store.get_project(project_id)
        existing_names = {existing.name for existing in project.layers}
        if layer.name in existing_names:
            counter = 2
            renamed = f"{layer.name} ({counter})"
            while renamed in existing_names:
                counter += 1
                renamed = f"{layer.name} ({counter})"
            layer.metadata["duplicate_import"] = True
            layer.metadata["renamed_from"] = layer.name
            outcome.message += f"；项目中已存在同名图层，本次导入已命名为“{renamed}”。"
            layer.name = renamed

        self.store.upsert_layer(project_id, layer)
        self.store.add_recent_action(
            project_id,
            "导入教学数据",
            f"已导入 {layer.name}",
            status="success",
            metadata={"layer_id": layer.layer_id, "source_file": filename},
        )
        result: Dict[str, Any] = {
            "layer": layer.to_dict(),
            "artifact": {
                "artifact_type": "dataset_import",
                "title": f"{layer.name} 数据导入",
                "path": str(file_path),
                "metadata": {"public_url": self.config.public_url_for_path(file_path), "source_file": filename},
            },
            "crs": outcome.crs_report,
            "message": outcome.message,
        }
        if outcome.row_report is not None:
            result["row_report"] = outcome.row_report
        if outcome.feature_report is not None:
            result["feature_report"] = outcome.feature_report
        return result

    # ------------------------------------------------------------------
    # GeoJSON
    # ------------------------------------------------------------------

    def _build_geojson_import(self, raw_bytes: bytes, display_name: str) -> _ImportOutcome:
        text, encoding_used = _decode_text(raw_bytes)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"GeoJSON 解析失败：文件不是有效的 JSON（第 {exc.lineno} 行第 {exc.colno} 列附近：{exc.msg}）。"
            ) from exc
        if not isinstance(payload, (dict, list)):
            raise ValueError("GeoJSON 内容需要是 Feature 或 FeatureCollection 对象。")

        explicit_crs = crs_detector.detect_geojson_crs(payload)
        # detection_method tracks how we arrived at source_crs for the UI.
        detection_method = "geojson_crs_member" if explicit_crs else "implicit_wgs84"
        source_crs = explicit_crs or PROJECT_WORKING_CRS

        collection = self._normalize_feature_collection(payload)
        # Strip the legacy crs member so the stored payload is unambiguous.
        collection.pop("crs", None)

        raw_features = collection.get("features") or []
        valid_features: List[Dict[str, Any]] = []
        skip_reasons: Dict[str, int] = {}
        for feature in raw_features:
            if not isinstance(feature, dict):
                skip_reasons["非法要素（不是对象）"] = skip_reasons.get("非法要素（不是对象）", 0) + 1
                continue
            if not isinstance(feature.get("geometry"), dict):
                skip_reasons["缺失几何（geometry 为 null）"] = skip_reasons.get("缺失几何（geometry 为 null）", 0) + 1
                continue
            valid_features.append(feature)
        if not valid_features:
            raise ValueError(
                "GeoJSON 不包含任何有效要素：features 为空，或全部要素缺少 geometry。"
            )
        collection["features"] = valid_features

        collection, report = crs_reprojector.reproject_feature_collection(
            collection,
            source_crs=source_crs if explicit_crs else None,
            target_crs=PROJECT_WORKING_CRS,
        )
        # Re-attach detection metadata to the report (reprojector only knows source/target).
        report.source_crs = source_crs
        self._annotate_range_diagnostics(report, explicit_crs, collection)

        crs_converted = report.reprojected
        stored_crs = PROJECT_WORKING_CRS if (crs_converted or source_crs == PROJECT_WORKING_CRS) else source_crs

        geometry_type = self._infer_geometry_type(valid_features)
        feature_report = {
            "total_features": len(raw_features),
            "imported_features": len(valid_features),
            "skipped_features": len(raw_features) - len(valid_features),
            "skip_reasons": skip_reasons,
        }
        message = self._compose_feature_message(
            feature_report, source_crs, stored_crs, crs_converted, report
        )
        layer = LayerRecord.create(
            layer_id=f"upload_pending",
            name=display_name,
            kind="vector",
            source="upload",
            geometry_type=geometry_type,
            visible=stored_crs == PROJECT_WORKING_CRS,
            data=collection,
            metadata={
                "feature_count": len(valid_features),
                "source_crs": source_crs,
                "crs_detection": detection_method,
                "stored_crs": stored_crs,
                "crs_converted": crs_converted,
                "encoding": encoding_used,
            },
            style={"labelField": "name"},
            z_index=40,
        )
        return _ImportOutcome(
            layer=layer,
            crs_report=self._compose_crs_report(report, detection_method),
            message=message,
            feature_report=feature_report,
        )

    # ------------------------------------------------------------------
    # CSV
    # ------------------------------------------------------------------

    def _build_csv_import(
        self,
        raw_bytes: bytes,
        display_name: str,
        lat_field: str = "",
        lon_field: str = "",
    ) -> _ImportOutcome:
        text, encoding_used = _decode_text(raw_bytes)
        rows_iter = csv.reader(io.StringIO(text))
        try:
            header = [str(cell).strip() for cell in next(rows_iter)]
        except StopIteration:
            raise ValueError("CSV 文件为空或缺少表头行。") from None
        if not any(header):
            raise ValueError("CSV 表头行为空，无法识别字段。")

        lookup = {name.lower(): index for index, name in enumerate(header) if name}
        latitude_field = lat_field.strip() or self._pick_field(lookup, _LAT_FIELD_ALIASES)
        longitude_field = lon_field.strip() or self._pick_field(lookup, _LON_FIELD_ALIASES)
        if not latitude_field or not longitude_field:
            raise ValueError(
                "CSV 导入需要经纬度字段：请让文件包含 lat/lon（或 纬度/经度）列，"
                "或在导入选项中手动指定字段名。"
            )
        lat_index = lookup.get(latitude_field.strip().lower())
        lon_index = lookup.get(longitude_field.strip().lower())
        if lat_index is None or lon_index is None:
            missing = [name for name, idx in ((latitude_field, lat_index), (longitude_field, lon_index)) if idx is None]
            raise ValueError(
                f"CSV 中不存在字段：{'、'.join(missing)}。文件实际字段：{header}。"
            )

        features: List[Dict[str, Any]] = []
        skip_reasons: Dict[str, int] = {}
        swap_examples: List[List[float]] = []
        projected_like_rows = 0
        total_rows = 0

        def bump(reason: str) -> None:
            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1

        for row in rows_iter:
            if not row or all(not str(cell).strip() for cell in row):
                if row:
                    bump("空行")
                continue
            total_rows += 1
            needed = max(lat_index, lon_index) + 1
            cells = [str(cell).strip() for cell in row]
            if len(cells) < needed:
                cells.extend([""] * (needed - len(cells)))
            lon_text = cells[lon_index]
            lat_text = cells[lat_index]
            if not lon_text or not lat_text:
                bump("坐标缺失")
                continue
            try:
                lon = float(lon_text)
                lat = float(lat_text)
            except ValueError:
                bump("坐标不是有效数字")
                continue
            if math.isnan(lon) or math.isnan(lat) or math.isinf(lon) or math.isinf(lat):
                bump("坐标不是有效数字")
                continue
            verdict = crs_detector.classify_coordinate_pair(lon, lat)
            if verdict != crs_detector.COORD_OK:
                if abs(lon) >= 1000 or abs(lat) >= 1000:
                    projected_like_rows += 1
                    bump("坐标超出经纬度范围（疑似投影坐标）")
                elif verdict == crs_detector.COORD_SUSPECTED_SWAP:
                    if len(swap_examples) < 3:
                        swap_examples.append([lon, lat])
                    bump("疑似经纬度反置（纬度/经度列可能填反）")
                else:
                    bump("坐标超出经纬度范围")
                continue
            properties = {
                name: _json_safe(value)
                for name, value in zip(header, cells[: len(header)])
                if name
            }
            properties["__fillColor"] = "#46b5d1"
            properties["__radius"] = 7
            if not properties.get("name"):
                properties["name"] = f"记录 {total_rows}"
            features.append(
                {
                    "type": "Feature",
                    "properties": properties,
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                }
            )

        row_report = {
            "total_rows": total_rows,
            "imported_rows": len(features),
            "skipped_rows": total_rows - len(features),
            "skip_reasons": skip_reasons,
            "encoding": encoding_used,
            "lat_field": latitude_field,
            "lon_field": longitude_field,
        }
        if total_rows == 0:
            raise ValueError("CSV 文件没有数据行（仅表头或空文件）。")
        if not features:
            self._raise_csv_all_skipped(row_report, swap_examples, projected_like_rows)

        collection = {"type": "FeatureCollection", "features": features}
        report = crs_reprojector.ReprojectionReport(
            source_crs=PROJECT_WORKING_CRS,
            target_crs=PROJECT_WORKING_CRS,
            reprojected=False,
        )
        report.features_total = len(features)
        report.features_untouched = len(features)
        # Write a sibling GeoJSON so the PyQGIS worker can ingest the points
        # via OGR (raw CSV would need a CSVT sidecar).
        message = self._compose_row_message(row_report, PROJECT_WORKING_CRS, PROJECT_WORKING_CRS, False, report)
        layer = LayerRecord.create(
            layer_id="upload_pending",
            name=display_name,
            kind="vector",
            source="upload",
            geometry_type="Point",
            data=collection,
            metadata={
                "feature_count": len(features),
                "lat_field": latitude_field,
                "lon_field": longitude_field,
                "source_crs": PROJECT_WORKING_CRS,
                "crs_detection": "csv_lonlat_validated",
                "stored_crs": PROJECT_WORKING_CRS,
                "crs_converted": False,
                "encoding": encoding_used,
            },
            style={"labelField": "name"},
            z_index=42,
        )
        return _ImportOutcome(
            layer=layer,
            crs_report=self._compose_crs_report(report, "csv_lonlat_validated"),
            message=message,
            row_report=row_report,
            sibling_geojson_collection=collection,
        )

    # ------------------------------------------------------------------
    # Image overlay
    # ------------------------------------------------------------------

    def _build_image_overlay_import(
        self,
        raw_bytes: bytes,
        display_name: str,
        image_bounds: Iterable[float],
    ) -> _ImportOutcome:
        try:
            bounds = [float(value) for value in image_bounds]
        except (TypeError, ValueError):
            raise ValueError("图片叠加边界需要是数字（west,south,east,north）。") from None
        if len(bounds) != 4:
            raise ValueError(
                "图片叠加需要 west,south,east,north 四个边界值（经纬度）。"
            )
        west, south, east, north = bounds
        if not all(math.isfinite(value) for value in bounds):
            raise ValueError("图片叠加边界需要是有限数字。")
        if not (-180.0 <= west <= 180.0 and -180.0 <= east <= 180.0):
            raise ValueError("东西边界超出经度范围（-180 到 180）。")
        if not (-90.0 <= south <= 90.0 and -90.0 <= north <= 90.0):
            raise ValueError("南北边界超出纬度范围（-90 到 90）。")
        if west >= east:
            raise ValueError("西界必须小于东界。")
        if south >= north:
            raise ValueError("南界必须小于北界。")
        # Image overlays are always interpreted in EPSG:4326 (bounds = lon/lat).
        # We surface this explicitly so the UI shows it was an assumption.
        report = crs_reprojector.ReprojectionReport(
            source_crs=PROJECT_WORKING_CRS,
            target_crs=PROJECT_WORKING_CRS,
            reprojected=False,
        )
        layer = LayerRecord.create(
            layer_id="upload_pending",
            name=display_name,
            kind="raster",
            source="upload",
            geometry_type="Image",
            data={},
            metadata={
                "bounds": bounds,
                "source_crs": PROJECT_WORKING_CRS,
                "crs_detection": "image_bounds_assumed_wgs84",
                "stored_crs": PROJECT_WORKING_CRS,
                "crs_converted": False,
            },
            opacity=0.88,
            z_index=30,
        )
        return _ImportOutcome(
            layer=layer,
            crs_report=self._compose_crs_report(report, "image_bounds_assumed_wgs84"),
            message=f"图片叠加已导入，覆盖范围 west={west}, south={south}, east={east}, north={north}（按 WGS84 经纬度解释）。",
        )

    # ------------------------------------------------------------------
    # Shapefile ZIP
    # ------------------------------------------------------------------

    def _build_shapefile_zip_import(self, raw_bytes: bytes, display_name: str) -> _ImportOutcome:
        if importlib.util.find_spec("shapefile") is None:
            # Same "stored only" fallback as before, with CRS undetected.
            report = crs_reprojector.ReprojectionReport(
                source_crs=None,
                target_crs=PROJECT_WORKING_CRS,
                reprojected=False,
            )
            report.add_warning(
                "PYSHP_UNAVAILABLE",
                "未安装 pyshp，ZIP Shapefile 仅保存原文件，不能自动转 WebGIS 图层。",
            )
            layer = LayerRecord.create(
                layer_id="upload_pending",
                name=display_name,
                kind="vector",
                source="upload",
                geometry_type="Unknown",
                visible=False,
                data={"type": "FeatureCollection", "features": []},
                metadata={
                    "ingest_status": "stored_only",
                    "message": "ZIP Shapefile 已保存，但当前环境未安装 pyshp，无法自动转为 WebGIS 图层。",
                    "source_crs": None,
                    "crs_detection": "shapefile_undetected",
                    "stored_crs": PROJECT_WORKING_CRS,
                    "crs_converted": False,
                },
                z_index=5,
            )
            return _ImportOutcome(
                layer=layer,
                crs_report=self._compose_crs_report(report, "shapefile_undetected"),
                message="ZIP 已保存，但当前环境未安装 pyshp，无法自动解析为图层。",
            )

        import shapefile  # type: ignore

        features: List[Dict[str, Any]] = []
        skip_reasons: Dict[str, int] = {}
        detected_crs: Optional[str] = None
        detection_method = "shapefile_undetected"
        dbf_encoding = "utf-8"
        # Extract into a system temp dir so a failed import never leaves
        # extraction debris inside the project uploads directory.
        with tempfile.TemporaryDirectory(prefix="webgis_shpzip_") as temp_dir:
            extract_dir = Path(temp_dir)
            with zipfile.ZipFile(io.BytesIO(raw_bytes)) as archive:
                self._safe_extract_zip(archive, extract_dir)

            shp_paths = [
                path
                for path in extract_dir.rglob("*.shp")
                if not any(part.startswith("__MACOSX") or part.startswith(".") for part in path.parts)
            ]
            if not shp_paths:
                raise ValueError(
                    "ZIP 中未找到 .shp 文件。请确认压缩包含完整的 Shapefile（.shp/.shx/.dbf，可选 .prj）。"
                )
            if len(shp_paths) > 1:
                names = "、".join(path.name for path in shp_paths[:8])
                raise ValueError(
                    f"ZIP 中包含多个 Shapefile（{names}），无法确定要导入哪一个。"
                    "请每次只打包一个图层（同名 .shp/.shx/.dbf 文件集）。"
                )
            shp_path = shp_paths[0]
            missing = [ext for ext in (".shx", ".dbf") if not shp_path.with_suffix(ext).exists()]
            if missing:
                raise ValueError(
                    f"Shapefile 缺少配套文件：{'、'.join(missing)}。"
                    "请重新打包同名 .shp/.shx/.dbf（以及可选 .prj）后上传。"
                )
            prj_path = shp_path.with_suffix(".prj")
            if prj_path.exists():
                detected_crs = crs_detector.parse_wkt_epsg(prj_path.read_text(encoding="utf-8", errors="replace"))
            detection_method = "shapefile_prj" if detected_crs else "shapefile_no_prj_assumed_wgs84"

            features, skip_reasons, dbf_encoding = self._read_shapefile_records(shp_path)

        if not features:
            raise ValueError("Shapefile 不包含任何有效要素（记录为空或全部为空几何）。")

        collection: Dict[str, Any] = {"type": "FeatureCollection", "features": features}
        source_crs = detected_crs or PROJECT_WORKING_CRS
        # Reproject if we detected a non-WGS84 CRS. If pyproj is absent the
        # call returns the collection unchanged but adds a warning.
        collection, report = crs_reprojector.reproject_feature_collection(
            collection,
            source_crs=detected_crs,
            target_crs=PROJECT_WORKING_CRS,
        )
        report.source_crs = source_crs
        if detected_crs is None:
            report.add_warning(
                "SHAPEFILE_NO_PRJ",
                "Shapefile 缺少 .prj 文件，已按 EPSG:4326 处理。若数据实际为投影坐标，"
                "位置可能错位，请重新上传带 .prj 的版本。",
            )
        self._annotate_range_diagnostics(report, detected_crs, collection)

        crs_converted = report.reprojected
        stored_crs = PROJECT_WORKING_CRS if (crs_converted or source_crs == PROJECT_WORKING_CRS) else source_crs

        feature_report = {
            "total_features": len(features) + sum(skip_reasons.values()),
            "imported_features": len(features),
            "skipped_features": sum(skip_reasons.values()),
            "skip_reasons": skip_reasons,
        }
        message = self._compose_feature_message(
            feature_report, source_crs, stored_crs, crs_converted, report
        )
        layer = LayerRecord.create(
            layer_id="upload_pending",
            name=display_name,
            kind="vector",
            source="upload",
            geometry_type=self._infer_geometry_type(features),
            visible=stored_crs == PROJECT_WORKING_CRS,
            data=collection,
            metadata={
                "feature_count": len(features),
                "source_crs": source_crs,
                "crs_detection": detection_method,
                "stored_crs": stored_crs,
                "crs_converted": crs_converted,
                "dbf_encoding": dbf_encoding,
            },
            z_index=40,
        )
        return _ImportOutcome(
            layer=layer,
            crs_report=self._compose_crs_report(report, detection_method),
            message=message,
            feature_report=feature_report,
            sibling_geojson_collection=collection,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _read_shapefile_records(self, shp_path: Path) -> Tuple[List[Dict[str, Any]], Dict[str, int], str]:
        """Read shape records with an explicit DBF encoding probe.

        The encoding is chosen BEFORE constructing pyshp's Reader: a failed
        in-constructor decode would leak the already-opened DBF handle (the
        partial reader is kept alive by the exception traceback), which on
        Windows blocks temp-directory cleanup. We probe by decoding the DBF
        bytes ourselves — UTF-8 first, GB18030 fallback (superset of GBK,
        the classic ArcGIS 中文 code page).

        NULL shapes are skipped and counted — pyshp raises on their
        ``__geo_interface__``. Returns ``(features, skip_reasons, encoding)``.
        """
        import shapefile  # type: ignore

        encoding = self._detect_dbf_encoding(shp_path.with_suffix(".dbf"))
        reader = shapefile.Reader(str(shp_path), encoding=encoding)
        try:
            fields = [field_name[0] for field_name in reader.fields[1:]]
            features: List[Dict[str, Any]] = []
            skip_reasons: Dict[str, int] = {}
            for shape_record in reader.shapeRecords():
                try:
                    geometry = shape_record.shape.__geo_interface__
                except Exception:  # pyshp: NULL shapes cannot be GeoJSON
                    reason = "空几何（NULL Shape）"
                    skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                    continue
                properties = {
                    _json_safe(name): _json_safe(value)
                    for name, value in zip(fields, shape_record.record)
                    if name
                }
                features.append(
                    {
                        "type": "Feature",
                        "properties": properties,
                        "geometry": geometry,
                    }
                )
        except UnicodeDecodeError as exc:
            raise ValueError(
                f"Shapefile 属性表无法按 {encoding} 解码，请检查 DBF 编码。"
            ) from exc
        finally:
            # Close eagerly: on Windows an open DBF handle blocks
            # TemporaryDirectory cleanup.
            try:
                reader.close()
            except Exception:  # pragma: no cover - defensive
                pass
        return features, skip_reasons, encoding

    @staticmethod
    def _detect_dbf_encoding(dbf_path: Path) -> str:
        try:
            raw = dbf_path.read_bytes()
        except OSError:
            return "utf-8"
        for encoding in ("utf-8", "gb18030"):
            try:
                raw.decode(encoding)
                return encoding
            except UnicodeDecodeError:
                continue
        return "gb18030"

    def _annotate_range_diagnostics(
        self,
        report: crs_reprojector.ReprojectionReport,
        explicit_crs: Optional[str],
        collection: Dict[str, Any],
    ) -> None:
        """Attach soft range diagnostics to a finished reprojection.

        Range heuristics never rewrite coordinates and never upgrade an
        assumed CRS (requirement: value ranges are not proof). They only add
        an honest warning so teachers can react to mislabelled data.
        """
        degraded = {
            "PYPROJ_UNAVAILABLE",
            "PYPROJ_IMPORT_FAILED",
            "REPROJECTION_FAILED",
        }
        if any(warning["code"] in degraded for warning in report.warnings):
            # Reprojection degraded or failed — the existing warning already
            # explains that coordinates were left as-is; don't pile on.
            return
        issue = crs_detector.summarize_geojson_coord_range(collection)
        if issue is None:
            return
        example = issue.get("example")
        if report.reprojected:
            report.add_warning(
                "REPROJECTION_SUSPECT",
                f"坐标转换后仍有 {issue['out_of_range']} 组坐标超出经纬度范围"
                f"（如 {example}），源数据标注的 CRS 可能不正确，请核对。",
            )
        elif explicit_crs:
            report.add_warning(
                "COORD_RANGE_CONFLICT",
                f"文件声明为 {explicit_crs}，但有 {issue['out_of_range']} 组坐标超出经纬度范围"
                f"（如 {example}）。已保留原始数值，请核实数据。",
            )
        else:
            report.add_warning(
                "COORD_RANGE_SUSPECT",
                f"文件未声明 CRS，且有 {issue['out_of_range']} 组坐标超出经纬度范围"
                f"（如 {example}）。已按 EPSG:4326 保留原始数值、未做转换；"
                "若数据实为投影坐标，位置可能错位。",
            )

    def _raise_csv_all_skipped(
        self,
        row_report: Dict[str, Any],
        swap_examples: List[List[float]],
        projected_like_rows: int,
    ) -> None:
        if projected_like_rows > 0:
            raise CrsAssumptionError(
                "CSV 坐标看起来不是经纬度（EPSG:4326）。请先在 QGIS / ogr2ogr 中"
                "把数据转换为 WGS84 (EPSG:4326) 后再上传，或导入为 Shapefile（包含 .prj）。"
            )
        dominant = max(row_report["skip_reasons"].items(), key=lambda item: item[1])
        hint = ""
        if dominant[0].startswith("疑似经纬度反置"):
            hint = f"（例如坐标 ({swap_examples[0][0]}, {swap_examples[0][1]}) 更像“纬度在前”）。"
        raise ValueError(
            f"CSV 中没有可导入的坐标行：全部 {row_report['total_rows']} 行都被跳过，"
            f"主要原因是“{dominant[0]}”共 {dominant[1]} 行。{hint}"
            "请检查坐标列后重新上传。"
        )

    def _pick_field(self, lookup: Dict[str, int], aliases: Iterable[str]) -> Optional[str]:
        for alias in aliases:
            if alias in lookup:
                return alias
        return None

    def _compose_row_message(
        self,
        row_report: Dict[str, Any],
        source_crs: str,
        stored_crs: str,
        crs_converted: bool,
        report: crs_reprojector.ReprojectionReport,
    ) -> str:
        imported = row_report["imported_rows"]
        message = f"成功导入 {imported} 条记录"
        if row_report["skipped_rows"]:
            dominant = sorted(row_report["skip_reasons"].items(), key=lambda item: -item[1])
            detail = "、".join(f"{count} 条{reason}" for reason, count in dominant)
            message += f"，{row_report['skipped_rows']} 条被跳过（{detail}）"
        message += self._compose_crs_phrase(source_crs, stored_crs, crs_converted, report)
        return message + "。"

    def _compose_feature_message(
        self,
        feature_report: Dict[str, Any],
        source_crs: str,
        stored_crs: str,
        crs_converted: bool,
        report: crs_reprojector.ReprojectionReport,
    ) -> str:
        imported = feature_report["imported_features"]
        message = f"成功导入 {imported} 个要素"
        if feature_report["skipped_features"]:
            dominant = sorted(feature_report["skip_reasons"].items(), key=lambda item: -item[1])
            detail = "、".join(f"{count} 个{reason}" for reason, count in dominant)
            message += f"，{feature_report['skipped_features']} 个被跳过（{detail}）"
        message += self._compose_crs_phrase(source_crs, stored_crs, crs_converted, report)
        return message + "。"

    def _compose_crs_phrase(
        self,
        source_crs: str,
        stored_crs: str,
        crs_converted: bool,
        report: crs_reprojector.ReprojectionReport,
    ) -> str:
        if crs_converted:
            return f"；坐标已从 {source_crs} 转换为 {stored_crs}"
        if source_crs == stored_crs:
            return f"；坐标按 {source_crs} 处理"
        return f"；坐标保留为 {stored_crs}（未能转换为 {report.target_crs}，图层已隐藏以防错位）"

    def _compose_crs_report(
        self,
        report: crs_reprojector.ReprojectionReport,
        detection_method: str,
    ) -> Dict[str, Any]:
        payload = report.to_dict()
        payload["detection_method"] = detection_method
        return payload

    def _normalize_feature_collection(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if isinstance(payload, list):
            return {"type": "FeatureCollection", "features": payload}
        if payload.get("type") == "FeatureCollection":
            return payload
        if payload.get("type") == "Feature":
            return {"type": "FeatureCollection", "features": [payload]}
        raise ValueError("不支持的 GeoJSON 内容：需要 Feature、FeatureCollection 或要素数组。")

    def _infer_geometry_type(self, features: List[Dict[str, Any]]) -> str:
        geometry_types = {str(feature.get("geometry", {}).get("type", "")) for feature in features if feature.get("geometry")}
        if not geometry_types:
            return "Unknown"
        if len(geometry_types) == 1:
            return next(iter(geometry_types))
        return "Mixed"

    def _safe_extract_zip(self, archive: zipfile.ZipFile, target_dir: Path) -> None:
        members = archive.infolist()
        if len(members) > MAX_ZIP_ENTRIES:
            raise ValueError(
                f"ZIP 内条目数超过安全上限（{len(members)} > {MAX_ZIP_ENTRIES}），已拒绝解压。"
            )
        total_uncompressed = sum(member.file_size for member in members)
        if total_uncompressed > MAX_ZIP_UNCOMPRESSED_BYTES:
            raise ValueError(
                f"ZIP 解压后总大小超过安全上限"
                f"（{total_uncompressed // (1024 * 1024)} MB > {MAX_ZIP_UNCOMPRESSED_BYTES // (1024 * 1024)} MB），已拒绝解压。"
            )
        target_dir.mkdir(parents=True, exist_ok=True)
        resolved_target = target_dir.resolve()
        for member in members:
            if member.file_size > MAX_SINGLE_ENTRY_BYTES:
                raise ValueError(
                    f"ZIP 条目解压后过大（{member.filename}），已拒绝解压。"
                )
            member_path = (resolved_target / member.filename).resolve()
            try:
                member_path.relative_to(resolved_target)
            except ValueError as exc:
                raise ValueError(f"Unsafe ZIP entry: {member.filename}") from exc
            if member.is_dir():
                continue
            archive.extract(member, resolved_target)
