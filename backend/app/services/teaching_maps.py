"""Service for managing teaching map image overlays.

Teaching maps are pre-registered textbook images (population, climate,
topography, etc.) that can be toggled on/off as semi-transparent raster
overlays on the classroom map.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import AppConfig
from ..models import LayerRecord
from ..store import RuntimeStore


TEACHING_MAP_LAYER_PREFIX = "teaching_map_"


class TeachingMapService:
    def __init__(self, config: AppConfig, store: RuntimeStore):
        self.config = config
        self.store = store
        self._registry: List[Dict[str, Any]] = []
        self._load_registry()

    def _load_registry(self) -> None:
        registry_path = self.config.builtin_dir / "teaching_maps" / "registry.json"
        if not registry_path.exists():
            self._registry = []
            return
        try:
            payload = json.loads(registry_path.read_text(encoding="utf-8"))
            self._registry = payload.get("items", [])
        except (OSError, json.JSONDecodeError):
            self._registry = []

        # Ensure images are present in the uploads directory for serving
        self._ensure_images_available()

    def _ensure_images_available(self) -> None:
        """Copy teaching map images to the uploads directory if not present."""
        source_dir = self.config.builtin_dir / "teaching_maps"
        target_dir = self.config.uploads_dir / "teaching_maps"
        target_dir.mkdir(parents=True, exist_ok=True)

        for item in self._registry:
            filename = item.get("filename", "")
            if not filename:
                continue
            target_file = target_dir / filename
            if target_file.exists():
                continue
            source_file = source_dir / filename
            if not source_file.exists():
                # Try the root 人口地图 directory as fallback
                fallback = self.config.root_dir / "人口地图" / filename
                if fallback.exists():
                    source_file = fallback
                else:
                    continue
            shutil.copy2(source_file, target_file)

    def list_maps(self) -> Dict[str, Any]:
        """Return all registered teaching map overlays, grouped by category."""
        items = []
        for item in self._registry:
            filename = item.get("filename", "")
            asset_url = f"/files/uploads/teaching_maps/{filename}" if filename else ""
            items.append({
                "id": item["id"],
                "name": item["name"],
                "category": item.get("category", "其他"),
                "category_order": item.get("category_order", 99),
                "bounds": item.get("bounds", []),
                "view": item.get("view", {}),
                "opacity": item.get("opacity", 0.82),
                "keywords": item.get("keywords", []),
                "asset_url": asset_url,
            })

        items.sort(key=lambda x: (x["category_order"], x["name"]))
        return {"status": "success", "items": items}

    def get_map(self, map_id: str) -> Optional[Dict[str, Any]]:
        """Get a single teaching map by ID."""
        for item in self._registry:
            if item.get("id") == map_id:
                filename = item.get("filename", "")
                return {
                    **item,
                    "asset_url": f"/files/uploads/teaching_maps/{filename}" if filename else "",
                }
        return None

    def toggle_overlay(
        self,
        project_id: str,
        map_id: str,
        visible: bool = True,
    ) -> Dict[str, Any]:
        """Toggle a teaching map overlay on or off in a project.

        When turned on, creates a raster layer in the project.
        When turned off, hides the layer (keeps it for quick re-toggle).
        """
        map_info = self.get_map(map_id)
        if map_info is None:
            raise KeyError(f"Unknown teaching map: {map_id}")

        layer_id = f"{TEACHING_MAP_LAYER_PREFIX}{map_id}"
        project = self.store.get_project(project_id)
        if project is None:
            raise KeyError(f"Unknown project: {project_id}")

        existing_layer = next(
            (layer for layer in project.layers if layer.layer_id == layer_id),
            None,
        )

        if existing_layer is not None:
            # Layer already exists, just toggle visibility
            layer = self.store.patch_layer(project_id, layer_id, {"visible": visible})
            action_text = "显示" if visible else "隐藏"
            self.store.add_recent_action(
                project_id,
                f"{action_text}教学地图",
                f'{action_text}“{map_info["name"]}”',
                status="success",
                metadata={"layer_id": layer_id, "teaching_map_id": map_id},
            )
            return {
                "status": "success",
                "layer": layer.to_dict(),
                "view": map_info.get("view", {}),
            }

        if not visible:
            return {"status": "success", "layer": None, "view": {}}

        # Create new raster layer
        filename = map_info.get("filename", "")
        asset_url = f"/files/uploads/teaching_maps/{filename}"
        bounds = map_info.get("bounds", [])

        layer = LayerRecord.create(
            layer_id=layer_id,
            name=map_info["name"],
            kind="raster",
            source="teaching_map",
            geometry_type="Image",
            data={},
            metadata={
                "asset_url": asset_url,
                "bounds": bounds,
                "teaching_map_id": map_id,
                "category": map_info.get("category", ""),
            },
            opacity=map_info.get("opacity", 0.82),
            z_index=20,
        )
        self.store.upsert_layer(project_id, layer)
        self.store.add_recent_action(
            project_id,
            "叠加教学地图",
            f'已叠加"{map_info["name"]}"',
            status="success",
            metadata={"layer_id": layer_id, "teaching_map_id": map_id},
        )

        return {
            "status": "success",
            "layer": layer.to_dict(),
            "view": map_info.get("view", {}),
        }

    def get_active_overlays(self, project_id: str) -> List[str]:
        """Return IDs of teaching maps currently visible in a project."""
        project = self.store.get_project(project_id)
        if project is None:
            return []
        active = []
        for layer in project.layers:
            if layer.layer_id.startswith(TEACHING_MAP_LAYER_PREFIX) and layer.visible:
                active.append(layer.layer_id[len(TEACHING_MAP_LAYER_PREFIX):])
        return active

    def find_by_keyword(self, keyword: str) -> Optional[Dict[str, Any]]:
        """Find a teaching map by keyword match (for voice commands)."""
        lowered = keyword.lower()
        best_match: Optional[Dict[str, Any]] = None
        best_score = 0

        for item in self._registry:
            score = 0
            name = item.get("name", "").lower()
            if lowered in name:
                score = len(lowered) / max(len(name), 1) * 10

            for kw in item.get("keywords", []):
                if kw.lower() in lowered or lowered in kw.lower():
                    kw_score = len(kw) / max(len(lowered), 1) * 8
                    score = max(score, kw_score)

            if score > best_score:
                best_score = score
                best_match = item

        if best_match and best_score > 1.0:
            filename = best_match.get("filename", "")
            return {
                **best_match,
                "asset_url": f"/files/uploads/teaching_maps/{filename}" if filename else "",
            }
        return None
