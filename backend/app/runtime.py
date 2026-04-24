from __future__ import annotations

import base64
import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import AppConfig
from .models import LayerRecord, ProjectRecord, build_workflow_stages
from .services.assistant import ASSISTANT_TOOL_SCHEMA, AssistantService
from .services.datasets import DatasetService
from .services.llm_planner import LLMPlanner
from .services.minimax_client import MiniMaxClient
from .services.poi import PoiService
from .services.qgis_bridge import QGIS_ALLOWED_TOOLS, QgisBridgeClient
from .services.templates import TemplateService
from .store import RuntimeStore


class WebGISRuntime:
    def __init__(self, config: Optional[AppConfig] = None, store: Optional[RuntimeStore] = None):
        self.config = config or AppConfig()
        self.config.ensure_dirs()
        self.store = store or RuntimeStore(self.config.state_file)
        self.dataset_service = DatasetService(self.config, self.store)
        self.template_service = TemplateService(self.config, self.store)
        self.assistant_service = AssistantService(self.config)
        self.poi_service = PoiService(self.config, self.store)
        self.minimax_client = MiniMaxClient(self.config)
        self.qgis_bridge = QgisBridgeClient(self.config)
        self.llm_planner = LLMPlanner(self.minimax_client, self.assistant_service, self.qgis_bridge)
        self._normalize_loaded_projects()

    def health(self) -> Dict[str, Any]:
        return {
            "status": "success",
            "runtime": {
                "api": f"http://{self.config.host}:{self.config.port}",
                "workspace": str(self.config.root_dir),
                "uploads": str(self.config.uploads_dir),
                "outputs": str(self.config.outputs_dir),
            },
            "ui": {
                "mode": "single_teacher_live_demo",
                "assistant_tools": ASSISTANT_TOOL_SCHEMA,
            },
            "online_services": {
                "amap_poi_enabled": self.config.online_services_enabled(),
            },
            "llm": self.minimax_client.status(),
            "qgis": self.config.qgis_status_config(),
            "basemaps": self.config.basemap_catalog(),
            "templates": self.template_service.list_templates()["items"],
        }

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
        target: str = "webgis",
    ) -> Dict[str, Any]:
        normalized_target = target if target in {"webgis", "qgis", "auto"} else "webgis"
        job = self.store.create_job(
            project_id=project_id,
            job_type="assistant",
            title="课堂助教请求",
            workflow_type="assistant_message",
            request={"message": message, "map_context": map_context or {}, "target": normalized_target},
        )
        threading.Thread(
            target=self._run_assistant_job,
            args=(job.job_id, project_id, message, map_context or {}, normalized_target),
            daemon=True,
        ).start()
        return {"status": "accepted", "job_id": job.job_id, "project_id": project_id}

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
        return {"status": "success", "items": self.store.list_outputs(project_id=project_id)}

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

    def _run_assistant_job(self, job_id: str, project_id: str, message: str, map_context: Dict[str, Any], target: str = "webgis") -> None:
        try:
            project = self._require_project(project_id)
            self.store.set_job_status(job_id, "running")
            self.store.append_job_step(job_id, "解析指令", "正在理解课堂助教请求。", "running")
            self.store.update_job_stage(job_id, "analysis", "running", "正在分析课堂意图。")
            plan = self.llm_planner.plan_actions(message, project, map_context=map_context, target=target)
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
                    "actions": plan.get("actions", []),
                    "actions_executed": executed_actions,
                    "artifacts": registered_artifacts,
                    "stages": self.store.get_job(job_id).stages,
                },
            )
        except Exception as exc:  # pragma: no cover - defensive runtime branch
            self._fail_job(job_id, "assistant_message", str(exc))

    def _execute_qgis_action(self, action: Dict[str, Any]) -> Dict[str, Any]:
        tool_name = action["tool_name"]
        params = action.get("tool_params", {})
        if tool_name not in QGIS_ALLOWED_TOOLS:
            raise ValueError(f"QGIS tool is not allowed: {tool_name}")
        response = self.qgis_bridge.execute(tool_name, params)
        status = str(response.get("status") or "")
        if status and status not in {"success", "ok"}:
            raise ValueError(str(response.get("message") or f"QGIS tool failed: {tool_name}"))
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

    def _normalize_loaded_projects(self) -> None:
        for project in list(self.store.projects.values()):
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
