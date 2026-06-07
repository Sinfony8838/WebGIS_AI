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
from .workflow_validator import ValidationResult, validate_workflow


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
                workflow.error = make_error(
                    "VALIDATION_FAILED",
                    message="workflow validation failed",
                    user_friendly="工作流校验未通过，请检查输入。",
                    details={"errors": [e.to_dict() for e in validation.errors]},
                )
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
                return workflow, validation
            if validation.normalized:
                workflow.workflow_json = validation.normalized
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
            record.status = "error"
            if record.error is None:
                # bubble up first failed step error
                first_err = next((s for s in steps_state if s["status"] == "error"), None)
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
                {"workflow_id": workflow_id, "error": record.error or {}},
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

    def shutdown(self) -> None:
        try:
            self.worker_manager.shutdown(timeout=3.0)
        except Exception:  # pragma: no cover
            pass

    def init_warning(self) -> Optional[Dict[str, Any]]:
        return self.worker_manager.init_warning()
