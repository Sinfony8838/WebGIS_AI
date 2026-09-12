"""Workflow orchestration on the FastAPI side.

Responsibilities:
* register a :class:`WorkflowRecord` with the runtime store;
* maintain in-memory event subscribers so the SSE endpoint can stream
  ``workflow_created``, ``step_started``, ``step_success``, ``step_error``,
  ``workflow_success`` and ``workflow_error`` events to the frontend;
* run the steps sequentially through :class:`PyQgisWorkerManager`, resolving
  ``depends_on`` via topological order;
* persist the final ``workflow.json`` and ``status.json`` files into the
  workflow's working directory and register output artifacts;
* call the optional summary generator (LLM-backed) once execution succeeds.

This module never imports ``qgis.core`` and never touches the worker side
state directly.
"""
from __future__ import annotations

import json
import logging
import queue
import re
import threading
import time
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Tuple

from ..config import AppConfig
from ..models import WorkflowArtifact, WorkflowRecord, utc_now
from ..store import RuntimeStore
from .pyqgis_worker import PyQgisWorkerManager
from .pyqgis_worker.errors import make_error
from .workflow_validator import ValidationError, ValidationResult, validate_workflow


logger = logging.getLogger(__name__)

#: Mapping of step output keys to (artifact_kind, default_title) for outputs
#: that should be exposed as ``WorkflowArtifact`` rows. The frontend reads the
#: artifact list to know which files to fetch.
_ARTIFACT_KEYS: Tuple[Tuple[str, str, str], ...] = (
    ("geojson", "geojson", "结果矢量"),
    ("style", "style", "图层样式"),
    ("stats", "stats", "统计结果"),
    ("png", "png", "地图图片"),
    ("summary", "summary", "AI 解释"),
)


# ---------------------------------------------------------------------------
# Preflight (small, data-aware checks run BEFORE a workflow is dispatched)
# ---------------------------------------------------------------------------

#: GeoJSON files larger than this skip field/CRS inspection (preflight must
#: stay cheap; the worker does the authoritative validation anyway).
_PREFLIGHT_MAX_GEOJSON_BYTES = 32 * 1024 * 1024

#: Which params of an op hold ``${step.key}`` layer references we can trace
#: back to a ``load_layer`` dataset.
_LAYER_REF_PARAMS: Dict[str, Tuple[str, ...]] = {
    "inspect_layer": ("input",),
    "reproject": ("input",),
    "fix_geometries": ("input",),
    "filter_features": ("input",),
    "calculate_field": ("input",),
    "buffer": ("input",),
    "choropleth": ("input",),
    "aggregate_stats": ("input",),
    "export_geojson": ("input",),
    "export_map_png": ("layers",),
    "clip": ("input", "clip_layer"),
    "intersection": ("input", "overlay_layer"),
    "spatial_join": ("input", "join_layer"),
    "classify": ("input",),
    "zonal_stats": ("input",),
}


def _resolve_dataset_for_preflight(
    config: AppConfig, source: str, project_id: str
) -> Optional[Path]:
    """Resolve a ``load_layer`` source to an existing file path.

    Mirrors the worker's ``resolve_dataset_path`` (builtin:/upload:/bare name)
    without importing QGIS. Returns None when nothing matches so the caller
    can raise an accurate DATASET_NOT_FOUND preflight error.
    """
    cleaned = (source or "").strip()
    if not cleaned:
        return None
    if cleaned.startswith("builtin:"):
        rest = cleaned.removeprefix("builtin:").lstrip("/").replace("\\", "/")
        for root in (config.data_dir / "builtin", config.builtin_dir):
            candidate = (root / rest).resolve()
            if candidate.exists() and str(candidate).startswith(str(root.resolve())):
                return candidate
        return None
    if cleaned.startswith("upload:"):
        rest = cleaned.removeprefix("upload:").lstrip("/").replace("\\", "/")
        uploads_root = config.uploads_dir.resolve()
        candidate = (uploads_root / rest).resolve()
        if candidate.exists() and str(candidate).startswith(str(uploads_root)):
            return candidate
        return None
    # Bare file name: uploads/<project_id>/ first, then builtin roots.
    if project_id:
        candidate = (config.uploads_dir / project_id / cleaned).resolve()
        if candidate.exists():
            return candidate
    for root in (config.data_dir / "builtin", config.builtin_dir):
        candidate = (root / cleaned).resolve()
        if candidate.exists():
            return candidate
    return None


def _read_geojson_fields(path: Path) -> Optional[List[str]]:
    """Return the property names of the first GeoJSON feature.

    Returns None when the file is not inspectable (too large, unreadable, or
    not parseable) — preflight then skips field checks for that dataset
    instead of blocking a run the worker might still handle fine.
    """
    try:
        if path.stat().st_size > _PREFLIGHT_MAX_GEOJSON_BYTES:
            return None
        if path.suffix.lower() not in {".geojson", ".json"}:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("features"), list):
        return None
    for feature in data["features"]:
        properties = feature.get("properties") if isinstance(feature, dict) else None
        if isinstance(properties, dict) and properties:
            return [str(key) for key in properties.keys()]
    return None


def _read_geojson_crs(path: Path) -> Optional[str]:
    """Best-effort CRS name from a GeoJSON ``crs`` member (None if absent)."""
    try:
        if path.suffix.lower() not in {".geojson", ".json"}:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    crs = data.get("crs")
    if isinstance(crs, dict):
        properties = crs.get("properties")
        if isinstance(properties, dict) and isinstance(properties.get("name"), str):
            return properties["name"]
    return None


def _quoted_identifiers(expression: str) -> List[str]:
    """Extract ``"..."``-quoted identifiers from a QGIS-style expression.

    Double quotes in QGIS expressions denote field references (string
    literals use single quotes), so every quoted token must exist on the
    input layer or the step fails at runtime.
    """
    return re.findall(r'"([^"]+)"', expression or "")


class _PreflightContext:
    """Resolves ``${step.key}`` input chains back to their source datasets."""

    def __init__(self, config: AppConfig, steps: List[Dict[str, Any]]) -> None:
        self.config = config
        self.steps = {str(step.get("id")): step for step in steps if isinstance(step, dict) and step.get("id")}
        self._dataset_cache: Dict[str, Optional[Path]] = {}
        self._fields_cache: Dict[str, Optional[List[str]]] = {}

    def source_of(self, step_id: str, visited: Optional[set] = None) -> Optional[Tuple[str, Path]]:
        """Trace a layer reference to (source_string, resolved_path).

        Walks ``input`` / ``clip_layer`` / ... chains through intermediate ops
        until it reaches a ``load_layer``. Returns None when the chain cannot
        be traced (foreign reference, unresolvable dataset, cycle).
        """
        visited = visited if visited is not None else set()
        if step_id in visited:
            return None
        visited.add(step_id)
        step = self.steps.get(step_id)
        if step is None:
            return None
        op = str(step.get("op") or "")
        params = step.get("params") or {}
        if op == "load_layer":
            source = params.get("source")
            if not isinstance(source, str):
                return None
            project_id = str(params.get("project_id") or "")
            if source not in self._dataset_cache:
                self._dataset_cache[source] = _resolve_dataset_for_preflight(
                    self.config, source, project_id
                )
            path = self._dataset_cache[source]
            if path is None:
                return None
            return source, path
        ref_params = _LAYER_REF_PARAMS.get(op, ("input",))
        for param_name in ref_params:
            value = params.get(param_name)
            if isinstance(value, list):
                value = value[0] if value else None
            if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                target = value[2:-1].split(".", 1)[0]
                found = self.source_of(target, visited)
                if found is not None:
                    return found
        return None

    def fields_for(self, step_id: str) -> Optional[List[str]]:
        """Fields available on the output of ``step_id``.

        Combines the source dataset's fields with fields added along the
        chain (calculate_field / classify). Returns None when unavailable.
        """
        if step_id in self._fields_cache:
            return self._fields_cache[step_id]
        result: Optional[List[str]] = None
        step = self.steps.get(step_id)
        if step is not None:
            op = str(step.get("op") or "")
            params = step.get("params") or {}
            source = self.source_of(step_id)
            if source is not None:
                fields = _read_geojson_fields(source[1])
                if fields is not None:
                    result = list(fields)
            # Walk the chain again to collect added fields between the
            # source and this step.
            if result is not None:
                result = result + self._added_fields(step_id, set())
        self._fields_cache[step_id] = result
        return result

    def _added_fields(self, step_id: str, visited: set) -> List[str]:
        added: List[str] = []
        if step_id in visited:
            return added
        visited.add(step_id)
        step = self.steps.get(step_id)
        if step is None:
            return added
        op = str(step.get("op") or "")
        params = step.get("params") or {}
        if op == "load_layer":
            return added
        ref_params = _LAYER_REF_PARAMS.get(op, ("input",))
        for param_name in ref_params:
            value = params.get(param_name)
            if isinstance(value, list):
                value = value[0] if value else None
            if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                target = value[2:-1].split(".", 1)[0]
                added.extend(self._added_fields(target, visited))
        if op == "calculate_field" and isinstance(params.get("field"), str):
            added.append(params["field"])
        elif op == "classify":
            output_field = str(params.get("output_field") or "").strip()
            field = str(params.get("field") or "").strip()
            added.append(output_field or f"{field}_class")
        return added


def run_preflight(
    config: AppConfig, workflow: Dict[str, Any]
) -> Tuple[List[ValidationError], List[ValidationError]]:
    """Check runnability before dispatching the workflow thread.

    Small and practical: verifies every ``load_layer`` dataset exists, that
    referenced fields (choropleth/classify fields, aggregate stats columns,
    quoted identifiers in expressions) exist on the resolved source, and that
    the declared GeoJSON CRS is the web-standard EPSG:4326. Structural
    problems (missing required params, unknown ops) are already covered by
    :class:`WorkflowValidator`; this pass catches the data-level breakages
    that otherwise surface as a doomed background run.

    Returns (errors, warnings); only errors block submission.
    """
    errors: List[ValidationError] = []
    warnings: List[ValidationError] = []
    steps = workflow.get("steps") or []
    context = _PreflightContext(config, steps if isinstance(steps, list) else [])

    for step in steps:
        if not isinstance(step, dict):
            continue
        step_id = str(step.get("id") or "")
        op = str(step.get("op") or "")
        params = step.get("params") or {}

        if op == "load_layer":
            source = params.get("source")
            if isinstance(source, str) and source.strip():
                project_id = str(params.get("project_id") or "")
                path = _resolve_dataset_for_preflight(config, source, project_id)
                if path is None:
                    errors.append(ValidationError(
                        code="DATASET_NOT_FOUND",
                        message=f"dataset not found: {source}",
                        user_friendly=f"找不到数据集 {source}（步骤 {step_id}）。请确认数据已上传，或在数据集下拉里重新选择。",
                        step_id=step_id,
                        field="source",
                    ))
                    continue
                crs_name = _read_geojson_crs(path)
                if crs_name and not any(token in crs_name.upper() for token in ("4326", "CRS84")):
                    warnings.append(ValidationError(
                        code="CRS_NOT_SUPPORTED",
                        message=f"dataset {source} declares CRS {crs_name}",
                        user_friendly=(
                            f"数据集 {source} 的坐标系是 {crs_name}，不是网页常用的 EPSG:4326，"
                            f"结果位置可能偏离底图（步骤 {step_id}）。"
                        ),
                        step_id=step_id,
                        field="crs",
                    ))

        # Field existence checks against the traced source dataset.
        input_param = params.get("input")
        input_ref = input_param if isinstance(input_param, str) else None
        if input_ref and input_ref.startswith("${") and input_ref.endswith("}"):
            input_step = input_ref[2:-1].split(".", 1)[0]
            fields = context.fields_for(input_step)
        else:
            fields = None

        if fields is not None:
            available = ", ".join(fields)

            def _field_missing(field_name: str, field_label: str) -> None:
                errors.append(ValidationError(
                    code="FIELD_NOT_FOUND",
                    message=f"layer has no field '{field_name}'",
                    user_friendly=f"图层中找不到字段「{field_name}」（步骤 {step_id} 的{field_label}）。可用字段：{available}。请修正字段名后重新运行。",
                    step_id=step_id,
                    field=field_name,
                ))

            if op == "choropleth":
                field_name = str(params.get("field") or "")
                if field_name and field_name not in fields:
                    _field_missing(field_name, "分级字段")
            elif op == "classify":
                field_name = str(params.get("field") or "")
                if field_name and field_name not in fields:
                    _field_missing(field_name, "分级字段")
            elif op == "aggregate_stats":
                raw_fields = params.get("fields") or []
                if isinstance(raw_fields, str):
                    raw_fields = [raw_fields]
                for field_name in raw_fields:
                    field_name = str(field_name)
                    if field_name and field_name not in fields:
                        _field_missing(field_name, "统计字段")
                label_field = str(params.get("label_field") or "")
                if label_field and label_field not in fields:
                    errors.append(ValidationError(
                        code="FIELD_NOT_FOUND",
                        message=f"layer has no field '{label_field}'",
                        user_friendly=f"图层中找不到标签字段「{label_field}」（步骤 {step_id}）。可用字段：{available}。",
                        step_id=step_id,
                        field=label_field,
                    ))
            elif op in {"calculate_field", "filter_features"}:
                expression = str(params.get("expression") or "")
                for identifier in _quoted_identifiers(expression):
                    if identifier not in fields:
                        errors.append(ValidationError(
                            code="FIELD_NOT_FOUND",
                            message=f"expression references unknown field '{identifier}'",
                            user_friendly=(
                                f"表达式里的字段「{identifier}」在该图层中不存在（步骤 {step_id}）。"
                                f"可用字段：{available}。请修正表达式后重新运行。"
                            ),
                            step_id=step_id,
                            field=identifier,
                        ))

    return errors, warnings


def _compose_issue_message(errors: List[ValidationError], fallback: str) -> str:
    """Join validation/preflight issues into one readable sentence chain."""
    parts = [error.user_friendly for error in errors if error.user_friendly]
    message = "；".join(parts)
    if len(message) > 400:
        message = message[:397] + "…"
    return message or fallback


@dataclass
class _Event:
    type: str
    payload: Dict[str, Any] = dataclass_field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"type": self.type, "payload": self.payload, "timestamp": time.time()}


class _EventBus:
    """In-memory pub-sub keyed by workflow_id; subscribers are queue.Queue."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._subscribers: Dict[str, List["queue.Queue[Optional[_Event]]"]] = {}
        self._history: Dict[str, List[_Event]] = {}

    def publish(self, workflow_id: str, event: _Event) -> None:
        with self._lock:
            self._history.setdefault(workflow_id, []).append(event)
            for q in self._subscribers.get(workflow_id, []):
                try:
                    q.put_nowait(event)
                except Exception:  # pragma: no cover
                    pass

    def subscribe(self, workflow_id: str) -> "queue.Queue[Optional[_Event]]":
        q: "queue.Queue[Optional[_Event]]" = queue.Queue()
        with self._lock:
            for past in self._history.get(workflow_id, []):
                q.put_nowait(past)
            self._subscribers.setdefault(workflow_id, []).append(q)
        return q

    def unsubscribe(self, workflow_id: str, q: "queue.Queue[Optional[_Event]]") -> None:
        with self._lock:
            subs = self._subscribers.get(workflow_id, [])
            if q in subs:
                subs.remove(q)
            try:
                q.put_nowait(None)
            except Exception:  # pragma: no cover
                pass

    def history(self, workflow_id: str) -> List[_Event]:
        with self._lock:
            return list(self._history.get(workflow_id, []))


class WorkflowExecutor:
    """High-level orchestrator used by the FastAPI endpoints."""

    def __init__(
        self,
        config: AppConfig,
        store: RuntimeStore,
        worker_manager: Optional[PyQgisWorkerManager] = None,
        summary_callback: Optional[Callable[[WorkflowRecord, Dict[str, Any]], Optional[str]]] = None,
    ) -> None:
        self.config = config
        self.store = store
        self.worker_manager = worker_manager or PyQgisWorkerManager(
            workflows_root=config.workflows_dir,
            qgis_root=config.qgis_root,
            qgis_python=getattr(config, "qgis_python", "") or "",
        )
        self.summary_callback = summary_callback
        self.bus = _EventBus()
        self._workers: Dict[str, threading.Thread] = {}
        self._workers_lock = threading.RLock()

    # ------------------------------------------------------------------
    # Registration / submission
    # ------------------------------------------------------------------

    def submit(self, workflow: WorkflowRecord, validate: bool = True) -> Tuple[WorkflowRecord, Optional[ValidationResult]]:
        """Persist + start a workflow. Returns (record, validation result)."""
        validation: Optional[ValidationResult] = None
        if validate:
            validation = validate_workflow(workflow.workflow_json)
            if not validation.valid:
                workflow.status = "error"
                # Surface the concrete problems (which step, which param) in
                # the toast-level message, not just in the details payload.
                workflow.error = make_error(
                    "VALIDATION_FAILED",
                    message="workflow validation failed",
                    user_friendly=_compose_issue_message(validation.errors, "工作流校验未通过，请检查输入。"),
                    details={"errors": [e.to_dict() for e in validation.errors]},
                )
                return self._reject_before_run(workflow), validation
            if validation.normalized:
                workflow.workflow_json = validation.normalized
            # Data-aware preflight: catch doomed runs (missing datasets/fields,
            # unusable CRS) BEFORE any background task is started. Filled
            # parameters stay on the record so the teacher can correct and
            # resubmit instead of retyping everything.
            preflight_errors, preflight_warnings = run_preflight(self.config, workflow.workflow_json)
            if preflight_errors:
                details = {
                    "errors": [e.to_dict() for e in preflight_errors],
                    "warnings": [w.to_dict() for w in preflight_warnings],
                }
                workflow.status = "error"
                workflow.error = make_error(
                    "VALIDATION_FAILED",
                    message="workflow preflight failed",
                    user_friendly=_compose_issue_message(
                        preflight_errors, "工作流预检未通过，请检查输入。"
                    ),
                    details=details,
                )
                return self._reject_before_run(workflow), validation
        # Persist & emit creation event
        self.store.create_workflow(workflow)
        self._write_workflow_files(workflow)
        self.bus.publish(workflow.workflow_id, _Event(
            "workflow_created",
            {"workflow": workflow.to_dict()},
        ))

        thread = threading.Thread(
            target=self._run_workflow,
            args=(workflow.workflow_id,),
            name=f"workflow-{workflow.workflow_id}",
            daemon=True,
        )
        with self._workers_lock:
            self._workers[workflow.workflow_id] = thread
        thread.start()
        return workflow, validation

    def _reject_before_run(self, workflow: WorkflowRecord) -> WorkflowRecord:
        """Finish a workflow synchronously as failed, without running steps.

        Records the failure, persists the files and replays created+error
        events so any SSE subscriber sees the same terminal state a real run
        would produce.
        """
        workflow.touch()
        self.store.create_workflow(workflow)
        self._write_workflow_files(workflow)
        self.bus.publish(workflow.workflow_id, _Event(
            "workflow_created",
            {"workflow": workflow.to_dict()},
        ))
        self.bus.publish(workflow.workflow_id, _Event(
            "workflow_error",
            {"workflow_id": workflow.workflow_id, "error": workflow.error},
        ))
        return workflow

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    def stream(self, workflow_id: str, idle_timeout: float = 90.0) -> Iterator[Dict[str, Any]]:
        """Yield event dicts for the given workflow until completion."""
        record = self.store.get_workflow(workflow_id)
        if record is None:
            yield {"type": "workflow_error", "payload": {
                "workflow_id": workflow_id,
                "error": make_error("INTERNAL_ERROR", "workflow not found", "找不到该工作流"),
            }}
            return
        q = self.bus.subscribe(workflow_id)
        try:
            terminal = {"workflow_success", "workflow_error"}
            last_seen = time.time()
            while True:
                try:
                    event = q.get(timeout=2.0)
                except queue.Empty:
                    if time.time() - last_seen > idle_timeout:
                        yield {"type": "stream_idle_timeout", "payload": {"workflow_id": workflow_id}}
                        return
                    # heartbeat for SSE clients
                    yield {"type": "ping", "payload": {"workflow_id": workflow_id, "ts": time.time()}}
                    continue
                if event is None:
                    return
                last_seen = time.time()
                yield event.to_dict()
                if event.type in terminal:
                    return
        finally:
            self.bus.unsubscribe(workflow_id, q)

    # ------------------------------------------------------------------
    # Workflow execution thread
    # ------------------------------------------------------------------

    def _run_workflow(self, workflow_id: str) -> None:
        record = self.store.get_workflow(workflow_id)
        if record is None:
            return
        record.status = "running"
        record.started_at = utc_now()
        record.touch()
        self.store.save_workflow(record)
        self.bus.publish(workflow_id, _Event(
            "workflow_started", {"workflow_id": workflow_id, "status": "running"},
        ))

        steps_def = list(record.workflow_json.get("steps") or [])
        ordered_step_ids = self._topological_order(steps_def)
        steps_state: List[Dict[str, Any]] = []
        for step in steps_def:
            steps_state.append({
                "id": str(step.get("id")),
                "op": str(step.get("op")),
                "status": "pending",
                "outputs": {},
                "error": None,
                "started_at": "",
                "finished_at": "",
            })
        record.steps = steps_state
        self.store.save_workflow(record)

        success = True
        for step_id in ordered_step_ids:
            step = next((s for s in steps_def if str(s.get("id")) == step_id), None)
            if step is None:
                continue
            state = next((s for s in steps_state if s["id"] == step_id), None)
            if state is None:
                continue
            state["status"] = "running"
            state["started_at"] = utc_now()
            self.store.save_workflow(record)
            self.bus.publish(workflow_id, _Event(
                "step_started", {"workflow_id": workflow_id, "step": dict(state)},
            ))

            result = self.worker_manager.run_step(workflow_id, step)
            timings = result.get("timings") if isinstance(result, dict) else None
            if timings:
                logger.info(
                    "step %s/%s timings %s", workflow_id, step_id, timings
                )
            state["finished_at"] = utc_now()
            if result.get("status") == "success":
                state["status"] = "success"
                state["outputs"] = result.get("outputs") or {}
                state["error"] = None
                self._register_artifacts(record, state)
                self.store.save_workflow(record)
                self.bus.publish(workflow_id, _Event(
                    "step_success", {"workflow_id": workflow_id, "step": dict(state)},
                ))
            else:
                error = result.get("error") or make_error(
                    "PROCESSING_FAILED", "unknown step failure", "步骤执行失败", step_id=step_id,
                )
                state["status"] = "error"
                state["error"] = error
                self.store.save_workflow(record)
                self.bus.publish(workflow_id, _Event(
                    "step_error", {"workflow_id": workflow_id, "step": dict(state), "error": error},
                ))
                if (step.get("on_error") or "abort") == "skip":
                    continue
                success = False
                break

        record.finished_at = utc_now()
        if success:
            record.status = "success"
            # Optional: ask the summary callback to write a summary.md
            if self.summary_callback is not None:
                try:
                    summary_text = self.summary_callback(record, self._collect_outputs(record))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("summary_callback failed: %s", exc)
                    summary_text = ""
                if summary_text:
                    summary_path = self.config.workflow_dir(workflow_id) / "outputs" / "summary.md"
                    try:
                        summary_path.write_text(summary_text, encoding="utf-8")
                        self._add_artifact(record, "summary", "AI 解释", "outputs/summary.md")
                    except Exception:
                        logger.exception("failed to write summary.md")
        else:
            first_err = next((s for s in steps_state if s["status"] == "error"), None)
            first_error = (first_err or {}).get("error") or {}
            if str(first_error.get("code") or "") == "STEP_CANCELLED":
                # Distinguish a teacher-initiated cancel from a real failure:
                # the workflow did its job, it was just stopped on purpose.
                record.status = "cancelled"
                cancelled_error = dict(first_error)
                cancelled_error["user_friendly"] = "已取消本次分析，未保存结果图层。可以调整参数后重新提交。"
                record.error = cancelled_error
            else:
                record.status = "error"
                if record.error is None:
                    # bubble up first failed step error
                    if first_err and first_err.get("error"):
                        record.error = first_err["error"]
        record.touch()
        self.store.save_workflow(record)
        self._write_workflow_files(record)

        if success:
            self.bus.publish(workflow_id, _Event(
                "workflow_success",
                {
                    "workflow_id": workflow_id,
                    "workflow": record.to_dict(),
                    "artifacts": list(record.artifacts),
                },
            ))
        else:
            self.bus.publish(workflow_id, _Event(
                "workflow_error",
                {
                    "workflow_id": workflow_id,
                    "error": record.error or {},
                    # Carry the full record so subscribers can tell a
                    # cancelled run apart from a failed one.
                    "workflow": record.to_dict(),
                },
            ))

        # Free the worker-side workspace (paths on disk are kept).
        try:
            self.worker_manager.release_workflow(workflow_id)
        except Exception:  # pragma: no cover
            pass

    # ------------------------------------------------------------------
    # Artifact / output helpers
    # ------------------------------------------------------------------

    def _register_artifacts(self, record: WorkflowRecord, state: Dict[str, Any]) -> None:
        outputs = state.get("outputs") or {}
        for key, kind, default_title in _ARTIFACT_KEYS:
            value = outputs.get(key)
            if not isinstance(value, str) or not value:
                continue
            relative = self._relative_within_workflow(record.workflow_id, value)
            if relative is None:
                continue
            self._add_artifact(record, kind, default_title, relative, step_id=state.get("id"))
        self._sync_artifacts_to_database(record)

    def _sync_artifacts_to_database(self, record: WorkflowRecord) -> None:
        """Mirror teacher-facing workflow artifacts into RuntimeStore outputs.

        The 数据库 panel lists RuntimeStore artifacts only; without this
        bridge, analysis results (结果矢量/地图图片/统计) are invisible there.
        Idempotent: re-running a workflow replaces its previous mirror
        entries (matched by metadata.workflow_id) so the panel never shows
        stale duplicates.
        """
        try:
            existing = [
                item
                for item in self.store.list_outputs(project_id=record.project_id)
                if str((item.get("metadata") or {}).get("workflow_id") or "") == record.workflow_id
            ]
            for item in existing:
                self.store.delete_artifact(item["artifact_id"])
            for artifact in record.artifacts:
                kind = str(artifact.get("kind") or "")
                if kind not in {"geojson", "png", "stats", "summary"}:
                    continue
                relative = str(artifact.get("relative_path") or "")
                absolute = self.config.workflow_dir(record.workflow_id) / relative
                self.store.register_artifact(
                    record.project_id,
                    record.workflow_id,
                    "workflow_output",
                    str(artifact.get("title") or "工作流产物"),
                    str(absolute),
                    metadata={
                        "workflow_id": record.workflow_id,
                        "kind": kind,
                        "public_url": str(artifact.get("public_url") or ""),
                        "relative_path": relative,
                        "template_id": record.template_id,
                        "ai_summary": kind == "summary",
                    },
                )
        except Exception:
            # Mirroring must never fail the workflow itself; the authoritative
            # artifact list stays on WorkflowRecord.
            pass

    def _add_artifact(
        self,
        record: WorkflowRecord,
        kind: str,
        title: str,
        relative_path: str,
        step_id: Optional[str] = None,
    ) -> None:
        try:
            url = self.config.public_url_for_workflow_path(record.workflow_id, relative_path)
        except ValueError:
            return
        artifact = WorkflowArtifact.create(
            workflow_id=record.workflow_id,
            kind=kind,
            title=title,
            relative_path=relative_path,
            public_url=url,
            metadata={"step_id": step_id} if step_id else {},
        )
        record.artifacts.append(artifact.to_dict())
        self.bus.publish(record.workflow_id, _Event(
            "artifact_ready", {"workflow_id": record.workflow_id, "artifact": artifact.to_dict()},
        ))

    def _relative_within_workflow(self, workflow_id: str, absolute_path: str) -> Optional[str]:
        try:
            base = self.config.workflow_dir(workflow_id).resolve()
            candidate = Path(absolute_path).resolve()
            return candidate.relative_to(base).as_posix()
        except Exception:
            return None

    def _collect_outputs(self, record: WorkflowRecord) -> Dict[str, Any]:
        outputs: Dict[str, Any] = {}
        for state in record.steps:
            outputs[state["id"]] = state.get("outputs") or {}
        return outputs

    def _write_workflow_files(self, record: WorkflowRecord) -> None:
        try:
            wf_dir = self.config.workflow_dir(record.workflow_id)
        except Exception:
            return
        try:
            (wf_dir / "workflow.json").write_text(
                json.dumps(record.workflow_json, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (wf_dir / "status.json").write_text(
                json.dumps({
                    "workflow_id": record.workflow_id,
                    "status": record.status,
                    "steps": record.steps,
                    "error": record.error,
                    "started_at": record.started_at,
                    "finished_at": record.finished_at,
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            logger.exception("failed to persist workflow files")

    # ------------------------------------------------------------------
    # Topological sort
    # ------------------------------------------------------------------

    @staticmethod
    def _topological_order(steps: Iterable[Dict[str, Any]]) -> List[str]:
        """Return step ids in dependency order. Cycles fall back to insertion order."""
        steps_list = list(steps)
        order: List[str] = []
        visited: Dict[str, bool] = {}
        by_id = {str(s.get("id")): s for s in steps_list if s.get("id")}

        def visit(step_id: str, stack: List[str]) -> None:
            if visited.get(step_id):
                return
            if step_id in stack:
                return  # cycle; skip
            stack.append(step_id)
            step = by_id.get(step_id)
            if step is not None:
                for dep in step.get("depends_on") or []:
                    if isinstance(dep, str) and dep in by_id:
                        visit(dep, stack)
            stack.pop()
            visited[step_id] = True
            order.append(step_id)

        for step in steps_list:
            sid = str(step.get("id"))
            if sid:
                visit(sid, [])
        return order

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def cancel_workflow(self, workflow_id: str) -> int:
        """Cancel the in-flight worker request(s) of ``workflow_id``.

        The running workflow thread will observe ``STEP_CANCELLED`` for the
        affected step and the workflow fails with that error. Late worker
        results are isolated by request_id and can never leak into a rerun.
        Returns how many in-flight requests were cancelled.
        """
        cancel = getattr(self.worker_manager, "cancel_workflow", None)
        if cancel is None:  # stub managers in tests
            return 0
        try:
            return int(cancel(workflow_id))
        except Exception:  # pragma: no cover
            logger.exception("failed to cancel workflow %s", workflow_id)
            return 0

    def shutdown(self) -> None:
        try:
            self.worker_manager.shutdown(timeout=3.0)
        except Exception:  # pragma: no cover
            pass

    def init_warning(self) -> Optional[Dict[str, Any]]:
        return self.worker_manager.init_warning()
