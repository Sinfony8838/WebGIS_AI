from __future__ import annotations

import base64
import json
import re
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from .config import AppConfig
from .models import LayerRecord, ProjectRecord, build_assistant_v2_stages, build_workflow_stages, utc_now
from .services.assistant import ASSISTANT_TOOL_SCHEMA, AssistantService
from .services.datasets import DatasetService
from .services.knowledge_base import KnowledgeBaseService
from .services.llm_planner import LLMPlanner
from .services.minimax_client import MiniMaxClient
from .services.poi import PoiService
from .services.qgis_bridge import QGIS_ALLOWED_TOOLS, QgisBridgeClient
from .services.resource_search import ResourceSearchService
from .services.session_engine import AssistantSessionEngine
from .services.teaching_maps import TeachingMapService
from .services.templates import DISABLED_TEMPLATE_IDS, TemplateService
from .services.vision import MapVisionService
from .store import RuntimeStore


TRANSPARENT_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAEElEQVR42mP8z8BQDwAFgwJ/lU9nWQAAAABJRU5ErkJggg=="
)


class WebGISRuntime:
    def __init__(self, config: Optional[AppConfig] = None, store: Optional[RuntimeStore] = None):
        self.config = config or AppConfig()
        self.config.ensure_dirs()
        self.store = store or RuntimeStore(self.config.state_file)
        self.dataset_service = DatasetService(self.config, self.store)
        self.template_service = TemplateService(self.config, self.store)
        self.assistant_service = AssistantService(self.config)
        self.knowledge_base_service = KnowledgeBaseService(self.config)
        self.resource_search_service = ResourceSearchService(self.config, self.knowledge_base_service)
        self.poi_service = PoiService(self.config, self.store)
        self.vision_service = MapVisionService(self.config)
        self.minimax_client = MiniMaxClient(self.config)
        self.qgis_bridge = QgisBridgeClient(self.config)
        self.teaching_map_service = TeachingMapService(self.config, self.store)
        self.assistant_service.teaching_map_service = self.teaching_map_service
        self.assistant_service.minimax_client = self.minimax_client
        self.llm_planner = LLMPlanner(self.minimax_client, self.assistant_service, self.qgis_bridge)
        self.session_engine = AssistantSessionEngine(
            self.config,
            self.store,
            self.llm_planner,
            self.assistant_service,
            self._execute_assistant_action,
            self._execute_qgis_action,
        )
        self.session_engine.set_resource_search(self.resource_search_service)
        self._normalize_loaded_projects()

    def health(self) -> Dict[str, Any]:
        return {
            "status": "success",
            "runtime": {
                "api": self.config.public_api_base_url(),
                "workspace": str(self.config.root_dir),
                "uploads": str(self.config.uploads_dir),
                "outputs": str(self.config.outputs_dir),
            },
            "ui": {
                "mode": "single_teacher_live_demo",
                "assistant_tools": ASSISTANT_TOOL_SCHEMA,
                "assistant_v2_enabled": self.config.assistant_v2_enabled,
            },
            "online_services": {
                "amap_poi_enabled": self.config.online_services_enabled(),
                "weather_basemap_enabled": self.config.weather_basemap_enabled(),
            },
            "llm": self.minimax_client.status(),
            "vision": self.vision_service.status(),
            "qgis": self.config.qgis_status_config(),
            "basemaps": self.config.basemap_catalog(),
            "templates": self.template_service.list_templates()["items"],
            "knowledge_base": {
                "manifest_path": str(self.knowledge_base_service.manifest_path),
                "item_count": len(self.knowledge_base_service.get_manifest().get("items", [])),
            },
        }

    def list_teaching_maps(self) -> Dict[str, Any]:
        return self.teaching_map_service.list_maps()

    def toggle_teaching_map(self, project_id: str, map_id: str, visible: bool = True) -> Dict[str, Any]:
        self._require_project(project_id)
        return self.teaching_map_service.toggle_overlay(project_id, map_id, visible)

    def get_active_teaching_maps(self, project_id: str) -> Dict[str, Any]:
        self._require_project(project_id)
        return {"status": "success", "active": self.teaching_map_service.get_active_overlays(project_id)}

    def kb_manifest(self) -> Dict[str, Any]:
        return self.knowledge_base_service.get_manifest()

    def kb_search(
        self,
        query: str = "",
        topic: str = "",
        region: str = "",
        tag: str = "",
        limit: int = 20,
    ) -> Dict[str, Any]:
        return self.knowledge_base_service.search(query=query, topic=topic, region=region, tag=tag, limit=limit)

    def kb_topics(self) -> Dict[str, Any]:
        return self.knowledge_base_service.topics()

    def kb_upsert_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        normalized = self.knowledge_base_service.upsert_item(item)
        return {"status": "success", "item": normalized}

    def kb_register_layer(self, project_id: str, layer_id: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        project = self._require_project(project_id)
        target_layer = next((layer for layer in project.layers if layer.layer_id == layer_id), None)
        if target_layer is None:
            raise KeyError(f"Unknown layer in project: {layer_id}")
        item = self.knowledge_base_service.build_item_from_layer(project_id, target_layer, metadata or {})
        normalized = self.knowledge_base_service.upsert_item(item)
        self.store.add_recent_action(
            project_id,
            "知识库登记",
            f"图层“{target_layer.name}”已登记到知识库",
            status="success",
            metadata={"layer_id": layer_id, "kb_item_id": normalized.get("id", "")},
        )
        return {"status": "success", "item": normalized}

    def kb_upload_material(
        self,
        kb_item_id: str,
        filename: str,
        raw_bytes: bytes,
        title: str = "",
        description: str = "",
        material_type: str = "",
        region_binding: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        suffix = Path(filename or "").suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".mp4", ".webm", ".mov", ".m4v", ".html", ".htm", ".pdf", ".doc", ".docx", ".ppt", ".pptx"}:
            raise ValueError(f"Unsupported material type: {suffix or 'unknown'}")
        safe_name = self._safe_upload_filename(filename or f"material{suffix}")
        output_dir = self.config.uploads_dir / "kb_materials"
        output_path = self.config.unique_path(output_dir, safe_name)
        output_path.write_bytes(raw_bytes)
        material = self.knowledge_base_service.add_material_to_item(
            kb_item_id,
            {
                "title": title or Path(filename).stem or "教学资料",
                "type": material_type,
                "source": "teacher_upload",
                "url": self.config.public_url_for_path(output_path),
                "thumbnail_url": self.config.public_url_for_path(output_path) if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"} else "",
                "description": description,
                "region_binding": region_binding or {},
            },
        )
        return {"status": "success", "material": material}

    def kb_link_material(
        self,
        kb_item_id: str,
        url: str,
        title: str = "",
        description: str = "",
        material_type: str = "link",
        thumbnail_url: str = "",
        region_binding: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not str(url or "").strip().lower().startswith(("http://", "https://", "/files/")):
            raise ValueError("Material link must be an http(s) URL or a public /files URL")
        material = self.knowledge_base_service.add_material_to_item(
            kb_item_id,
            {
                "title": title or url,
                "type": material_type or "link",
                "source": "teacher_link",
                "url": url,
                "thumbnail_url": thumbnail_url,
                "description": description,
                "region_binding": region_binding or {},
            },
        )
        return {"status": "success", "material": material}

    def resource_search(self, query: str = "", scope: str = "all", limit: int = 12) -> Dict[str, Any]:
        return self.resource_search_service.search(query=query, scope=scope, limit=limit)

    def list_lesson_resources(self, project_id: str) -> Dict[str, Any]:
        project = self._require_project(project_id)
        sets = self._lesson_resource_sets(project.project_id, project.metadata)
        active_id = str(project.metadata.get("active_lesson_resource_set_id") or "")
        return {"status": "success", "items": sets, "active_lesson_resource_set_id": active_id}

    def save_lesson_resource_set(self, project_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        project = self._require_project(project_id)
        sets = self._lesson_resource_sets(project.project_id, project.metadata)
        now = self.store_timestamp()
        resource_set = self._normalize_lesson_resource_set(project_id, payload, now)
        replaced = False
        for index, existing in enumerate(sets):
            if existing["id"] == resource_set["id"]:
                resource_set["created_at"] = existing.get("created_at") or now
                sets[index] = resource_set
                replaced = True
                break
        if not replaced:
            sets.append(resource_set)
        project.metadata["lesson_resource_sets"] = sets
        if resource_set.get("active"):
            project.metadata["active_lesson_resource_set_id"] = resource_set["id"]
            for item in sets:
                item["active"] = item["id"] == resource_set["id"]
        self.store.save_project(project)
        return {"status": "success", "item": resource_set, "items": sets}

    def activate_lesson_resource_set(self, project_id: str, set_id: str, patch: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        project = self._require_project(project_id)
        sets = self._lesson_resource_sets(project.project_id, project.metadata)
        if not any(item.get("id") == set_id for item in sets):
            raise KeyError(f"Unknown lesson resource set: {set_id}")
        patch = patch or {}
        for item in sets:
            if item.get("id") != set_id:
                item["active"] = False
                continue
            if patch:
                item.update({key: value for key, value in patch.items() if key in {"title", "item_ids", "material_ids", "region_bindings"}})
            item["active"] = bool(patch.get("active", True))
            item["updated_at"] = self.store_timestamp()
            if item["active"]:
                project.metadata["active_lesson_resource_set_id"] = set_id
        if patch.get("active") is False:
            project.metadata["active_lesson_resource_set_id"] = ""
        project.metadata["lesson_resource_sets"] = sets
        self.store.save_project(project)
        return {"status": "success", "items": sets, "active_lesson_resource_set_id": project.metadata.get("active_lesson_resource_set_id", "")}

    def llm_status(self) -> Dict[str, Any]:
        return {"status": "success", **self.minimax_client.status()}

    def qgis_status(self) -> Dict[str, Any]:
        return {"status": "success", **self.qgis_bridge.status()}

    def qgis_layers(self) -> Dict[str, Any]:
        return {"status": "success", "result": self.qgis_bridge.layers()}

    def qgis_focus(self) -> Dict[str, Any]:
        focus = self.qgis_bridge.focus_window()
        return {"status": "success" if focus.get("ok") else "error", **focus}

    def qgis_execute_tool(self, tool_name: str, tool_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if tool_name not in QGIS_ALLOWED_TOOLS:
            raise ValueError(f"QGIS tool is not allowed: {tool_name}")
        result = self.qgis_bridge.execute(tool_name, tool_params or {})
        return {"status": "success", "result": result}

    def list_basemaps(self) -> Dict[str, Any]:
        return {"status": "success", **self.config.basemap_catalog()}

    def fetch_weather_tile(self, layer: str, z: int, x: int, y: int) -> tuple[bytes, str]:
        if not self.config.weather_basemap_enabled():
            return TRANSPARENT_PNG, "image/png"
        request = urllib.request.Request(
            self.config.weather_tile_upstream_url(layer, z, x, y),
            headers={"User-Agent": "WebGIS-AI/1.1"},
        )
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                content_type = response.headers.get_content_type() or "image/png"
                return response.read(), content_type
        except urllib.error.HTTPError as exc:
            raise ConnectionError(f"Weather tile upstream returned HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise ConnectionError(f"Weather tile upstream is unavailable: {exc.reason}") from exc

    def create_project(self, name: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        project = self.store.create_project(name=name, metadata=metadata, base_map=self.config.default_basemap())
        return {"status": "success", **project.to_dict()}

    def get_project(self, project_id: str) -> Dict[str, Any]:
        project = self._require_project(project_id)
        return {"status": "success", **project.to_dict()}

    def list_layers(self, project_id: str) -> Dict[str, Any]:
        project = self._require_project(project_id)
        layers = sorted(project.layers, key=lambda layer: layer.z_index)
        return {
            "status": "success",
            "items": [layer.to_dict() for layer in layers],
            "active_layer_id": project.active_layer_id,
            "view": project.view,
            "enabled_templates": project.enabled_templates,
            "recent_actions": project.recent_actions,
            "base_map": project.base_map,
        }

    def patch_layer(self, project_id: str, layer_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
        layer = self.store.patch_layer(project_id, layer_id, patch)
        if patch.get("active"):
            self.store.set_active_layer(project_id, layer_id)
        self.store.add_recent_action(
            project_id,
            "更新图层样式",
            f"已更新图层“{layer.name}”",
            status="success",
            metadata={"layer_id": layer.layer_id},
        )
        return {"status": "success", "item": layer.to_dict()}

    def set_basemap(self, project_id: str, basemap_id: str) -> Dict[str, Any]:
        self._require_project(project_id)
        base_map = self.config.basemap_by_id(basemap_id)
        updated = self.store.set_basemap(project_id, base_map)
        self.store.add_recent_action(
            project_id,
            "切换底图",
            f"已切换到“{updated.get('title', basemap_id)}”",
            status="success",
            metadata={"basemap_id": basemap_id},
        )
        return {"status": "success", "base_map": updated}

    def search_poi(
        self,
        project_id: str,
        keyword: str,
        mode: str = "view",
        extent: Optional[List[float]] = None,
        geometry: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        self._require_project(project_id)
        return self.poi_service.search(project_id=project_id, keyword=keyword, mode=mode, extent=extent, geometry=geometry)

    def upload_dataset(
        self,
        project_id: str,
        filename: str,
        raw_bytes: bytes,
        dataset_name: str = "",
        lat_field: str = "",
        lon_field: str = "",
        image_bounds: Optional[List[float]] = None,
    ) -> Dict[str, Any]:
        job = self.store.create_job(
            project_id=project_id,
            job_type="dataset_upload",
            title=f"导入 {filename}",
            workflow_type="dataset_upload",
            request={"filename": filename},
            stages=build_workflow_stages(),
        )
        try:
            self.store.set_job_status(job.job_id, "running")
            self.store.update_job_stage(job.job_id, "analysis", "running", "正在识别数据类型。")
            result = self.dataset_service.import_upload(
                project_id=project_id,
                filename=filename,
                raw_bytes=raw_bytes,
                dataset_name=dataset_name,
                lat_field=lat_field,
                lon_field=lon_field,
                image_bounds=image_bounds,
            )
            self.store.update_job_stage(job.job_id, "analysis", "success", "数据类型识别完成。")
            self.store.update_job_stage(job.job_id, "map", "success", "图层已写入项目。")
            artifact = result["artifact"]
            registered_artifact = self.store.register_artifact(
                project_id=project_id,
                job_id=job.job_id,
                artifact_type=artifact["artifact_type"],
                title=artifact["title"],
                path=artifact["path"],
                metadata=artifact["metadata"],
            )
            self.store.update_job_stage(job.job_id, "artifacts", "success", "数据导入记录已保存。")
            self.store.set_job_status(
                job.job_id,
                "completed",
                result={
                    "status": "success",
                    "workflow_type": "dataset_upload",
                    "summary": f"已导入 {result['layer']['name']}",
                    "assistant_message": f"数据集 {result['layer']['name']} 已进入当前课堂项目。",
                    "artifacts": {registered_artifact.artifact_id: registered_artifact.to_dict()},
                    "layer": result["layer"],
                    "stages": self.store.get_job(job.job_id).stages,
                },
            )
            return {"status": "success", "job_id": job.job_id, **result}
        except Exception as exc:
            self._fail_job(job.job_id, "dataset_upload", str(exc))
            raise

    def submit_template(self, project_id: str, template_id: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        job = self.store.create_job(
            project_id=project_id,
            job_type="template",
            title=f"应用模板 {template_id}",
            workflow_type="template_run",
            request={"template_id": template_id, "payload": payload or {}},
        )
        threading.Thread(
            target=self._run_template_job,
            args=(job.job_id, project_id, template_id, payload or {}),
            daemon=True,
        ).start()
        return {"status": "accepted", "job_id": job.job_id, "project_id": project_id}

    def submit_assistant_message(
        self,
        project_id: str,
        message: str,
        map_context: Optional[Dict[str, Any]] = None,
        assistant_mode: str = "tool",
        conversation_id: str = "",
        history: Optional[List[Dict[str, Any]]] = None,
        target: str = "webgis",
        input_mode: str = "text",
        screen_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        normalized_target = target if target in {"webgis", "qgis", "auto"} else "webgis"
        normalized_input_mode = input_mode if input_mode in {"text", "voice"} else "text"
        normalized_mode = assistant_mode if assistant_mode in {"knowledge", "tool"} else "tool"
        use_v2 = self.config.assistant_v2_enabled or assistant_mode == "knowledge" or bool(conversation_id) or bool(history)
        job = self.store.create_job(
            project_id=project_id,
            job_type="assistant",
            title="课堂助教请求",
            workflow_type="assistant_message",
            request={
                "message": message,
                "map_context": map_context or {},
                "assistant_mode": normalized_mode,
                "conversation_id": conversation_id,
                "history": history or [],
                "target": normalized_target,
                "input_mode": normalized_input_mode,
                "screen_snapshot": screen_snapshot or {},
            },
            stages=build_assistant_v2_stages() if use_v2 else build_workflow_stages(),
        )
        if use_v2:
            threading.Thread(
                target=self._run_assistant_v2_job,
                args=(
                    job.job_id,
                    project_id,
                    message,
                    map_context or {},
                    normalized_mode,
                    conversation_id,
                    history or [],
                    normalized_target,
                    normalized_input_mode,
                    screen_snapshot or {},
                ),
                daemon=True,
            ).start()
        else:
            threading.Thread(
                target=self._run_assistant_job,
                args=(job.job_id, project_id, message, map_context or {}, normalized_target, normalized_input_mode, screen_snapshot or {}),
                daemon=True,
            ).start()
        return {
            "status": "accepted",
            "job_id": job.job_id,
            "project_id": project_id,
            "conversation_id": conversation_id,
            "assistant_mode": normalized_mode,
        }

    def confirm_assistant_action(self, confirmation_id: str, decision: str = "approve") -> Dict[str, Any]:
        confirmation = self.store.get_confirmation(confirmation_id)
        if confirmation is None:
            raise KeyError(f"Unknown confirmation: {confirmation_id}")
        normalized_decision = "reject" if str(decision).strip().lower() == "reject" else "approve"
        job = self.store.create_job(
            project_id=confirmation.project_id,
            job_type="assistant_confirmation",
            title=confirmation.title or ("Reject assistant action" if normalized_decision == "reject" else "Confirm assistant action"),
            workflow_type="assistant_confirmation",
            request={"confirmation_id": confirmation_id, "conversation_id": confirmation.conversation_id, "decision": normalized_decision},
            stages=build_assistant_v2_stages(),
        )
        threading.Thread(target=self._run_confirmation_job, args=(job.job_id, confirmation_id, normalized_decision), daemon=True).start()
        return {
            "status": "accepted",
            "job_id": job.job_id,
            "project_id": confirmation.project_id,
            "conversation_id": confirmation.conversation_id,
            "confirmation_id": confirmation_id,
            "decision": normalized_decision,
        }

    def get_conversation(self, conversation_id: str) -> Dict[str, Any]:
        conversation = self.store.get_conversation(conversation_id)
        if conversation is None:
            raise KeyError(f"Unknown conversation: {conversation_id}")
        messages = [item.to_dict() for item in self.store.list_conversation_messages(conversation_id)]
        return {"status": "success", **conversation.to_dict(), "messages": messages}

    def export_snapshot(
        self,
        project_id: str,
        title: str,
        image_data_url: str,
        note: str = "",
    ) -> Dict[str, Any]:
        job = self.store.create_job(
            project_id=project_id,
            job_type="export",
            title=title or "课堂导图",
            workflow_type="export_snapshot",
            request={"title": title, "note": note},
        )
        try:
            self.store.set_job_status(job.job_id, "running")
            self.store.update_job_stage(job.job_id, "artifacts", "running", "正在保存课堂截图。")
            if "," not in image_data_url:
                raise ValueError("Snapshot export requires a valid data URL")
            prefix, encoded = image_data_url.split(",", 1)
            if ";base64" not in prefix:
                raise ValueError("Snapshot export requires a base64 data URL")
            raw = base64.b64decode(encoded.encode("utf-8"))
            output_path = self.config.project_output_dir(project_id) / f"snapshot_{job.job_id}.png"
            output_path.write_bytes(raw)
            artifact = self.store.register_artifact(
                project_id=project_id,
                job_id=job.job_id,
                artifact_type="map_snapshot",
                title=title or "课堂导图",
                path=str(output_path),
                metadata={"public_url": self.config.public_url_for_path(output_path), "note": note},
            )
            self.store.add_recent_action(project_id, "导出课堂截图", title or "课堂导图", status="success")
            self.store.update_job_stage(job.job_id, "artifacts", "success", "课堂截图已保存。")
            self.store.set_job_status(
                job.job_id,
                "completed",
                result={
                    "status": "success",
                    "workflow_type": "export_snapshot",
                    "summary": f"已导出 {title or '课堂导图'}",
                    "assistant_message": "当前课堂画面已保存为本地截图。",
                    "artifacts": {artifact.artifact_id: artifact.to_dict()},
                    "stages": self.store.get_job(job.job_id).stages,
                },
            )
            return {"status": "success", "job_id": job.job_id, "artifact": artifact.to_dict()}
        except Exception as exc:
            self._fail_job(job.job_id, "export_snapshot", str(exc))
            raise

    def get_job(self, job_id: str) -> Dict[str, Any]:
        job = self.store.get_job(job_id)
        if not job:
            raise KeyError(f"Unknown job: {job_id}")
        return job.to_dict()

    def get_artifact(self, artifact_id: str) -> Dict[str, Any]:
        artifact = self.store.get_artifact(artifact_id)
        if not artifact:
            raise KeyError(f"Unknown artifact: {artifact_id}")
        return {"status": "success", **artifact.to_dict()}

    def list_outputs(self, project_id: Optional[str] = None) -> Dict[str, Any]:
        teacher_facing = {"map_snapshot", "annotation_export", "dataset_import", "assistant_note", "query_summary"}
        items = [item for item in self.store.list_outputs(project_id=project_id) if item.get("artifact_type") in teacher_facing]
        return {"status": "success", "items": items}

    def _run_template_job(self, job_id: str, project_id: str, template_id: str, payload: Dict[str, Any]) -> None:
        try:
            self.store.set_job_status(job_id, "running")
            self.store.append_job_step(job_id, "开始处理模板", f"正在应用模板 {template_id}", "running")
            self.store.update_job_stage(job_id, "analysis", "success", "模板请求已接收。")
            self.store.update_job_stage(job_id, "actions", "running", "正在准备图层和课堂视图。")
            result = self.template_service.apply_template(project_id, template_id, payload)
            self.store.update_job_stage(job_id, "actions", "success", "模板规则计算完成。")
            self.store.update_job_stage(job_id, "map", "success", "地图图层已写入课堂项目。")
            artifacts = self._register_artifacts(project_id, job_id, result.get("artifacts", []))
            self.store.update_job_stage(job_id, "artifacts", "success", "模板产物已登记。")
            self.store.set_job_status(
                job_id,
                "completed",
                result={
                    "status": "success",
                    "workflow_type": "template_run",
                    "summary": result["summary"],
                    "assistant_message": result["assistant_message"],
                    "template_id": template_id,
                    "artifacts": artifacts,
                    "stages": self.store.get_job(job_id).stages,
                    "layers": result.get("layers", []),
                    "view": result.get("view", {}),
                },
            )
        except Exception as exc:  # pragma: no cover - defensive runtime branch
            self._fail_job(job_id, "template_run", str(exc))

    def _run_assistant_v2_job(
        self,
        job_id: str,
        project_id: str,
        message: str,
        map_context: Dict[str, Any],
        assistant_mode: str,
        conversation_id: str,
        history: List[Dict[str, Any]],
        target: str = "webgis",
        input_mode: str = "text",
        screen_snapshot: Optional[Dict[str, Any]] = None,
    ) -> None:
        try:
            project = self._require_project(project_id)
            if screen_snapshot:
                map_context = {**map_context, "screen_snapshot": screen_snapshot}
            self.store.set_job_status(job_id, "running")
            self.store.append_job_step(job_id, "route", "assistant session engine started", "running")

            def update_stage(stage_name: str, status: str, summary: str = "", detail: str = "") -> None:
                self.store.update_job_stage(job_id, stage_name, status, summary, detail)

            result = self.session_engine.handle(
                job_id=job_id,
                project=project,
                message=message,
                assistant_mode=assistant_mode,
                conversation_id=conversation_id,
                history=history,
                map_context=map_context,
                target=target,
                input_mode=input_mode,
                stage_callback=update_stage,
            )
            registered_artifacts: Dict[str, Any] = {}
            for item in result.get("actions_executed", []):
                action_result = item.get("result", {})
                registered_artifacts.update(
                    self._register_artifacts(project_id, job_id, action_result.get("artifacts", []))
                )
            artifact_status = "success" if registered_artifacts else "skipped"
            artifact_summary = "Artifacts registered" if registered_artifacts else "No standalone artifacts"
            self.store.update_job_stage(job_id, "artifacts", artifact_status, artifact_summary)
            self.store.set_job_status(
                job_id,
                "completed",
                result={
                    "status": "success",
                    "workflow_type": "assistant_message",
                    "summary": result.get("assistant_message") or message,
                    "assistant_message": result.get("assistant_message") or "",
                    "intent": result.get("intent"),
                    "knowledge": result.get("knowledge"),
                    "citations": result.get("citations", []),
                    "actions_planned": result.get("actions_planned", []),
                    "actions_executed": result.get("actions_executed", []),
                    "requires_confirmation": result.get("requires_confirmation", False),
                    "confirmation_id": result.get("confirmation_id", ""),
                    "confirmation_expires_at": result.get("confirmation_expires_at", ""),
                    "plan_fingerprint": result.get("plan_fingerprint", ""),
                    "planner": result.get("planner", ""),
                    "retrieval_trace": result.get("retrieval_trace", []),
                    "conversation_id": result.get("conversation_id", ""),
                    "prompt_parts": result.get("prompt_parts", {}),
                    "permission_context": result.get("permission_context", {}),
                    "artifacts": registered_artifacts,
                    "stages": self.store.get_job(job_id).stages,
                },
            )
        except Exception as exc:  # pragma: no cover - defensive runtime branch
            self._fail_job(job_id, "assistant_message_v2", str(exc))

    def _run_assistant_job(
        self,
        job_id: str,
        project_id: str,
        message: str,
        map_context: Dict[str, Any],
        target: str = "webgis",
        input_mode: str = "text",
        screen_snapshot: Optional[Dict[str, Any]] = None,
    ) -> None:
        try:
            project = self._require_project(project_id)
            if screen_snapshot:
                map_context = {**map_context, "screen_snapshot": screen_snapshot}
            self.store.set_job_status(job_id, "running")
            self.store.append_job_step(job_id, "解析指令", "正在理解课堂助教请求。", "running")
            self.store.update_job_stage(job_id, "analysis", "running", "正在分析课堂意图。")
            plan = self.llm_planner.plan_actions(
                message,
                project,
                map_context=map_context,
                target=target,
                input_mode=input_mode,
            )
            plan_target = str(plan.get("target") or "webgis")
            self.store.update_job_stage(job_id, "analysis", "success", "课堂意图识别完成。")
            self.store.update_job_stage(job_id, "actions", "running", "正在执行地图副驾驶动作。")
            executed_actions = []
            artifacts: List[Dict[str, Any]] = []
            messages = [plan.get("assistant_message", "").strip()]
            for action in plan.get("actions", []):
                self.store.append_job_step(job_id, action["tool_name"], json.dumps(action["tool_params"], ensure_ascii=False), "info")
                if plan_target == "qgis":
                    action_result = self._execute_qgis_action(action)
                else:
                    action_result = self._execute_assistant_action(project_id, action, map_context)
                executed_actions.append({"action": action, "result": action_result})
                if action_result.get("assistant_message"):
                    messages.append(str(action_result["assistant_message"]))
                artifacts.extend(action_result.get("artifacts", []))
            self.store.update_job_stage(job_id, "actions", "success", "课堂动作执行完成。")
            self.store.update_job_stage(job_id, "map", "success", "项目状态已同步到课堂地图。")
            registered_artifacts = self._register_artifacts(project_id, job_id, artifacts)
            artifact_status = "success" if registered_artifacts else "skipped"
            artifact_summary = "已记录助教产物。" if registered_artifacts else "本次助教动作没有生成独立产物。"
            self.store.update_job_stage(job_id, "artifacts", artifact_status, artifact_summary)
            self.store.set_job_status(
                job_id,
                "completed",
                result={
                    "status": "success",
                    "workflow_type": "assistant_message",
                    "summary": messages[-1] if messages else "课堂助教已完成当前操作。",
                    "assistant_message": "\n\n".join([part for part in messages if part]),
                    "target": plan_target,
                    "planner": plan.get("planner", "rule_fallback"),
                    "llm_fallback_reason": plan.get("llm_fallback_reason", ""),
                    "actions": plan.get("actions", []),
                    "actions_executed": executed_actions,
                    "artifacts": registered_artifacts,
                    "stages": self.store.get_job(job_id).stages,
                },
            )
        except Exception as exc:  # pragma: no cover - defensive runtime branch
            self._fail_job(job_id, "assistant_message", str(exc))

    def _run_confirmation_job(self, job_id: str, confirmation_id: str, decision: str = "approve") -> None:
        try:
            self.store.set_job_status(job_id, "running")
            self.store.append_job_step(
                job_id,
                "confirm",
                "rejecting assistant action" if decision == "reject" else "executing confirmed assistant action",
                "running",
            )

            def update_stage(stage_name: str, status: str, summary: str = "", detail: str = "") -> None:
                self.store.update_job_stage(job_id, stage_name, status, summary, detail)

            if decision == "reject":
                result = self.session_engine.reject_confirmation(confirmation_id)
            else:
                result = self.session_engine.execute_confirmation(confirmation_id, stage_callback=update_stage)
            registered_artifacts: Dict[str, Any] = {}
            for item in result.get("actions_executed", []):
                action_result = item.get("result", {})
                registered_artifacts.update(
                    self._register_artifacts(result.get("project_id", self.store.get_job(job_id).project_id), job_id, action_result.get("artifacts", []))
                )
            self.store.update_job_stage(job_id, "artifacts", "success" if registered_artifacts else "skipped", "Confirmation flow finished")
            self.store.set_job_status(
                job_id,
                "completed",
                result={
                    "status": "success",
                    "workflow_type": "assistant_confirmation",
                    "summary": result.get("assistant_message", ""),
                    "assistant_message": result.get("assistant_message", ""),
                    "intent": result.get("intent"),
                    "knowledge": result.get("knowledge"),
                    "citations": result.get("citations", []),
                    "actions_planned": result.get("actions_planned", []),
                    "actions_executed": result.get("actions_executed", []),
                    "requires_confirmation": False,
                    "confirmation_id": result.get("confirmation_id", ""),
                    "confirmation_status": "rejected" if decision == "reject" else "approved",
                    "planner": result.get("planner", "confirmation"),
                    "retrieval_trace": result.get("retrieval_trace", []),
                    "conversation_id": result.get("conversation_id", ""),
                    "permission_context": result.get("permission_context", {}),
                    "artifacts": registered_artifacts,
                    "stages": self.store.get_job(job_id).stages,
                },
            )
        except Exception as exc:  # pragma: no cover - defensive runtime branch
            self._fail_job(job_id, "assistant_confirmation", str(exc))

    def _execute_qgis_action(self, action: Dict[str, Any]) -> Dict[str, Any]:
        tool_name = action["tool_name"]
        params = action.get("tool_params", {})
        if tool_name not in QGIS_ALLOWED_TOOLS:
            raise ValueError(f"QGIS tool is not allowed: {tool_name}")
        response = self.qgis_bridge.execute(tool_name, params)
        status = str(response.get("status") or "")
        if status and status not in {"success", "ok"}:
            error_message = str(response.get("message") or f"QGIS tool failed: {tool_name}")
            if tool_name == "set_style" and "dedicated tools" in error_message.lower():
                return {
                    "assistant_message": "QGIS 插件已拒绝通用 set_style（复杂专题样式需专用工具），该步骤已跳过并继续执行。",
                    "qgis_response": response,
                    "artifacts": [],
                }
            raise ValueError(error_message)
        message = str(response.get("message") or f"QGIS 工具 {tool_name} 已执行。")
        return {"assistant_message": message, "qgis_response": response, "artifacts": []}

    def _execute_assistant_action(self, project_id: str, action: Dict[str, Any], map_context: Dict[str, Any]) -> Dict[str, Any]:
        tool_name = action["tool_name"]
        params = action.get("tool_params", {})
        if tool_name == "set_view":
            view = self.store.set_view(project_id, params)
            self.store.add_recent_action(project_id, "调整视角", "已更新课堂视图。", status="success")
            return {"assistant_message": "课堂视角已更新。", "view": view, "artifacts": []}
        if tool_name == "toggle_layer":
            layer = self.store.patch_layer(project_id, params["layer_id"], {"visible": params["visible"]})
            state_text = "显示" if params["visible"] else "隐藏"
            self.store.add_recent_action(project_id, f"{state_text}图层", f"{state_text}“{layer.name}”", status="success")
            return {"assistant_message": f"图层“{layer.name}”已{state_text}。", "artifacts": []}
        if tool_name == "reorder_layer":
            layer = self.store.patch_layer(project_id, params["layer_id"], {"z_index": params["z_index"]})
            self.store.add_recent_action(project_id, "调整图层顺序", f"“{layer.name}”已移动到新的层级。", status="success")
            return {"assistant_message": f"图层“{layer.name}”的顺序已调整。", "artifacts": []}
        if tool_name == "style_layer":
            layer = self.store.patch_layer(project_id, params["layer_id"], {"style": params["style"]})
            self.store.add_recent_action(project_id, "更新图层样式", f"“{layer.name}”样式已更新。", status="success")
            return {"assistant_message": f"图层“{layer.name}”的样式已更新。", "artifacts": []}
        if tool_name == "query_features":
            project = self._require_project(project_id)
            content = self.assistant_service.compose_feature_summary(project, params.get("layer_id", ""), limit=int(params.get("limit", 5)))
            note = self._write_text_output(project_id, f"query_{self._safe_output_stub(params.get('layer_id', 'layers'))}", content)
            return {
                "assistant_message": content,
                "artifacts": [{"artifact_type": "assistant_note", "title": "图层查询摘要", "path": str(note), "metadata": {"public_url": self.config.public_url_for_path(note)}}],
            }
        if tool_name == "draw_annotation":
            project = self._require_project(project_id)
            annotation_layer = next((layer for layer in project.layers if layer.layer_id == "assistant_annotations"), None)
            if annotation_layer is None:
                annotation_layer = LayerRecord.create(
                    layer_id="assistant_annotations",
                    name="课堂标注",
                    kind="annotation",
                    source="generated",
                    geometry_type="Point",
                    data={"type": "FeatureCollection", "features": []},
                    style={"labelField": "label", "fillColor": "#fde047", "radius": 8, "strokeColor": "#0f172a"},
                    z_index=100,
                )
            position = params.get("position") or project.view.get("center") or [104.0, 35.0]
            annotation_layer.data.setdefault("features", []).append(
                {
                    "type": "Feature",
                    "properties": {"name": params.get("text", "课堂标注"), "label": params.get("text", "课堂标注"), "__fillColor": "#fde047", "__strokeColor": "#0f172a", "__radius": 8},
                    "geometry": {"type": "Point", "coordinates": [float(position[0]), float(position[1])]},
                }
            )
            self.store.upsert_layer(project_id, annotation_layer)
            self.store.add_recent_action(project_id, "添加课堂标注", params.get("text", "课堂标注"), status="success")
            return {"assistant_message": "课堂标注已添加到当前视图。", "artifacts": []}
        if tool_name == "measure":
            content = self.assistant_service.compose_measurement(params.get("extent") or map_context.get("extent"))
            note = self._write_text_output(project_id, "measure_note", content)
            return {
                "assistant_message": content,
                "artifacts": [{"artifact_type": "assistant_note", "title": "尺度说明", "path": str(note), "metadata": {"public_url": self.config.public_url_for_path(note)}}],
            }
        if tool_name == "apply_template":
            result = self.template_service.apply_template(project_id, params["template_id"], {})
            return {"assistant_message": result["assistant_message"], "artifacts": result.get("artifacts", [])}
        if tool_name == "export_snapshot":
            return {"assistant_message": self.assistant_service.build_export_hint(), "artifacts": []}
        if tool_name == "explain_current_view":
            project = self._require_project(project_id)
            content = self.assistant_service.compose_explanation(project, map_context=map_context, focus=params.get("focus", ""))
            screen_snapshot = map_context.get("screen_snapshot") if isinstance(map_context.get("screen_snapshot"), dict) else {}
            if screen_snapshot:
                vision_result = self.vision_service.understand_map(
                    project_id=project_id,
                    project=project,
                    map_context=map_context,
                    focus=params.get("focus", ""),
                    screen_snapshot=screen_snapshot,
                )
                if not vision_result.get("used_vision") and vision_result.get("reason"):
                    content = f"{content}\n\n注意事项：{vision_result['reason']}"
            note = self._write_text_output(project_id, "assistant_explanation", content)
            return {
                "assistant_message": content,
                "artifacts": [{"artifact_type": "assistant_note", "title": "课堂讲解稿", "path": str(note), "metadata": {"public_url": self.config.public_url_for_path(note)}}],
            }
        if tool_name == "switch_basemap":
            basemap = self.set_basemap(project_id, params["basemap_id"])["base_map"]
            return {"assistant_message": f"底图已切换到“{basemap.get('title', params['basemap_id'])}”。", "artifacts": []}
        if tool_name == "search_poi":
            result = self.search_poi(
                project_id=project_id,
                keyword=str(params.get("keyword") or ""),
                mode=str(params.get("mode") or "view"),
                extent=params.get("extent"),
                geometry=params.get("geometry"),
            )
            content = "\n".join(
                [
                    result["summary"],
                    *[
                        f"- {item['name']}（{item['district'] or item['city'] or '未知区域'} {item['address'] or ''}）".strip()
                        for item in result["items"][:5]
                    ],
                ]
            )
            note = self._write_text_output(project_id, "poi_search_note", content)
            return {
                "assistant_message": self.assistant_service.build_poi_hint(result["keyword"], len(result["items"])),
                "artifacts": [{"artifact_type": "assistant_note", "title": "POI 检索结果", "path": str(note), "metadata": {"public_url": self.config.public_url_for_path(note)}}],
            }
        if tool_name == "toggle_teaching_map":
            result = self.toggle_teaching_map(project_id, params["map_id"], params.get("visible", True))
            layer = result.get("layer")
            name = layer["name"] if layer else params["map_id"]
            visible = params.get("visible", True)
            state_text = "叠加" if visible else "隐藏"
            # Also set view to the recommended area when showing a teaching map
            view = result.get("view", {})
            if visible and view.get("center") and view.get("zoom"):
                self.store.set_view(project_id, view)
            return {
                "assistant_message": f'教学地图"{name}"已{state_text}。',
                "view": view,
                "artifacts": [],
            }
        if tool_name == "open_material":
            material = params.get("material") if isinstance(params.get("material"), dict) else {}
            if not material:
                material = self._find_kb_material(str(params.get("material_id") or ""))
            if not material:
                raise KeyError(f"Unknown teaching material: {params.get('material_id') or ''}")
            title = str(material.get("title") or "课堂资料")
            return {
                "assistant_message": f"已打开课堂资料“{title}”。",
                "ui_actions": [{"type": "open_material", "title": title, "materials": [material]}],
                "artifacts": [],
            }
        raise ValueError(f"Unsupported assistant tool: {tool_name}")

    def _register_artifacts(self, project_id: str, job_id: str, artifacts: List[Dict[str, Any]]) -> Dict[str, Any]:
        registered = {}
        for descriptor in artifacts:
            artifact = self.store.register_artifact(
                project_id=project_id,
                job_id=job_id,
                artifact_type=descriptor["artifact_type"],
                title=descriptor["title"],
                path=descriptor["path"],
                metadata=descriptor.get("metadata", {}),
            )
            registered[artifact.artifact_id] = artifact.to_dict()
        return registered

    def _write_text_output(self, project_id: str, stem: str, content: str) -> Path:
        output_path = self.config.unique_path(self.config.project_output_dir(project_id), f"{stem}.md")
        output_path.write_text(content, encoding="utf-8")
        return output_path

    def _safe_output_stub(self, value: str) -> str:
        return "".join(ch if ch.isalnum() else "_" for ch in str(value or "note"))

    def _find_kb_material(self, material_id: str) -> Dict[str, Any]:
        if not material_id:
            return {}
        manifest = self.knowledge_base_service.get_manifest()
        for item in manifest.get("items", []):
            for material in item.get("materials", []):
                if str(material.get("id") or "") == material_id:
                    return material
        return {}

    def _safe_upload_filename(self, filename: str) -> str:
        name = Path(filename or "material.dat").name
        stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(name).stem).strip("._") or "material"
        suffix = Path(name).suffix.lower()
        return f"{stem}_{uuid4().hex[:8]}{suffix}"

    def store_timestamp(self) -> str:
        return utc_now()

    def _lesson_resource_sets(self, project_id: str, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        rows = []
        for item in metadata.get("lesson_resource_sets", []):
            if isinstance(item, dict):
                rows.append(self._normalize_lesson_resource_set(project_id, item, str(item.get("updated_at") or utc_now())))
        return rows

    def _normalize_lesson_resource_set(self, project_id: str, payload: Dict[str, Any], now: str) -> Dict[str, Any]:
        raw = payload or {}
        set_id = str(raw.get("id") or f"lesson_{uuid4().hex}")
        def string_list(value: Any) -> List[str]:
            if not isinstance(value, list):
                return []
            return [str(item).strip() for item in value if str(item).strip()]

        bindings = []
        for entry in raw.get("region_bindings", []):
            if not isinstance(entry, dict):
                continue
            bindings.append({key: str(value).strip() for key, value in entry.items() if key in {"layer_id", "feature_id", "admin_code", "name", "name_field"} and str(value).strip()})
        return {
            "id": set_id,
            "title": str(raw.get("title") or "课堂资料包").strip(),
            "project_id": project_id or str(raw.get("project_id") or ""),
            "item_ids": string_list(raw.get("item_ids")),
            "material_ids": string_list(raw.get("material_ids")),
            "region_bindings": bindings,
            "active": bool(raw.get("active")),
            "created_at": str(raw.get("created_at") or now),
            "updated_at": now,
        }

    def _normalize_loaded_projects(self) -> None:
        for project in list(self.store.projects.values()):
            normalized_templates = [item for item in project.enabled_templates if item not in DISABLED_TEMPLATE_IDS]
            if normalized_templates != project.enabled_templates:
                project.enabled_templates = normalized_templates
                self.store.save_project(project)
            normalized = self.config.normalize_basemap(project.base_map)
            if normalized != project.base_map:
                self.store.set_basemap(project.project_id, normalized)

    def _fail_job(self, job_id: str, workflow_type: str, message: str) -> None:
        self.store.update_job_stage(job_id, "artifacts", "error", message)
        self.store.set_job_status(
            job_id,
            "failed",
            result={"status": "error", "workflow_type": workflow_type, "summary": message, "assistant_message": message, "stages": self.store.get_job(job_id).stages},
            error=message,
        )

    def _require_project(self, project_id: str) -> ProjectRecord:
        project = self.store.get_project(project_id)
        if not project:
            raise KeyError(f"Unknown project: {project_id}")
        return project
