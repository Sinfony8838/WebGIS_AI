"""Validated adapters from voice goals to existing project services."""
from __future__ import annotations

import copy
import json
import re
import time
from pathlib import Path
from threading import RLock
from uuid import uuid4
from typing import Any, Dict

from ..models import WorkflowRecord
from .agent_capabilities import OP_KEYS
from .agent_harness import HarnessPolicy
from .interaction_run import InteractionRun, RunStopped, current_run
from .workflow_validator import WorkflowValidator, REFERENCE_PATTERN

_SAFE_FUNCTIONS = {"abs", "round", "floor", "ceil", "sqrt", "ln", "log", "log10", "exp", "pow", "min", "max", "clamp", "coalesce", "if", "nullif", "to_real", "to_int", "to_string", "lower", "upper", "length", "trim", "concat", "replace", "substr", "area", "perimeter", "x", "y", "and", "or", "not"}


def _expression(expression: Any) -> None:
    if not isinstance(expression, str) or not expression.strip() or len(expression) > 1500:
        raise ValueError("表达式不能为空且最多1500字符。")
    bare = re.sub(r"\"(?:[^\"]|\"\")*\"|'(?:[^']|'')*'", "", expression)
    functions = {name.lower() for name in re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(", bare)}
    if functions - _SAFE_FUNCTIONS or "@" in bare or ";" in bare:
        raise ValueError("表达式包含不支持的函数或外部上下文；请使用字段、算术与允许的 QGIS 函数。")


def prepare_generated_workflow(runtime: Any, project_id: str, payload: Any) -> Dict[str, Any]:
    """Compile the existing DSL; only server-bound project datasets may enter it."""
    if not isinstance(payload, dict) or set(payload) - {"steps", "title", "name", "outputs", "project_id"}:
        raise ValueError("生成工作流必须使用 steps 结构，不能包含脚本或嵌套工作流。")
    if payload.get("project_id", project_id) != project_id:
        raise ValueError("工作流不属于当前项目。")
    workflow = copy.deepcopy(payload)
    steps = workflow.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= 8:
        raise ValueError("生成工作流必须包含1至8步。")
    project = runtime._require_project(project_id)
    layers = {"layer:" + layer.layer_id: layer for layer in project.layers}
    seen = set()
    sources = []
    for step in steps:
        if not isinstance(step, dict) or set(step) - {"id", "op", "params", "title"}:
            raise ValueError("步骤只接受 id、op、params 与 title。")
        op, params = step.get("op"), step.get("params")
        if op not in OP_KEYS or not isinstance(params, dict) or set(params) - OP_KEYS[op]:
            raise ValueError(f"不支持的分析操作或参数：{op}")
        for key in ("input", "clip_layer", "overlay_layer", "join_layer"):
            if key in params:
                match = REFERENCE_PATTERN.fullmatch(str(params[key]))
                if not match or match[1] not in seen:
                    raise ValueError(f"{key} 必须引用前序步骤的结果。")
        if op == "export_map_png":
            refs = params.get("layers")
            if not isinstance(refs, list) or not refs or any(not REFERENCE_PATTERN.fullmatch(str(ref)) or REFERENCE_PATTERN.fullmatch(str(ref))[1] not in seen for ref in refs):
                raise ValueError("地图导出必须引用前序步骤的图层。")
            for key in ("width", "height"):
                if key in params and (not isinstance(params[key], int) or not 1 <= params[key] <= 4096):
                    raise ValueError("导出图片尺寸必须在1至4096之间。")
        if "expression" in params:
            _expression(params["expression"])
        if "name" in params and (not isinstance(params["name"], str) or re.search(r"[\\/:]|\.\.", params["name"])):
            raise ValueError("产物名称不能包含路径。")
        if op == "load_layer":
            source = params.get("source")
            if source not in layers:
                raise ValueError("数据源必须来自当前项目 datasets 中的 layer:<id>；请先加载所需数据。")
            sources.append((params, "source", layers[source]))
        if op == "zonal_stats":
            source = params.get("raster")
            if isinstance(source, str) and REFERENCE_PATTERN.fullmatch(source):
                if REFERENCE_PATTERN.fullmatch(source)[1] not in seen:
                    raise ValueError("栅格必须引用前序结果。")
            elif source in layers:
                sources.append((params, "raster", layers[source]))
            else:
                raise ValueError("栅格数据必须属于当前项目。")
        seen.add(str(step.get("id") or ""))
    validation = WorkflowValidator().validate(workflow)
    if not validation.valid:
        raise ValueError("；".join(error.user_friendly for error in validation.errors))
    # Bind immutable snapshots after all structural/expression checks pass.
    bound_sources = {}
    for params, key, layer in sources:
        if layer.layer_id in bound_sources:
            params[key] = bound_sources[layer.layer_id]
            params["project_id"] = project_id
            continue
        data = layer.data or {}
        if data.get("type") != "FeatureCollection":
            # Raster references may only resolve from server-owned layer metadata.
            raw = str((layer.metadata or {}).get("dataset_source") or "")
            from .workflow_executor import _resolve_dataset_for_preflight
            path = _resolve_dataset_for_preflight(runtime.config, raw, project_id) if raw else None
            if path is None:
                raise ValueError(f"图层“{layer.name}”没有可分析的数据，请先导入或加载数据。")
            params[key] = raw
        else:
            name = "agent-input-" + uuid4().hex + ".geojson"
            root = (runtime.config.uploads_dir / project_id).resolve()
            root.relative_to(runtime.config.uploads_dir.resolve())
            root.mkdir(parents=True, exist_ok=True)
            with (root / name).open("x", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False)
            params[key] = f"upload:{project_id}/{name}"
        params["project_id"] = project_id
        bound_sources[layer.layer_id] = params[key]
    workflow["project_id"] = project_id
    return workflow


class InteractionOperations:
    def __init__(self, runtime: Any):
        self.runtime = runtime
        self.store = runtime.store
        self._active: Dict[str, InteractionRun] = {}
        self._lock = RLock()

    def create_run(self, job_id: str) -> InteractionRun:
        job = self.store.get_job(job_id)
        run = InteractionRun(job_id=job_id, mode=str(job.request.get("assistant_mode") or ""),
            max_seconds=HarnessPolicy.from_config(self.runtime.config).max_seconds,
            cancelled=lambda: bool(self.store.get_job(job_id).activity.get("cancel_requested")),
            publish=lambda activity, usage: self.store.update_job_activity(job_id, activity, usage))
        if job.job_type == "assistant_confirmation":
            confirmation = self.store.get_confirmation(job.request.get("confirmation_id", ""))
            parent = self.store.get_job(confirmation.job_id) if confirmation else None
            if parent:
                usage = parent.usage or {}
                run.calls = int(usage.get("model_calls") or 0)
                run.input_tokens = int(usage.get("input_tokens") or 0)
                run.output_tokens = int(usage.get("output_tokens") or 0)
                run.unknown_usage = usage.get("input_tokens") is None or usage.get("output_tokens") is None
                run.model_ms = float(usage.get("model_ms") or 0)
                run.route = str(usage.get("route") or "direct")
                run.search_calls = int(usage.get("search_calls") or 0)
                run.search_ms = float(usage.get("search_ms") or 0)
                run.started -= float(usage.get("elapsed_ms") or 0) / 1000
        run.observe_ui = lambda actions: self.observe_ui(run, actions)
        with self._lock:
            self._active[job_id] = run
        return run

    def finish_run(self, job_id: str) -> None:
        with self._lock:
            self._active.pop(job_id, None)

    def cancel(self, job_id: str) -> Dict[str, Any]:
        job = self.store.get_job(job_id)
        if job is None or job.job_type not in {"assistant", "assistant_confirmation"}:
            raise KeyError("Unknown assistant job")
        if job.status in {"completed", "failed"}:
            return {"status": "already_finished", "job_id": job_id}
        self.store.update_job_activity(job_id, {**job.activity, "cancel_requested": True, "phase": "stopping", "label": "正在停止操作"})
        with self._lock:
            run = self._active.get(job_id)
        if run:
            run.close_requests()
        return {"status": "stopping", "job_id": job_id}

    def observe_ui(self, run: InteractionRun, actions: list) -> list:
        if not actions:
            return []
        run.check()
        job = self.store.get_job(run.job_id)
        session_id = str((job.request.get("teaching_context") or job.request.get("map_context", {}).get("teaching_context") or {}).get("session_id") or "")
        protocol = job.request.get("ui_observation_protocol", 0)
        expires_at = time.time() + 8.0
        batch = [{**action, "expires_at": expires_at, "action_id": "uia_" + uuid4().hex, "project_id": job.project_id,
                  "session_id": session_id, "status": "pending", "observation": None} for action in actions]
        self.store.update_job_activity(job.job_id, ui_actions=job.ui_actions + batch)
        run.emit("verifying", "正在核对结果")
        if protocol != 1:
            for item in batch:
                item["status"] = "unconfirmed"
            self.store.update_job_activity(job.job_id, ui_actions=job.ui_actions)
            return [{"action_id": item["action_id"], "status": "unconfirmed", "detail": "客户端未启用界面回执。"} for item in batch]
        deadline = time.monotonic() + min(8.0, run.remaining_seconds())
        try:
            while time.monotonic() < deadline:
                run.check()
                if all(item.get("observation") is not None for item in batch):
                    return [item["observation"] for item in batch]
                self.store.wait_for_job_update(job.job_id, job.updated_at, timeout=0.1)
        finally:
            for item in batch:
                if item.get("status") == "pending":
                    item["status"] = "unconfirmed"
            self.store.update_job_activity(job.job_id, ui_actions=job.ui_actions)
        return [item.get("observation") or {"action_id": item["action_id"], "status": "unconfirmed", "detail": "未收到界面应用回执。"} for item in batch]

    def acknowledge(self, job_id: str, payload: Dict[str, Any], actor_user_id: str) -> Dict[str, Any]:
        job = self.store.get_job(job_id)
        if job is None:
            raise KeyError("Unknown job")
        owner = str(job.request.get("actor_user_id") or "")
        if owner and owner != actor_user_id:
            raise PermissionError("只能确认自己发起的任务。")
        action_id = str(payload.get("action_id") or "")
        action = next((item for item in job.ui_actions if item.get("action_id") == action_id), None)
        if action is None or payload.get("project_id") != job.project_id or str(payload.get("session_id") or "") != action.get("session_id"):
            raise ValueError("界面回执与项目、课堂或任务不匹配。")
        if action.get("observation") is None and float(action.get("expires_at", 0)) < time.time():
            raise ValueError("界面动作已过期。")
        status = payload.get("status")
        if status not in {"applied", "failed", "unconfirmed"}:
            raise ValueError("无效的界面回执状态。")
        observation = {"action_id": action_id, "status": status, "detail": str(payload.get("detail") or "")[:300]}
        item = self.store.observe_ui_action(job_id, action_id, observation)
        return {"status": "success", "action": item}

    def template_parameters(self, project_id: str, template_id: str, description: str, supplied: Any) -> Dict[str, Any]:
        params = copy.deepcopy(supplied) if isinstance(supplied, dict) else {}
        project = self.runtime._require_project(project_id)
        if template_id in {"facility_buffer", "classify_field"} and not any(key in params for key in ("dataset", "facility_dataset", "input_dataset")):
            matched = [layer for layer in project.layers if layer.name and layer.name in description]
            if not matched and any(word in description for word in ("当前图层", "活动图层", "这个图层")):
                matched = [layer for layer in project.layers if layer.layer_id == project.active_layer_id]
            if len(matched) == 1:
                params["dataset"] = "layer:" + matched[0].layer_id
            elif len(matched) > 1 or "图层" in description or template_id == "facility_buffer":
                raise ValueError("请明确选择一个要分析的项目图层。")
        second_key = {"clip_to_region": "region_dataset", "overlay_intersection": "overlay_dataset", "spatial_join_attributes": "join_dataset"}.get(template_id)
        if second_key:
            matched = sorted([layer for layer in project.layers if layer.name and layer.name in description], key=lambda layer: description.index(layer.name))
            if len(matched) == 2:
                params.setdefault("input_dataset", "layer:" + matched[0].layer_id)
                params.setdefault(second_key, "layer:" + matched[1].layer_id)
            if not (params.get("input_dataset") or params.get("dataset")) or not params.get(second_key):
                raise ValueError("该分析需要明确指定当前项目中的两个数据图层。")
        for key, source in list(params.items()):
            if (key == "dataset" or key.endswith("_dataset")) and isinstance(source, str) and source.startswith("layer:"):
                bound = prepare_generated_workflow(self.runtime, project_id, {"steps": [{"id": "source", "op": "load_layer", "params": {"source": source}}]})
                params[key] = bound["steps"][0]["params"]["source"]
        return params

    def execute(self, project_id: str, action: Dict[str, Any], map_context: Dict[str, Any]) -> Dict[str, Any]:
        run = current_run()
        if run is None:
            raise ValueError("创造性操作必须在受预算控制的任务内执行。")
        run.check()
        params = action.get("tool_params") or {}
        if action["tool_name"] == "build_workflow":
            workflow = prepare_generated_workflow(self.runtime, project_id, params.get("workflow"))
            record = WorkflowRecord.create(project_id, user_message=str(params.get("title") or "语音生成分析"),
                intent="generated_analysis", mode="assistant_generated", workflow_json=workflow)
            run.check()
            record, _ = self.runtime.workflow_executor.submit(record)
            return self.await_workflow(record.workflow_id, run)
        if action["tool_name"] == "draft_teaching":
            return self.draft_teaching(project_id, params, run)
        raise ValueError("Unknown creative operation")

    def await_workflow(self, workflow_id: str, run: InteractionRun) -> Dict[str, Any]:
        try:
            while True:
                run.check()
                record = self.store.get_workflow(workflow_id)
                if record is None:
                    raise ValueError("找不到已提交的分析任务。")
                states = record.steps or []
                running = next((item for item in states if item.get("status") == "running"), None)
                label = str((running or {}).get("op") or "空间分析")
                activity = {"workflow_id": workflow_id, "tool": label}
                if run.activity.get("tool") != label or run.activity.get("workflow_id") != workflow_id:
                    run.emit("tool_running", "智能体调用工具中 · 空间分析", **activity)
                if record.status in {"success", "error", "cancelled"}:
                    break
                time.sleep(0.05)
        except RunStopped:
            self.runtime.workflow_executor.cancel_workflow(workflow_id)
            raise
        if record.status != "success":
            error = record.error or {}
            return {"status": record.status, "assistant_message": str(error.get("user_friendly") or "分析未完成。"),
                    "workflow": {"workflow_id": workflow_id, "status": record.status}, "error": error, "artifacts": []}
        facts, artifacts, layer_ids = [], [], []
        for state in record.steps:
            outputs = state.get("outputs") or {}
            row = {key: value for key, value in outputs.items() if key in {"feature_count", "fields", "breaks", "crs", "extent", "summary", "sample", "classification"}}
            stats_path = outputs.get("stats")
            if isinstance(stats_path, str):
                path = Path(stats_path).resolve()
                try:
                    path.relative_to(self.runtime.config.workflow_dir(workflow_id).resolve())
                    if path.is_file() and path.stat().st_size <= 2_000_000:
                        stats = json.loads(path.read_text(encoding="utf-8"))
                        if isinstance(stats, dict):
                            row["statistics"] = {key: stats[key] for key in ("summary", "all_rows_count", "sample_rows_count", "fields") if key in stats}
                            row["statistics"]["rows"] = (stats.get("rows") or [])[:10]
                except (ValueError, OSError):
                    pass
            if row:
                facts.append({"step_id": state.get("id"), "op": state.get("op"), "outputs": row})
        project = self.runtime._require_project(record.project_id)
        for artifact_id in list(project.artifact_ids):
            artifact = self.store.get_artifact(artifact_id)
            if artifact and (artifact.metadata or {}).get("workflow_id") == workflow_id:
                artifacts.append({"artifact_id": artifact_id, "title": artifact.title, "public_url": artifact.metadata.get("public_url", ""), "kind": artifact.metadata.get("kind")})
                if artifact.metadata.get("kind") == "geojson":
                    run.check()
                    loaded = self.runtime.load_output_as_layer(record.project_id, artifact_id)
                    layer_ids.append(loaded["item"]["layer_id"])
        return {"status": "success", "assistant_message": f"分析已完成，生成{len(layer_ids)}个结果图层和{len(artifacts)}项产物。",
                "workflow": {"workflow_id": workflow_id, "status": "success"}, "facts": facts,
                "layer_ids": layer_ids, "outputs": artifacts, "artifacts": []}

    def draft_teaching(self, project_id: str, params: Dict[str, Any], run: InteractionRun) -> Dict[str, Any]:
        draft = params.get("draft")
        allowed = {"title", "objectives", "core_questions", "stages", "homework", "board_design", "design_thinking"}
        if not isinstance(draft, dict) or set(draft) - allowed or not str(draft.get("title") or "").strip():
            raise ValueError("教学草稿需要标题，只能包含已声明的草稿章节。")
        if not isinstance(draft.get("objectives", []), list) or not isinstance(draft.get("stages", []), list):
            raise ValueError("目标和教学环节必须为数组。")
        if "homework" in draft and (not isinstance(draft["homework"], dict) or any(not isinstance(value, list) for value in draft["homework"].values())):
            raise ValueError("作业应使用 basic、inquiry 题目数组。")
        for stage in draft.get("stages", []):
            if not isinstance(stage, dict) or not str(stage.get("title") or "").strip():
                raise ValueError("每个教学环节需要标题。")
        evidence_ids = params.get("evidence_ids") or []
        evidence = {item["observation_id"]: item for item in run.observations if item.get("status") == "success"}
        if any(item not in evidence for item in evidence_ids):
            raise ValueError("教学引用必须来自当前项目已经成功执行的结果。")
        job = self.store.get_job(run.job_id)
        depends_on_results = any(item.get("job_id") == run.job_id and item.get("action", {}).get("tool_name") in {"build_workflow", "run_workflow", "run_visual_query", "query_features"} for item in run.observations)
        depends_on_results = depends_on_results or bool(re.search(r"刚才|结果|根据|基于", str((job.request if job else {}).get("message") or "")))
        if depends_on_results and not evidence_ids:
            raise ValueError("根据分析结果生成教学内容时必须填写 evidence_ids。")
        owner = str((job.request if job else {}).get("actor_user_id") or self.runtime._require_project(project_id).owner_user_id or "local_teacher")
        service = self.runtime.classroom.lesson_design
        run.check()
        source_refs = [{"id": key, "title": "语音分析执行结果", "source_type": "execution", "job_id": run.job_id,
                        "evidence": copy.deepcopy(evidence[key]["result"])} for key in evidence_ids]
        design, report = service.create_generated_draft(project_id, owner, draft, source_refs,
            {"trigger": "voice_agent", "job_id": run.job_id})
        return {"status": "success", "assistant_message": "已创建独立教学草稿，可在教案设计中查看和继续编辑。",
                "design_id": design.design_id, "title": design.draft.get("title"),
                "validation": report, "artifacts": []}
