"""Entry point of the PyQGIS worker subprocess.

The worker reads control / step messages from ``input_queue``, executes
them, and pushes structured results back through ``output_queue``. Both
queues are :class:`multiprocessing.Queue` instances created by
:class:`PyQgisWorkerManager`.

All QGIS imports happen inside this module / its handlers, never in the
FastAPI main process.
"""
from __future__ import annotations

import logging
import os
import time
import traceback
from pathlib import Path
from typing import Any, Dict


def _make_logger() -> logging.Logger:
    logger = logging.getLogger("pyqgis_worker")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("[pyqgis-worker %(levelname)s] %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger


def _safe_put(queue: Any, message: Dict[str, Any]) -> None:
    try:
        queue.put(message)
    except Exception:  # pragma: no cover - queue closed
        pass


def _emit_ready(output_queue: Any) -> None:
    _safe_put(output_queue, {"type": "worker_ready", "timestamp": time.time()})


def _emit_error(output_queue: Any, code: str, message: str, user_friendly: str = "", **details: Any) -> None:
    payload = {
        "type": "worker_error",
        "code": code,
        "message": message,
        "user_friendly": user_friendly or message,
        "details": details,
        "timestamp": time.time(),
    }
    _safe_put(output_queue, payload)


def worker_loop(input_queue: Any, output_queue: Any, qgis_root: str, workflows_root: str) -> None:
    """Main loop. Runs forever until receiving ``{"type": "shutdown"}``."""
    logger = _make_logger()
    logger.info("Worker starting (pid=%s)", os.getpid())

    workflows_dir = Path(workflows_root)
    workflows_dir.mkdir(parents=True, exist_ok=True)

    # 1. Try to start QGIS. If it fails, keep the loop running and reject
    #    every step with QGIS_ENV_NOT_READY so the FastAPI main process can
    #    surface a clean error.
    qgis_app = None
    qgis_init_error: Dict[str, Any] = {}
    try:
        from .bootstrap import start_qgis
        from .errors import WorkflowExecutionError

        try:
            qgis_app = start_qgis(qgis_root or None)
            logger.info("QGIS application initialized")
        except WorkflowExecutionError as exc:
            qgis_init_error = exc.to_dict()
            logger.warning("QGIS init failed: %s", exc.message)
    except Exception as exc:  # very early failure (import error before QGIS)
        qgis_init_error = {
            "code": "QGIS_ENV_NOT_READY",
            "message": str(exc),
            "user_friendly": "PyQGIS Worker 启动失败，请检查 QGIS_ROOT 配置。",
            "step_id": "",
            "details": {"reason": traceback.format_exc(limit=2)},
        }
        logger.error("worker bootstrap raised unexpectedly: %s", exc)

    # Lazily import workspace once Python path / env is configured
    from .workspace import Workspace
    from .errors import WorkflowExecutionError, make_error
    from .task_router import dispatch

    workspaces: Dict[str, Workspace] = {}

    _emit_ready(output_queue)
    if qgis_init_error:
        _safe_put(output_queue, {
            "type": "worker_init_warning",
            "error": qgis_init_error,
        })

    while True:
        try:
            message = input_queue.get()
        except (EOFError, KeyboardInterrupt):
            break

        if not isinstance(message, dict):
            continue
        msg_type = message.get("type")
        if msg_type == "shutdown":
            break

        if msg_type == "ping":
            _safe_put(output_queue, {"type": "pong", "timestamp": time.time()})
            continue

        if msg_type == "run_step":
            workflow_id = str(message.get("workflow_id") or "")
            step = message.get("step") or {}
            step_id = str(step.get("id") or "")
            op = str(step.get("op") or "")
            params = step.get("params") or {}

            if qgis_init_error:
                _safe_put(output_queue, {
                    "type": "step_result",
                    "workflow_id": workflow_id,
                    "step_id": step_id,
                    "status": "error",
                    "error": {**qgis_init_error, "step_id": step_id},
                    "outputs": {},
                })
                continue

            workspace = workspaces.get(workflow_id)
            if workspace is None:
                try:
                    workspace = Workspace(workflow_id, workflows_dir / workflow_id)
                    workspaces[workflow_id] = workspace
                except Exception as exc:
                    _safe_put(output_queue, {
                        "type": "step_result",
                        "workflow_id": workflow_id,
                        "step_id": step_id,
                        "status": "error",
                        "error": make_error(
                            "INTERNAL_ERROR",
                            message=str(exc),
                            user_friendly="无法创建工作流工作目录。",
                            step_id=step_id,
                        ),
                        "outputs": {},
                    })
                    continue

            workspace.append_log(f"[step_start] id={step_id} op={op}")
            try:
                outputs = dispatch(op, params, workspace) or {}
                workspace.register_step_outputs(step_id, outputs)
                workspace.append_log(
                    f"[step_success] id={step_id} op={op} keys={sorted(outputs.keys())}"
                )
                _safe_put(output_queue, {
                    "type": "step_result",
                    "workflow_id": workflow_id,
                    "step_id": step_id,
                    "status": "success",
                    "outputs": outputs,
                    "error": None,
                })
            except WorkflowExecutionError as exc:
                payload = exc.to_dict()
                payload.setdefault("step_id", step_id)
                workspace.append_log(
                    f"[step_error] id={step_id} op={op} code={payload.get('code')} msg={payload.get('message')}"
                )
                _safe_put(output_queue, {
                    "type": "step_result",
                    "workflow_id": workflow_id,
                    "step_id": step_id,
                    "status": "error",
                    "outputs": {},
                    "error": payload,
                })
            except Exception as exc:  # noqa: BLE001
                tb = traceback.format_exc(limit=4)
                workspace.append_log(
                    f"[step_crash] id={step_id} op={op} exc={exc}\n{tb}"
                )
                _safe_put(output_queue, {
                    "type": "step_result",
                    "workflow_id": workflow_id,
                    "step_id": step_id,
                    "status": "error",
                    "outputs": {},
                    "error": make_error(
                        "PROCESSING_FAILED",
                        message=str(exc),
                        user_friendly=f"步骤 {step_id} 执行失败：{exc}",
                        step_id=step_id,
                        details={"traceback": tb},
                    ),
                })
            continue

        if msg_type == "release_workflow":
            workflow_id = str(message.get("workflow_id") or "")
            ws = workspaces.pop(workflow_id, None)
            if ws is not None:
                ws.cleanup()
            _safe_put(output_queue, {"type": "workflow_released", "workflow_id": workflow_id})
            continue

    # Shutdown
    try:
        if qgis_app is not None:
            qgis_app.exitQgis()
    except Exception:  # pragma: no cover
        pass
    logger.info("Worker exiting (pid=%s)", os.getpid())


def run_worker(input_queue: Any, output_queue: Any, qgis_root: str, workflows_root: str) -> None:
    """multiprocessing target. Catches all exceptions to avoid silent crashes."""
    try:
        worker_loop(input_queue, output_queue, qgis_root, workflows_root)
    except Exception as exc:  # noqa: BLE001
        try:
            output_queue.put({
                "type": "worker_crashed",
                "code": "WORKER_CRASHED",
                "message": str(exc),
                "user_friendly": "PyQGIS Worker 进程异常退出。",
                "details": {"traceback": traceback.format_exc(limit=4)},
            })
        except Exception:
            pass
        raise
