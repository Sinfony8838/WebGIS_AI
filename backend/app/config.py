from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Sequence, Tuple
from uuid import uuid4


def _default_root_dir() -> Path:
    return Path(__file__).resolve().parents[2]


LLM_PROVIDER_ENV_KEYS = ("WEBGIS_AI_LLM_PROVIDER", "LLM_PROVIDER", "MINIMAX_PROVIDER")
MINIMAX_API_KEY_ENV_KEYS = ("WEBGIS_AI_MINIMAX_API_KEY", "MINIMAX_API_KEY")
MINIMAX_BASE_URL_ENV_KEYS = ("WEBGIS_AI_MINIMAX_BASE_URL", "MINIMAX_BASE_URL")
MINIMAX_MODEL_ENV_KEYS = ("WEBGIS_AI_MINIMAX_MODEL", "MINIMAX_MODEL")
LEGACY_WEATHER_BASEMAP_ID = "weather_live"
WEATHER_BASEMAP_ID = "weather_precipitation"
WEATHER_BASEMAP_PREFIX = "weather_"
OPENWEATHER_DEFAULT_LAYER = "precipitation_new"
OPENWEATHER_TILE_TEMPLATE = "https://tile.openweathermap.org/map/{layer}/{z}/{x}/{y}.png?appid={api_key}"
OPENWEATHER_LAYER_PRESETS = (
    {
        "id": "weather_precipitation",
        "title": "\u5929\u6c14\u00b7\u964d\u6c34",
        "description": "\u9ad8\u5fb7\u5e95\u56fe\u53e0\u52a0 OpenWeather \u5b9e\u65f6\u964d\u6c34\u7f51\u683c\u3002",
        "layer": "precipitation_new",
        "opacity": 0.78,
    },
    {
        "id": "weather_clouds",
        "title": "\u5929\u6c14\u00b7\u4e91\u56fe",
        "description": "\u9ad8\u5fb7\u5e95\u56fe\u53e0\u52a0 OpenWeather \u5b9e\u65f6\u4e91\u91cf\u7f51\u683c\u3002",
        "layer": "clouds_new",
        "opacity": 0.72,
    },
    {
        "id": "weather_temperature",
        "title": "\u5929\u6c14\u00b7\u6e29\u5ea6",
        "description": "\u9ad8\u5fb7\u5e95\u56fe\u53e0\u52a0 OpenWeather \u5b9e\u65f6\u6e29\u5ea6\u7f51\u683c\u3002",
        "layer": "temp_new",
        "opacity": 0.68,
    },
    {
        "id": "weather_wind",
        "title": "\u5929\u6c14\u00b7\u98ce\u901f",
        "description": "\u9ad8\u5fb7\u5e95\u56fe\u53e0\u52a0 OpenWeather \u5b9e\u65f6\u98ce\u901f\u7f51\u683c\u3002",
        "layer": "wind_new",
        "opacity": 0.72,
    },
    {
        "id": "weather_pressure",
        "title": "\u5929\u6c14\u00b7\u6c14\u538b",
        "description": "\u9ad8\u5fb7\u5e95\u56fe\u53e0\u52a0 OpenWeather \u5b9e\u65f6\u6d77\u5e73\u9762\u6c14\u538b\u7f51\u683c\u3002",
        "layer": "pressure_new",
        "opacity": 0.7,
    },
)


def _resolve_env_value(keys: Sequence[str], default: str, default_source: str) -> Tuple[str, str]:
    for key in keys:
        value = os.getenv(key)
        if value is not None and value.strip():
            return value, key
    return default, default_source


@dataclass
class AppConfig:
    root_dir: Path = field(default_factory=_default_root_dir)
    host: str = field(default_factory=lambda: os.getenv("WEBGIS_AI_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(os.getenv("WEBGIS_AI_PORT", "18999")))
    base_map_url: str = field(
        default_factory=lambda: os.getenv(
            "WEBGIS_AI_BASEMAP_URL",
            "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        )
    )
    base_map_attribution: str = field(
        default_factory=lambda: os.getenv(
            "WEBGIS_AI_BASEMAP_ATTRIBUTION",
            "© OpenStreetMap contributors",
        )
    )
    default_basemap_id: str = field(default_factory=lambda: os.getenv("WEBGIS_AI_DEFAULT_BASEMAP", "amap_vector"))
    amap_vector_url: str = field(
        default_factory=lambda: os.getenv(
            "WEBGIS_AI_AMAP_VECTOR_URL",
            "https://webrd{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=7&x={x}&y={y}&z={z}",
        )
    )
    amap_imagery_url: str = field(
        default_factory=lambda: os.getenv(
            "WEBGIS_AI_AMAP_IMAGERY_URL",
            "https://webst{s}.is.autonavi.com/appmaptile?style=6&x={x}&y={y}&z={z}",
        )
    )
    amap_annotation_url: str = field(
        default_factory=lambda: os.getenv(
            "WEBGIS_AI_AMAP_ANNOTATION_URL",
            "https://webst{s}.is.autonavi.com/appmaptile?style=8&x={x}&y={y}&z={z}",
        )
    )
    openweathermap_api_key: str = field(default_factory=lambda: os.getenv("WEBGIS_AI_OPENWEATHERMAP_API_KEY", ""))
    openweathermap_layer: str = field(
        default_factory=lambda: os.getenv("WEBGIS_AI_OPENWEATHERMAP_LAYER", OPENWEATHER_DEFAULT_LAYER)
    )
    amap_poi_polygon_url: str = field(
        default_factory=lambda: os.getenv(
            "WEBGIS_AI_AMAP_POI_POLYGON_URL",
            "https://restapi.amap.com/v3/place/polygon",
        )
    )
    amap_web_service_key: str = field(default_factory=lambda: os.getenv("WEBGIS_AI_AMAP_WEB_SERVICE_KEY", ""))
    llm_provider: str = field(
        default_factory=lambda: _resolve_env_value(LLM_PROVIDER_ENV_KEYS, "minimax", "default")[0].strip().lower() or "minimax"
    )
    minimax_api_key: str = field(default_factory=lambda: _resolve_env_value(MINIMAX_API_KEY_ENV_KEYS, "", "unset")[0])
    minimax_base_url: str = field(
        default_factory=lambda: _resolve_env_value(MINIMAX_BASE_URL_ENV_KEYS, "https://api.minimax.chat/v1", "default")[0]
    )
    minimax_model: str = field(default_factory=lambda: _resolve_env_value(MINIMAX_MODEL_ENV_KEYS, "MiniMax-M2.5", "default")[0])
    qgis_host: str = field(default_factory=lambda: os.getenv("WEBGIS_AI_QGIS_HOST", "127.0.0.1"))
    qgis_port: int = field(default_factory=lambda: int(os.getenv("WEBGIS_AI_QGIS_PORT", "5555")))
    qgis_root: str = field(default_factory=lambda: os.getenv("QGIS_ROOT", os.getenv("WEBGIS_AI_QGIS_ROOT", "")))
    qgis_prefix_subpath: str = field(
        default_factory=lambda: os.getenv("WEBGIS_AI_QGIS_PREFIX_SUBPATH", "apps/qgis-ltr")
    )
    vision_provider: str = field(default_factory=lambda: os.getenv("WEBGIS_AI_VISION_PROVIDER", "minimax_mcp").strip().lower())
    minimax_token_plan_key: str = field(default_factory=lambda: os.getenv("WEBGIS_AI_MINIMAX_TOKEN_PLAN_KEY", ""))
    vision_enabled: bool = field(
        default_factory=lambda: os.getenv("WEBGIS_AI_VISION_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    )
    assistant_v2_enabled: bool = field(
        default_factory=lambda: os.getenv("WEBGIS_AI_ASSISTANT_V2_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
    )
    resource_search_endpoint: str = field(default_factory=lambda: os.getenv("WEBGIS_AI_RESOURCE_SEARCH_ENDPOINT", ""))
    llm_provider_source: str = field(init=False, default="default")
    minimax_api_key_source: str = field(init=False, default="unset")
    minimax_base_url_source: str = field(init=False, default="default")
    minimax_model_source: str = field(init=False, default="default")

    def __post_init__(self) -> None:
        _, self.llm_provider_source = _resolve_env_value(LLM_PROVIDER_ENV_KEYS, "minimax", "default")
        _, self.minimax_api_key_source = _resolve_env_value(MINIMAX_API_KEY_ENV_KEYS, "", "unset")
        _, self.minimax_base_url_source = _resolve_env_value(MINIMAX_BASE_URL_ENV_KEYS, "https://api.minimax.chat/v1", "default")
        _, self.minimax_model_source = _resolve_env_value(MINIMAX_MODEL_ENV_KEYS, "MiniMax-M2.5", "default")
        self.llm_provider = (self.llm_provider or "minimax").strip().lower() or "minimax"
        self.minimax_base_url = (self.minimax_base_url or "https://api.minimax.chat/v1").strip() or "https://api.minimax.chat/v1"
        self.minimax_model = (self.minimax_model or "MiniMax-M2.5").strip() or "MiniMax-M2.5"
        self.backend_dir = self.root_dir / "backend"
        self.app_dir = self.backend_dir / "app"
        self.data_dir = self.backend_dir / "data"
        self.builtin_dir = self.app_dir / "data" / "builtin"
        self.knowledge_dir = self.builtin_dir / "knowledge"
        self.state_dir = self.data_dir / "state"
        self.uploads_dir = self.data_dir / "uploads"
        self.outputs_dir = self.data_dir / "outputs"
        self.workflows_dir = self.data_dir / "workflows"
        self.state_file = self.state_dir / "runtime.json"

    def ensure_dirs(self) -> None:
        for path in (
            self.state_dir,
            self.uploads_dir,
            self.outputs_dir,
            self.uploads_dir / "kb_materials",
            self.workflows_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def workflow_dir(self, workflow_id: str) -> Path:
        """Resolve a per-workflow working directory and ensure it exists."""
        safe_id = "".join(ch for ch in workflow_id if ch.isalnum() or ch in {"_", "-"})
        if not safe_id:
            raise ValueError("workflow_id is invalid")
        path = self.workflows_dir / safe_id
        (path / "outputs").mkdir(parents=True, exist_ok=True)
        (path / "steps").mkdir(parents=True, exist_ok=True)
        (path / "logs").mkdir(parents=True, exist_ok=True)
        return path

    def public_url_for_workflow_path(self, workflow_id: str, relative: str) -> str:
        """Return a /workflow-files/{wid}/{relative} URL the frontend can fetch."""
        cleaned = (relative or "").lstrip("/").replace("\\", "/")
        if ".." in PurePosixPath(cleaned).parts:
            raise ValueError("workflow path must not traverse")
        return f"/workflow-files/{workflow_id}/{cleaned}"

    def resolve_workflow_path(self, workflow_id: str, relative: str) -> Path:
        """Resolve a workflow-relative path and ensure it stays inside the workflow dir."""
        base = self.workflow_dir(workflow_id).resolve()
        cleaned = (relative or "").lstrip("/").replace("\\", "/")
        candidate = (base / cleaned).resolve()
        candidate.relative_to(base)  # raises ValueError on traversal
        return candidate

    def default_basemap(self) -> dict:
        catalog = self.basemap_catalog()
        default_id = catalog["default_id"]
        return copy.deepcopy(next(item for item in catalog["items"] if item["id"] == default_id))

    def basemap_catalog(self) -> Dict[str, Any]:
        vector_urls = self._expand_subdomain_urls(self.amap_vector_url)
        imagery_urls = self._expand_subdomain_urls(self.amap_imagery_url)
        annotation_urls = self._expand_subdomain_urls(self.amap_annotation_url)
        items = [
            {
                "id": "amap_vector",
                "title": "高德标准",
                "description": "适合课堂整体讲解的标准中文底图。",
                "type": "stack",
                "provider": "amap",
                "layers": [
                    self._xyz_layer(
                        layer_id="amap_vector_base",
                        title="高德标准底图",
                        urls=vector_urls,
                        attribution="© 高德地图",
                        class_name="basemap-layer basemap-vector",
                    )
                ],
            },
            {
                "id": "amap_imagery",
                "title": "高德影像",
                "description": "适合展示地貌、海岸与城市分布的影像底图。",
                "type": "stack",
                "provider": "amap",
                "layers": [
                    self._xyz_layer(
                        layer_id="amap_imagery_base",
                        title="高德影像底图",
                        urls=imagery_urls,
                        attribution="© 高德地图",
                        class_name="basemap-layer basemap-imagery",
                    ),
                    self._xyz_layer(
                        layer_id="amap_imagery_labels",
                        title="高德影像注记",
                        urls=annotation_urls,
                        attribution="© 高德地图",
                        class_name="basemap-layer basemap-annotation",
                        z_index=2,
                    ),
                ],
            },
            {
                "id": "amap_light",
                "title": "高德浅灰",
                "description": "适合叠加专题图和课堂标注的浅灰底图。",
                "type": "stack",
                "provider": "amap",
                "layers": [
                    self._xyz_layer(
                        layer_id="amap_light_base",
                        title="高德浅灰底图",
                        urls=vector_urls,
                        attribution="© 高德地图",
                        class_name="basemap-layer basemap-light",
                        opacity=0.96,
                    )
                ],
            },
            {
                "id": "legacy_xyz",
                "title": "兼容底图",
                "description": "用于兼容旧版单一 XYZ 底图配置。",
                "type": "stack",
                "provider": "legacy",
                "layers": [
                    self._xyz_layer(
                        layer_id="legacy_xyz_base",
                        title="兼容 XYZ 底图",
                        urls=[self.base_map_url],
                        attribution=self.base_map_attribution,
                        class_name="basemap-layer basemap-legacy",
                    )
                ],
            },
        ]
        for weather_preset in self.weather_basemap_presets(vector_urls):
            items.insert(-1, weather_preset)
        return {"default_id": self._resolved_default_basemap_id(items), "items": items}

    def basemap_by_id(self, basemap_id: str) -> Dict[str, Any]:
        catalog = self.basemap_catalog()
        for item in catalog["items"]:
            if item["id"] == basemap_id:
                return copy.deepcopy(item)
        return copy.deepcopy(next(item for item in catalog["items"] if item["id"] == catalog["default_id"]))

    def weather_basemap_presets(self, base_urls: Sequence[str]) -> List[Dict[str, Any]]:
        suffix = "" if self.weather_basemap_enabled() else "\u9700\u8981\u914d\u7f6e WEBGIS_AI_OPENWEATHERMAP_API_KEY \u540e\u663e\u793a\u5b9e\u65f6\u5929\u6c14\u53e0\u52a0\u3002"
        presets = []
        for item in OPENWEATHER_LAYER_PRESETS:
            description = item["description"] if self.weather_basemap_enabled() else f"{item['description']} {suffix}"
            presets.append(
                {
                    "id": item["id"],
                    "title": item["title"],
                    "description": description,
                    "type": "stack",
                    "provider": "openweather",
                    "layers": [
                        self._xyz_layer(
                            layer_id=f"{item['id']}_base",
                            title="\u9ad8\u5fb7\u6807\u51c6\u5e95\u56fe",
                            urls=list(base_urls),
                            attribution="OpenStreetMap / AMap",
                            class_name="basemap-layer basemap-weather-base",
                        ),
                        self._xyz_layer(
                            layer_id=f"{item['id']}_overlay",
                            title=item["title"],
                            urls=[self.weather_tile_proxy_url(str(item["layer"]))],
                            attribution="OpenWeatherMap",
                            class_name="basemap-layer basemap-weather-overlay",
                            opacity=float(item["opacity"]),
                            z_index=2,
                        ),
                    ],
                }
            )
        return presets

    def normalize_basemap(self, base_map: Dict[str, Any] | None) -> Dict[str, Any]:
        if not base_map:
            return self.default_basemap()

        basemap_id = str(base_map.get("id") or "").strip()
        if basemap_id:
            known_ids = {item["id"] for item in self.basemap_catalog()["items"]}
            if basemap_id in known_ids:
                return self.basemap_by_id(basemap_id)
            if basemap_id == LEGACY_WEATHER_BASEMAP_ID or basemap_id.startswith(WEATHER_BASEMAP_PREFIX):
                return self.default_basemap()

        if base_map.get("type") == "stack" and isinstance(base_map.get("layers"), list):
            normalized = copy.deepcopy(base_map)
            normalized["provider"] = normalized.get("provider") or "custom"
            normalized["layers"] = [self._normalize_layer_descriptor(item, index) for index, item in enumerate(normalized["layers"])]
            return normalized

        if base_map.get("url"):
            return {
                "id": "legacy_xyz",
                "title": base_map.get("title") or "兼容底图",
                "description": "由旧版单层底图配置自动迁移而来。",
                "type": "stack",
                "provider": "legacy",
                "legacy": True,
                "layers": [
                    self._xyz_layer(
                        layer_id="legacy_xyz_base",
                        title=base_map.get("title") or "兼容 XYZ 底图",
                        urls=[str(base_map["url"])],
                        attribution=str(base_map.get("attribution") or ""),
                        class_name="basemap-layer basemap-legacy",
                    )
                ],
            }

        return self.default_basemap()

    def project_upload_dir(self, project_id: str) -> Path:
        path = self.uploads_dir / project_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def project_output_dir(self, project_id: str) -> Path:
        path = self.outputs_dir / project_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def unique_path(self, directory: Path, filename: str) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        candidate = directory / filename
        if not candidate.exists():
            return candidate

        stem = candidate.stem or "file"
        suffix = candidate.suffix
        while True:
            deduplicated = directory / f"{stem}_{uuid4().hex[:8]}{suffix}"
            if not deduplicated.exists():
                return deduplicated

    def public_url_for_path(self, path: Path) -> str:
        resolved = path.resolve()
        for root in (self.uploads_dir.resolve(), self.outputs_dir.resolve()):
            try:
                relative = resolved.relative_to(root).as_posix()
            except ValueError:
                continue
            return f"/files/{root.name}/{relative}"
        raise ValueError(f"Path is not public: {resolved}")

    def resolve_public_path(self, relative_path: str) -> Path:
        normalized = PurePosixPath(relative_path.strip("/"))
        parts = normalized.parts
        if not parts or parts[0] not in {"uploads", "outputs"}:
            raise ValueError("Unsupported public path")

        base_dir = self.uploads_dir if parts[0] == "uploads" else self.outputs_dir
        candidate = base_dir.joinpath(*parts[1:]).resolve()
        candidate.relative_to(base_dir.resolve())
        return candidate

    def online_services_enabled(self) -> bool:
        return bool(self.amap_web_service_key.strip())

    def weather_basemap_enabled(self) -> bool:
        return bool(self.openweathermap_api_key.strip())

    def public_api_base_url(self) -> str:
        host = (self.host or "127.0.0.1").strip() or "127.0.0.1"
        if host in {"0.0.0.0", "::", "[::]"}:
            host = "127.0.0.1"
        return f"http://{host}:{self.port}"

    def weather_tile_proxy_url(self, layer: str = OPENWEATHER_DEFAULT_LAYER) -> str:
        return f"{self.public_api_base_url()}/tiles/weather/{layer}/{{z}}/{{x}}/{{y}}.png"

    def weather_tile_upstream_url(self, layer: str, z: int | str, x: int | str, y: int | str) -> str:
        api_key = self.openweathermap_api_key.strip()
        if not api_key:
            raise ValueError("OpenWeatherMap API key is not configured")
        layer = (layer or self.openweathermap_layer or OPENWEATHER_DEFAULT_LAYER).strip() or OPENWEATHER_DEFAULT_LAYER
        return (
            OPENWEATHER_TILE_TEMPLATE.replace("{layer}", layer)
            .replace("{api_key}", api_key)
            .replace("{z}", str(z))
            .replace("{x}", str(x))
            .replace("{y}", str(y))
        )

    def minimax_enabled(self) -> bool:
        return self.llm_provider == "minimax" and bool(self.minimax_api_key.strip())

    def llm_status(self) -> Dict[str, Any]:
        configured = self.minimax_enabled()
        error = ""
        if not configured:
            if self.llm_provider != "minimax":
                error = (
                    f"当前 provider 为 {self.llm_provider}。请设置 WEBGIS_AI_LLM_PROVIDER=minimax "
                    "(兼容: LLM_PROVIDER / MINIMAX_PROVIDER)，并重启后端。"
                )
            else:
                error = (
                    "未检测到 MiniMax API Key。请设置 WEBGIS_AI_MINIMAX_API_KEY "
                    "(兼容: MINIMAX_API_KEY)，并重启后端。"
                )
        status = {
            "enabled": configured,
            "configured": configured,
            "provider": self.llm_provider,
            "model": self.minimax_model,
            "base_url": self.minimax_base_url.rstrip("/"),
            "provider_source": self.llm_provider_source,
            "api_key_source": self.minimax_api_key_source,
        }
        if error:
            status["error"] = error
        return status

    def qgis_status_config(self) -> Dict[str, Any]:
        return {
            "enabled": True,
            "host": self.qgis_host,
            "port": self.qgis_port,
        }

    def vision_status(self) -> Dict[str, Any]:
        configured = self.vision_enabled and self.vision_provider == "minimax_mcp" and bool(self.minimax_token_plan_key.strip())
        return {
            "enabled": self.vision_enabled,
            "configured": configured,
            "provider": self.vision_provider,
            "token_plan_key_source": "WEBGIS_AI_MINIMAX_TOKEN_PLAN_KEY" if self.minimax_token_plan_key.strip() else "unset",
        }

    def _expand_subdomain_urls(self, template: str) -> List[str]:
        if "{s}" not in template:
            return [template]
        return [template.replace("{s}", suffix) for suffix in ("01", "02", "03", "04")]

    def _resolved_default_basemap_id(self, items: Sequence[Dict[str, Any]]) -> str:
        requested = str(self.default_basemap_id or "").strip()
        known_ids = {item["id"] for item in items}
        if requested in known_ids:
            return requested
        if "amap_vector" in known_ids:
            return "amap_vector"
        return items[0]["id"]

    def _xyz_layer(
        self,
        layer_id: str,
        title: str,
        urls: List[str],
        attribution: str,
        class_name: str,
        opacity: float = 1.0,
        z_index: int = 1,
    ) -> Dict[str, Any]:
        return {
            "layer_id": layer_id,
            "title": title,
            "kind": "xyz",
            "urls": urls,
            "attribution": attribution,
            "opacity": opacity,
            "z_index": z_index,
            "class_name": class_name,
            "cross_origin": "anonymous",
        }

    def _normalize_layer_descriptor(self, layer: Dict[str, Any], index: int) -> Dict[str, Any]:
        urls = layer.get("urls")
        if not urls and layer.get("url"):
            urls = [str(layer["url"])]
        return {
            "layer_id": str(layer.get("layer_id") or f"custom_layer_{index}"),
            "title": str(layer.get("title") or f"图层 {index + 1}"),
            "kind": str(layer.get("kind") or "xyz"),
            "urls": [str(item) for item in (urls or []) if str(item).strip()],
            "attribution": str(layer.get("attribution") or ""),
            "opacity": float(layer.get("opacity", 1.0)),
            "z_index": int(layer.get("z_index", index + 1)),
            "class_name": str(layer.get("class_name") or "basemap-layer basemap-custom"),
            "cross_origin": str(layer.get("cross_origin") or "anonymous"),
        }
