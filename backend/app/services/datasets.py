from __future__ import annotations

import csv
import importlib.util
import io
import json
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from uuid import uuid4

from ..config import AppConfig
from ..models import LayerRecord
from ..store import RuntimeStore
from . import crs_detector, crs_reprojector


# Project-wide working CRS. All vector geometry stored in LayerRecord.data
# is normalised to this CRS; LayerRecord.metadata.source_crs preserves the
# original for traceability and re-export.
PROJECT_WORKING_CRS = "EPSG:4326"


def _slugify_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return cleaned or "dataset"


class CrsAssumptionError(ValueError):
    """Raised when a CSV upload contains numeric coordinates that clearly
    are NOT EPSG:4326 lon/lat (e.g. projected meters). We surface this
    instead of silently dropping all rows so the user knows why.
    """


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
        upload_dir = self.config.project_upload_dir(project_id)
        file_path = self.config.unique_path(upload_dir, safe_name)
        file_path.write_bytes(raw_bytes)

        if suffix in {".geojson", ".json"}:
            layer, crs_report = self._import_geojson(file_path, dataset_name or Path(filename).stem)
        elif suffix == ".csv":
            layer, crs_report = self._import_csv(
                file_path,
                dataset_name or Path(filename).stem,
                lat_field=lat_field,
                lon_field=lon_field,
            )
        elif suffix == ".zip":
            layer, crs_report = self._import_shapefile_zip(file_path, dataset_name or Path(filename).stem)
        elif suffix in {".png", ".jpg", ".jpeg"}:
            layer, crs_report = self._import_image_overlay(
                file_path,
                dataset_name or Path(filename).stem,
                image_bounds=image_bounds or [],
            )
        else:
            raise ValueError(f"Unsupported upload type: {suffix}")

        self.store.upsert_layer(project_id, layer)
        self.store.add_recent_action(
            project_id,
            "导入教学数据",
            f"已导入 {layer.name}",
            status="success",
            metadata={"layer_id": layer.layer_id, "source_file": filename},
        )
        return {
            "layer": layer.to_dict(),
            "artifact": {
                "artifact_type": "dataset_import",
                "title": f"{layer.name} 数据导入",
                "path": str(file_path),
                "metadata": {"public_url": self.config.public_url_for_path(file_path), "source_file": filename},
            },
            "crs": crs_report,
        }

    # ------------------------------------------------------------------
    # GeoJSON
    # ------------------------------------------------------------------

    def _import_geojson(self, file_path: Path, display_name: str) -> tuple[LayerRecord, Dict[str, Any]]:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        explicit_crs = crs_detector.detect_geojson_crs(payload)
        # detection_method tracks how we arrived at source_crs for the UI.
        detection_method = "geojson_crs_member" if explicit_crs else "implicit_wgs84"
        source_crs = explicit_crs or PROJECT_WORKING_CRS

        collection = self._normalize_feature_collection(payload)
        # Strip the legacy crs member so the stored payload is unambiguous.
        collection.pop("crs", None)

        collection, report = crs_reprojector.reproject_feature_collection(
            collection,
            source_crs=source_crs if explicit_crs else None,
            target_crs=PROJECT_WORKING_CRS,
        )
        # Re-attach detection metadata to the report (reprojector only knows source/target).
        report.source_crs = source_crs

        geometry_type = self._infer_geometry_type(collection.get("features", []))
        layer = LayerRecord.create(
            layer_id=f"upload_{file_path.stem}",
            name=display_name,
            kind="vector",
            source="upload",
            geometry_type=geometry_type,
            data=collection,
            metadata={
                "source_file": file_path.name,
                "qgis_source_file": file_path.name,
                "feature_count": len(collection.get("features", [])),
                "source_crs": source_crs,
                "crs_detection": detection_method,
                "stored_crs": PROJECT_WORKING_CRS,
            },
            style={"labelField": "name"},
            z_index=40,
        )
        return layer, self._compose_crs_report(report, detection_method)

    # ------------------------------------------------------------------
    # CSV
    # ------------------------------------------------------------------

    def _import_csv(
        self,
        file_path: Path,
        display_name: str,
        lat_field: str = "",
        lon_field: str = "",
    ) -> tuple[LayerRecord, Dict[str, Any]]:
        text = file_path.read_text(encoding="utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(text)))
        if not rows:
            raise ValueError("CSV file is empty")
        field_lookup = {field.strip().lower(): field for field in rows[0].keys() if field}
        latitude_field = (
            lat_field.strip()
            or field_lookup.get("lat")
            or field_lookup.get("latitude")
            or field_lookup.get("y")
        )
        longitude_field = (
            lon_field.strip()
            or field_lookup.get("lon")
            or field_lookup.get("lng")
            or field_lookup.get("longitude")
            or field_lookup.get("x")
        )
        if not latitude_field or not longitude_field:
            raise ValueError("CSV upload requires lat/lon fields")
        if latitude_field not in rows[0] or longitude_field not in rows[0]:
            raise ValueError("CSV upload lat/lon fields do not exist in the file")

        # Pre-scan numeric columns: if they obviously aren't lon/lat (projected
        # meters look like ~500000), fail loud rather than silently drop every
        # row, which used to be the v1.1 behaviour.
        sample_lons: List[float] = []
        sample_lats: List[float] = []
        for row in rows[:50]:
            try:
                sample_lons.append(float(str(row[longitude_field]).strip()))
                sample_lats.append(float(str(row[latitude_field]).strip()))
            except (TypeError, ValueError):
                continue
        lon_projected = sample_lons and crs_detector.looks_like_projected_meters(sample_lons, axis="lon")
        lat_projected = sample_lats and crs_detector.looks_like_projected_meters(sample_lats, axis="lat")
        if lon_projected or lat_projected:
            raise CrsAssumptionError(
                "CSV 坐标看起来不是经纬度（EPSG:4326）。请先在 QGIS / ogr2ogr 中"
                "把数据转换为 WGS84 (EPSG:4326) 后再上传，或导入为 Shapefile（包含 .prj）。"
            )

        features = []
        for index, row in enumerate(rows, start=1):
            try:
                lon = float(str(row[longitude_field]).strip())
                lat = float(str(row[latitude_field]).strip())
            except Exception:
                continue
            if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
                continue
            properties = dict(row)
            properties["__fillColor"] = "#46b5d1"
            properties["__radius"] = 7
            if not properties.get("name"):
                properties["name"] = f"记录 {index}"
            features.append(
                {
                    "type": "Feature",
                    "properties": properties,
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                }
            )
        if not features:
            raise ValueError("CSV upload did not contain any valid coordinate rows")

        collection = {"type": "FeatureCollection", "features": features}
        report = crs_reprojector.ReprojectionReport(
            source_crs=PROJECT_WORKING_CRS,
            target_crs=PROJECT_WORKING_CRS,
            reprojected=False,
        )
        # Write a sibling GeoJSON so the PyQGIS worker can ingest the points
        # via OGR (raw CSV would need a CSVT sidecar).
        geojson_sibling = file_path.with_suffix(".geojson")
        geojson_sibling.write_text(
            json.dumps(collection, ensure_ascii=False),
            encoding="utf-8",
        )
        layer = LayerRecord.create(
            layer_id=f"upload_{file_path.stem}",
            name=display_name,
            kind="vector",
            source="upload",
            geometry_type="Point",
            data=collection,
            metadata={
                "source_file": file_path.name,
                "qgis_source_file": geojson_sibling.name,
                "feature_count": len(features),
                "lat_field": latitude_field,
                "lon_field": longitude_field,
                "source_crs": PROJECT_WORKING_CRS,
                "crs_detection": "csv_lonlat_validated",
                "stored_crs": PROJECT_WORKING_CRS,
            },
            style={"labelField": "name"},
            z_index=42,
        )
        return layer, self._compose_crs_report(report, "csv_lonlat_validated")

    # ------------------------------------------------------------------
    # Image overlay
    # ------------------------------------------------------------------

    def _import_image_overlay(
        self,
        file_path: Path,
        display_name: str,
        image_bounds: Iterable[float],
    ) -> tuple[LayerRecord, Dict[str, Any]]:
        bounds = [float(value) for value in image_bounds]
        if len(bounds) != 4:
            raise ValueError("Image overlay upload requires west,south,east,north bounds")
        # Image overlays are always interpreted in EPSG:4326 (bounds = lon/lat).
        # We surface this explicitly so the UI shows it was an assumption.
        report = crs_reprojector.ReprojectionReport(
            source_crs=PROJECT_WORKING_CRS,
            target_crs=PROJECT_WORKING_CRS,
            reprojected=False,
        )
        layer = LayerRecord.create(
            layer_id=f"upload_{file_path.stem}",
            name=display_name,
            kind="raster",
            source="upload",
            geometry_type="Image",
            data={},
            metadata={
                "asset_url": self.config.public_url_for_path(file_path),
                "bounds": bounds,
                "source_file": file_path.name,
                "source_crs": PROJECT_WORKING_CRS,
                "crs_detection": "image_bounds_assumed_wgs84",
                "stored_crs": PROJECT_WORKING_CRS,
            },
            opacity=0.88,
            z_index=30,
        )
        return layer, self._compose_crs_report(report, "image_bounds_assumed_wgs84")

    # ------------------------------------------------------------------
    # Shapefile ZIP
    # ------------------------------------------------------------------

    def _import_shapefile_zip(self, file_path: Path, display_name: str) -> tuple[LayerRecord, Dict[str, Any]]:
        spec = importlib.util.find_spec("shapefile")
        if spec is None:
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
                layer_id=f"upload_{file_path.stem}",
                name=display_name,
                kind="vector",
                source="upload",
                geometry_type="Unknown",
                visible=False,
                data={"type": "FeatureCollection", "features": []},
                metadata={
                    "source_file": file_path.name,
                    "ingest_status": "stored_only",
                    "message": "ZIP Shapefile 已保存，但当前环境未安装 pyshp，无法自动转为 WebGIS 图层。",
                    "public_url": self.config.public_url_for_path(file_path),
                    "source_crs": None,
                    "crs_detection": "shapefile_undetected",
                    "stored_crs": PROJECT_WORKING_CRS,
                },
                z_index=5,
            )
            return layer, self._compose_crs_report(report, "shapefile_undetected")

        import shapefile  # type: ignore

        extract_dir = file_path.parent / f"{file_path.stem}_extract_{uuid4().hex[:8]}"
        with zipfile.ZipFile(file_path) as archive:
            self._safe_extract_zip(archive, extract_dir)

        detected_crs: Optional[str] = None
        detection_method: str = "shapefile_undetected"
        try:
            shp_paths = list(extract_dir.rglob("*.shp"))
            if not shp_paths:
                raise ValueError("ZIP file does not contain a .shp file")
            # Detect CRS from a .prj sidecar (case-insensitive search via rglob).
            detected_crs = crs_detector.detect_shapefile_crs(extract_dir)
            if detected_crs:
                detection_method = "shapefile_prj"
            else:
                detection_method = "shapefile_no_prj_assumed_wgs84"

            reader = shapefile.Reader(str(shp_paths[0]))
            fields = [field[0] for field in reader.fields[1:]]
            features = []
            for sr in reader.shapeRecords():
                properties = {field: value for field, value in zip(fields, sr.record)}
                features.append(
                    {
                        "type": "Feature",
                        "properties": properties,
                        "geometry": sr.shape.__geo_interface__,
                    }
                )
        finally:
            shutil.rmtree(extract_dir, ignore_errors=True)

        collection = {"type": "FeatureCollection", "features": features}

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

        # Persist the converted FeatureCollection alongside the zip so the
        # PyQGIS worker's load_layer (file-path based, no /vsizip/) can
        # resolve it via upload:<pid>/<stem>.geojson. Without this, uploaded
        # shapefiles are visible on the map but unreachable from workflows.
        geojson_sibling = file_path.with_suffix(".geojson")
        geojson_sibling.write_text(
            json.dumps(collection, ensure_ascii=False),
            encoding="utf-8",
        )

        layer = LayerRecord.create(
            layer_id=f"upload_{file_path.stem}",
            name=display_name,
            kind="vector",
            source="upload",
            geometry_type=self._infer_geometry_type(collection.get("features", [])),
            data=collection,
            metadata={
                "source_file": file_path.name,
                "qgis_source_file": geojson_sibling.name,
                "feature_count": len(features),
                "source_crs": source_crs,
                "crs_detection": detection_method,
                "stored_crs": PROJECT_WORKING_CRS,
            },
            z_index=40,
        )
        return layer, self._compose_crs_report(report, detection_method)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _compose_crs_report(
        self,
        report: crs_reprojector.ReprojectionReport,
        detection_method: str,
    ) -> Dict[str, Any]:
        payload = report.to_dict()
        payload["detection_method"] = detection_method
        return payload

    def _normalize_feature_collection(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if payload.get("type") == "FeatureCollection":
            return payload
        if payload.get("type") == "Feature":
            return {"type": "FeatureCollection", "features": [payload]}
        if isinstance(payload, list):
            return {"type": "FeatureCollection", "features": payload}
        raise ValueError("Unsupported GeoJSON payload")

    def _infer_geometry_type(self, features: List[Dict[str, Any]]) -> str:
        geometry_types = {str(feature.get("geometry", {}).get("type", "")) for feature in features if feature.get("geometry")}
        if not geometry_types:
            return "Unknown"
        if len(geometry_types) == 1:
            return next(iter(geometry_types))
        return "Mixed"

    def _safe_extract_zip(self, archive: zipfile.ZipFile, target_dir: Path) -> None:
        target_dir.mkdir(parents=True, exist_ok=True)
        resolved_target = target_dir.resolve()
        for member in archive.infolist():
            member_path = (resolved_target / member.filename).resolve()
            try:
                member_path.relative_to(resolved_target)
            except ValueError as exc:
                raise ValueError(f"Unsafe ZIP entry: {member.filename}") from exc
            archive.extract(member, resolved_target)
