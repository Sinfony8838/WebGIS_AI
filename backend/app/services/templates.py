from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..config import AppConfig
from ..geo import generate_dynamic_hu_line
from ..models import LayerRecord
from ..store import RuntimeStore


TEMPLATE_SPECS: Dict[str, Dict[str, Any]] = {
    "generic_classroom_pack": {
        "title": "通用课堂包",
        "description": "用于区域认知、区位判断和课堂即时讲解的基础课堂包。",
        "chapter_id": "general_classroom",
        "chapter_title": "通用课堂",
        "chapter_order": 10,
        "unit_id": "regional_cognition",
        "unit_title": "区域认知基础",
        "unit_order": 10,
        "template_order": 10,
    },
    "population_classroom_pack": {
        "title": "人口专题包",
        "description": "一次加载人口分布、密度、迁移与胡焕庸线对比四类示范模板。",
        "chapter_id": "population_topic",
        "chapter_title": "人口专题",
        "chapter_order": 20,
        "unit_id": "population_pattern",
        "unit_title": "人口空间格局",
        "unit_order": 10,
        "template_order": 10,
    },
    "population_distribution": {
        "title": "人口分布",
        "description": "突出人口空间分布差异的分级设色模板。",
        "chapter_id": "population_topic",
        "chapter_title": "人口专题",
        "chapter_order": 20,
        "unit_id": "population_pattern",
        "unit_title": "人口空间格局",
        "unit_order": 10,
        "template_order": 20,
    },
    "population_density": {
        "title": "人口密度",
        "description": "基于点状符号展示人口密度强弱的课堂模板。",
        "chapter_id": "population_topic",
        "chapter_title": "人口专题",
        "chapter_order": 20,
        "unit_id": "population_pattern",
        "unit_title": "人口空间格局",
        "unit_order": 10,
        "template_order": 30,
    },
    "population_migration": {
        "title": "人口迁移",
        "description": "突出迁移方向、流量强度与区域联系的流线模板。",
        "chapter_id": "population_topic",
        "chapter_title": "人口专题",
        "chapter_order": 20,
        "unit_id": "population_pattern",
        "unit_title": "人口空间格局",
        "unit_order": 10,
        "template_order": 40,
    },
    "hu_line_comparison": {
        "title": "胡焕庸线对比",
        "description": "叠加经典胡焕庸线与动态拟合线，用于讲解人口格局分界。",
        "chapter_id": "population_topic",
        "chapter_title": "人口专题",
        "chapter_order": 20,
        "unit_id": "population_pattern",
        "unit_title": "人口空间格局",
        "unit_order": 10,
        "template_order": 50,
    },
}

DISABLED_TEMPLATE_IDS: set[str] = set()


def _quantile_thresholds(values: List[float], class_count: int) -> List[float]:
    if not values:
        return []
    sorted_values = sorted(values)
    thresholds = []
    for step in range(1, class_count):
        index = int(round(step * (len(sorted_values) - 1) / class_count))
        thresholds.append(sorted_values[index])
    return thresholds


class TemplateService:
    def __init__(self, config: AppConfig, store: RuntimeStore):
        self.config = config
        self.store = store

    def list_templates(self) -> Dict[str, Any]:
        ordered_items = sorted(
            (
                {"template_id": template_id, **spec}
                for template_id, spec in TEMPLATE_SPECS.items()
                if template_id not in DISABLED_TEMPLATE_IDS
            ),
            key=lambda item: (
                int(item.get("chapter_order") or 0),
                int(item.get("unit_order") or 0),
                int(item.get("template_order") or 0),
                str(item["template_id"]),
            ),
        )
        return {"items": ordered_items}

    def apply_template(self, project_id: str, template_id: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if template_id in DISABLED_TEMPLATE_IDS:
            raise ValueError(f"Template temporarily disabled: {template_id}")
        if template_id not in TEMPLATE_SPECS:
            raise ValueError(f"Unknown template: {template_id}")
        if template_id == "generic_classroom_pack":
            result = self._build_generic_classroom_pack(project_id)
        elif template_id == "population_distribution":
            result = self._build_population_distribution(project_id)
        elif template_id == "population_density":
            result = self._build_population_density(project_id)
        elif template_id == "population_migration":
            result = self._build_population_migration(project_id)
        elif template_id == "hu_line_comparison":
            result = self._build_hu_line_comparison(project_id)
        elif template_id == "population_classroom_pack":
            result = self._build_population_classroom_pack(project_id)
        else:
            raise ValueError(f"Unsupported template: {template_id}")

        for layer in result["layers"]:
            self.store.upsert_layer(project_id, layer)
        for enabled in result.get("enabled_templates", [template_id]):
            self.store.enable_template(project_id, enabled)
        if result.get("view"):
            self.store.set_view(project_id, result["view"])
        self.store.add_recent_action(project_id, "应用课堂模板", result["summary"], status="success")

        report_path = self._write_template_report(project_id, template_id, result)
        artifact = {
            "artifact_type": "template_output",
            "title": TEMPLATE_SPECS[template_id]["title"],
            "path": str(report_path),
            "metadata": {"public_url": self.config.public_url_for_path(report_path), "template_id": template_id},
        }
        return {
            "status": "success",
            "summary": result["summary"],
            "assistant_message": result["assistant_message"],
            "layers": [layer.to_dict() for layer in result["layers"]],
            "view": result.get("view", {}),
            "enabled_templates": result.get("enabled_templates", [template_id]),
            "artifacts": [artifact],
        }

    def _write_template_report(self, project_id: str, template_id: str, result: Dict[str, Any]) -> Path:
        output_path = self.config.unique_path(self.config.project_output_dir(project_id), f"{template_id}_report.json")
        payload = {
            "template_id": template_id,
            "summary": result["summary"],
            "assistant_message": result["assistant_message"],
            "layers": [layer.name for layer in result["layers"]],
            "view": result.get("view", {}),
        }
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return output_path

    def _load_builtin_geojson(self, *parts: str) -> Dict[str, Any]:
        path = self.config.builtin_dir.joinpath(*parts)
        return json.loads(path.read_text(encoding="utf-8"))

    def _clone_features(self, collection: Dict[str, Any]) -> Dict[str, Any]:
        return copy.deepcopy(collection)

    def _build_generic_classroom_pack(self, project_id: str) -> Dict[str, Any]:
        regions = self._clone_features(self._load_builtin_geojson("classroom", "eurasia_regions.geojson"))
        points = self._clone_features(self._load_builtin_geojson("classroom", "classroom_focus_points.geojson"))
        for feature in regions["features"]:
            feature["properties"]["__fillColor"] = "#2a6f97"
            feature["properties"]["__fillOpacity"] = 0.16
            feature["properties"]["__strokeColor"] = "#d7ecff"
            feature["properties"]["__strokeWidth"] = 2
        for feature in points["features"]:
            feature["properties"]["__fillColor"] = "#ffb703"
            feature["properties"]["__radius"] = 7
            feature["properties"]["__strokeColor"] = "#1b1b1b"

        layers = [
            LayerRecord.create(
                layer_id="builtin_eurasia_regions",
                name="欧亚区域框架",
                kind="vector",
                source="builtin",
                geometry_type="Polygon",
                data=regions,
                metadata={"feature_count": len(regions["features"]), "teaching_pack": "generic_classroom_pack"},
                style={"labelField": "name", "fillColor": "#2a6f97", "strokeColor": "#d7ecff"},
                z_index=10,
            ),
            LayerRecord.create(
                layer_id="builtin_classroom_points",
                name="课堂关注点",
                kind="vector",
                source="builtin",
                geometry_type="Point",
                data=points,
                metadata={"feature_count": len(points["features"]), "teaching_pack": "generic_classroom_pack"},
                style={"labelField": "name", "radius": 7, "fillColor": "#ffb703"},
                z_index=25,
            ),
        ]
        return {
            "summary": "已加载通用课堂包，可用于区域认知、区位判断和即时读图讲解。",
            "assistant_message": "通用课堂包已就绪。现在适合从区域格局、交通通道和关键节点切入课堂讲解。",
            "layers": layers,
            "view": {"center": [72.0, 37.0], "zoom": 4, "extent": [-10.0, 10.0, 145.0, 65.0]},
            "enabled_templates": ["generic_classroom_pack"],
        }

    def _build_population_distribution(self, project_id: str) -> Dict[str, Any]:
        collection = self._clone_features(self._load_builtin_geojson("population", "population_regions.geojson"))
        values = [float(feature["properties"].get("population", 0)) for feature in collection["features"]]
        thresholds = _quantile_thresholds(values, 5)
        palette = ["#fff0d9", "#ffd08a", "#f6a04d", "#dc6a2c", "#a73b1d"]
        for feature in collection["features"]:
            value = float(feature["properties"].get("population", 0))
            level = 0
            for index, threshold in enumerate(thresholds, start=1):
                if value >= threshold:
                    level = index
            feature["properties"]["__fillColor"] = palette[min(level, len(palette) - 1)]
            feature["properties"]["__strokeColor"] = "#432818"
            feature["properties"]["__strokeWidth"] = 1.4

        layer = LayerRecord.create(
            layer_id="builtin_population_regions",
            name="人口分布",
            kind="vector",
            source="builtin",
            geometry_type="Polygon",
            data=collection,
            metadata={"feature_count": len(collection["features"]), "template_id": "population_distribution"},
            style={"labelField": "name", "strokeColor": "#432818"},
            z_index=30,
        )
        return {
            "summary": "已切换到人口分布模板，适合讲解东密西疏与沿海集聚。",
            "assistant_message": "人口分布模板已加载。可以直接观察华东、华中与西北地区人口规模的梯度差异。",
            "layers": [layer],
            "view": {"center": [104.0, 35.0], "zoom": 4, "extent": [78.0, 18.0, 132.0, 50.5]},
            "enabled_templates": ["population_distribution"],
        }

    def _build_population_density(self, project_id: str) -> Dict[str, Any]:
        collection = self._clone_features(self._load_builtin_geojson("population", "population_centroids.geojson"))
        densities = [float(feature["properties"].get("density", 0)) for feature in collection["features"]]
        minimum = min(densities)
        maximum = max(densities)
        span = max(maximum - minimum, 1.0)
        for feature in collection["features"]:
            density = float(feature["properties"].get("density", 0))
            ratio = (density - minimum) / span
            feature["properties"]["__radius"] = round(8 + ratio * 18, 2)
            feature["properties"]["__fillColor"] = "#1d4ed8"
            feature["properties"]["__fillOpacity"] = round(0.28 + ratio * 0.45, 2)
            feature["properties"]["__strokeColor"] = "#dbeafe"

        layer = LayerRecord.create(
            layer_id="builtin_population_density",
            name="人口密度",
            kind="vector",
            source="builtin",
            geometry_type="Point",
            data=collection,
            metadata={"feature_count": len(collection["features"]), "template_id": "population_density"},
            style={"labelField": "name", "radius": 10, "fillColor": "#1d4ed8"},
            opacity=0.9,
            z_index=34,
        )
        return {
            "summary": "已切换到人口密度模板，适合从点状符号解释集聚中心。",
            "assistant_message": "人口密度模板已加载。圆点越大，表示对应区域的人口密度越高。",
            "layers": [layer],
            "view": {"center": [104.0, 35.0], "zoom": 4, "extent": [78.0, 18.0, 132.0, 50.5]},
            "enabled_templates": ["population_density"],
        }

    def _build_population_migration(self, project_id: str) -> Dict[str, Any]:
        collection = self._clone_features(self._load_builtin_geojson("population", "migration_flows.geojson"))
        migrants = [float(feature["properties"].get("migrants", 0)) for feature in collection["features"]]
        minimum = min(migrants)
        maximum = max(migrants)
        span = max(maximum - minimum, 1.0)
        for feature in collection["features"]:
            value = float(feature["properties"].get("migrants", 0))
            ratio = (value - minimum) / span
            feature["properties"]["__strokeColor"] = "#ef476f"
            feature["properties"]["__strokeWidth"] = round(2 + ratio * 4.5, 2)

        layer = LayerRecord.create(
            layer_id="builtin_population_migration",
            name="人口迁移",
            kind="vector",
            source="builtin",
            geometry_type="LineString",
            data=collection,
            metadata={"feature_count": len(collection["features"]), "template_id": "population_migration"},
            style={"labelField": "name", "strokeColor": "#ef476f"},
            z_index=45,
        )
        return {
            "summary": "已切换到人口迁移模板，适合讲解迁移流向、吸引中心与区域联系。",
            "assistant_message": "人口迁移模板已加载。线条越粗表示迁移规模越大，可结合沿海城市群解释人口流动。",
            "layers": [layer],
            "view": {"center": [104.0, 35.0], "zoom": 4, "extent": [78.0, 18.0, 132.0, 50.5]},
            "enabled_templates": ["population_migration"],
        }

    def _build_hu_line_comparison(self, project_id: str) -> Dict[str, Any]:
        points = self._clone_features(self._load_builtin_geojson("population", "population_centroids.geojson"))
        weighted_points: List[Tuple[Tuple[float, float], float]] = []
        for feature in points["features"]:
            coordinates = feature["geometry"]["coordinates"]
            weighted_points.append(((float(coordinates[0]), float(coordinates[1])), float(feature["properties"].get("population", 1))))

        dynamic_payload = generate_dynamic_hu_line(weighted_points)
        layer = LayerRecord.create(
            layer_id="generated_hu_line",
            name="胡焕庸线对比",
            kind="vector",
            source="generated",
            geometry_type="LineString",
            data=dynamic_payload["features"],
            metadata={
                "template_id": "hu_line_comparison",
                "classic_share": round(dynamic_payload["classic_share"], 4),
                "dynamic_share": round(dynamic_payload["dynamic_share"], 4),
            },
            style={"labelField": "name"},
            z_index=50,
        )
        return {
            "summary": "已叠加胡焕庸线对比模板，可直接讲解人口空间格局分界。",
            "assistant_message": "胡焕庸线对比模板已加载。经典线与动态拟合线都保留了东南密集、西北稀疏的人口格局特征。",
            "layers": [layer],
            "view": {"center": [104.0, 35.0], "zoom": 4, "extent": [78.0, 18.0, 132.0, 50.5]},
            "enabled_templates": ["hu_line_comparison"],
        }

    def _build_population_classroom_pack(self, project_id: str) -> Dict[str, Any]:
        results = [
            self._build_population_distribution(project_id),
            self._build_population_density(project_id),
            self._build_population_migration(project_id),
            self._build_hu_line_comparison(project_id),
        ]
        layers: List[LayerRecord] = []
        enabled_templates: List[str] = ["population_classroom_pack"]
        for result in results:
            layers.extend(result["layers"])
            enabled_templates.extend(result.get("enabled_templates", []))

        return {
            "summary": "已加载人口专题包，覆盖分布、密度、迁移与胡焕庸线四条课堂演示路径。",
            "assistant_message": "人口专题包已就绪。现在可以从人口分布切入，再过渡到密度、迁移与胡焕庸线的综合解释。",
            "layers": layers,
            "view": {"center": [104.0, 35.0], "zoom": 4, "extent": [78.0, 18.0, 132.0, 50.5]},
            "enabled_templates": enabled_templates,
        }
