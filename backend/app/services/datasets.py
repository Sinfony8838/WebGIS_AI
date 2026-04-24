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


def _slugify_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return cleaned or "dataset"


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
            layer = self._import_geojson(file_path, dataset_name or Path(filename).stem)
        elif suffix == ".csv":
            layer = self._import_csv(file_path, dataset_name or Path(filename).stem, lat_field=lat_field, lon_field=lon_field)
        elif suffix == ".zip":
            layer = self._import_shapefile_zip(file_path, dataset_name or Path(filename).stem)
        elif suffix in {".png", ".jpg", ".jpeg"}:
            layer = self._import_image_overlay(
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
        }

    def _import_geojson(self, file_path: Path, display_name: str) -> LayerRecord:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        collection = self._normalize_feature_collection(payload)
        geometry_type = self._infer_geometry_type(collection.get("features", []))
        return LayerRecord.create(
            layer_id=f"upload_{file_path.stem}",
            name=display_name,
            kind="vector",
            source="upload",
            geometry_type=geometry_type,
            data=collection,
            metadata={"source_file": file_path.name, "feature_count": len(collection.get("features", []))},
            style={"labelField": "name"},
            z_index=40,
        )

    def _import_csv(self, file_path: Path, display_name: str, lat_field: str = "", lon_field: str = "") -> LayerRecord:
        text = file_path.read_text(encoding="utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(text)))
        if not rows:
            raise ValueError("CSV file is empty")
        field_lookup = {field.strip().lower(): field for field in rows[0].keys() if field}
        latitude_field = lat_field.strip() or field_lookup.get("lat") or field_lookup.get("latitude") or field_lookup.get("y")
        longitude_field = lon_field.strip() or field_lookup.get("lon") or field_lookup.get("lng") or field_lookup.get("longitude") or field_lookup.get("x")
        if not latitude_field or not longitude_field:
            raise ValueError("CSV upload requires lat/lon fields")
        if latitude_field not in rows[0] or longitude_field not in rows[0]:
            raise ValueError("CSV upload lat/lon fields do not exist in the file")

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
        return LayerRecord.create(
            layer_id=f"upload_{file_path.stem}",
            name=display_name,
            kind="vector",
            source="upload",
            geometry_type="Point",
            data=collection,
            metadata={
                "source_file": file_path.name,
                "feature_count": len(features),
                "lat_field": latitude_field,
                "lon_field": longitude_field,
            },
            style={"labelField": "name"},
            z_index=42,
        )

    def _import_image_overlay(
        self,
        file_path: Path,
        display_name: str,
        image_bounds: Iterable[float],
    ) -> LayerRecord:
        bounds = [float(value) for value in image_bounds]
        if len(bounds) != 4:
            raise ValueError("Image overlay upload requires west,south,east,north bounds")
        return LayerRecord.create(
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
            },
            opacity=0.88,
            z_index=30,
        )

    def _import_shapefile_zip(self, file_path: Path, display_name: str) -> LayerRecord:
        spec = importlib.util.find_spec("shapefile")
        if spec is None:
            return LayerRecord.create(
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
                },
                z_index=5,
            )

        import shapefile  # type: ignore

        extract_dir = file_path.parent / f"{file_path.stem}_extract_{uuid4().hex[:8]}"
        with zipfile.ZipFile(file_path) as archive:
            self._safe_extract_zip(archive, extract_dir)

        try:
            shp_paths = list(extract_dir.rglob("*.shp"))
            if not shp_paths:
                raise ValueError("ZIP file does not contain a .shp file")
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
        return LayerRecord.create(
            layer_id=f"upload_{file_path.stem}",
            name=display_name,
            kind="vector",
            source="upload",
            geometry_type=self._infer_geometry_type(collection.get("features", [])),
            data=collection,
            metadata={"source_file": file_path.name, "feature_count": len(features)},
            z_index=40,
        )

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
