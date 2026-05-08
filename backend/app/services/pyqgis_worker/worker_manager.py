"""Manage the PyQGIS worker subprocess from the FastAPI main process.

The manager:

* spawns a daemon ``multiprocessing.Process`` running :func:`worker_main.run_worker`;
* exposes ``run_step`` / ``shutdown`` / ``release_workflow`` helpers that
  communicate over two ``multiprocessing.Queue`` instances;
* never imports ``qgis.core`` itself — only forwards already-validated step
  payloads consisting of plain Python types.

If the worker has not been started yet the first ``run_step`` call lazily
launches it.
"""
from __future__ import annotations

import logging
import multiprocessing as mp
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional


logger = logging.getLogger(__name__)


class PyQgisWorkerManager:
    """Lifecycle owner of the PyQGIS worker subprocess."""

    def __init__(
        self,
        workflows_root: Path,
        qgis_root: str = "",
        startup_timeout: float = 60.0,
        step_timeout: float = 600.0,
    ) -> None:
        self.workflows_root = Path(workflows_root)
        self.qgis_root = qgis_root or ""
        self.startup_timeout = startup_timeout
        self.step_timeout = step_timeout
        self._lock = threading.RLock()
        self._process: Optional[mp.Process] = None
        self._input_queue: Optional[mp.Queue] = None
        self._output_queue: Optional[mp.Queue] = None
        self._init_warning: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    # Process lifecycle
    # ------------------------------------------------------------------

    def is_alive(self) -> bool:
        with self._lock:
            return bool(self._process and self._process.is_alive())

    def ensure_started(self) -> None:
        with self._lock:
            if self._process is not None and self._process.is_alive():
                return
            # Stale process? clean up first
            if self._process is not None:
                self._cleanup_locked()

            ctx = mp.get_context("spawn")  # spawn keeps Windows imports clean
            self._input_queue = ctx.Queue()
            self._output_queue = ctx.Queue()
            # Avoid importing worker_main eagerly here; the spawn will import.
            from .worker_main import run_worker

            process = ctx.Process(
                target=run_worker,
                args=(self._input_queue, self._output_queue, self.qgis_root, str(self.workflows_root)),
                name="PyQgisWorker",
                daemon=True,
            )
            process.start()
            self._process = process
            logger.info("PyQGIS worker process spawned pid=%s", process.pid)
            self._init_warning = None
            self._await_ready()

    def _await_ready(self) -> None:
        """Drain initial messages until ``worker_ready`` arrives."""
        deadline = time.time() + self.startup_timeout
        assert self._output_queue is not None
        while time.time() < deadline:
            remaining = max(0.1, deadline - time.time())
            try:
                msg = self._output_queue.get(timeout=remaining)
            except Exception:
                break
            if not isinstance(msg, dict):
                continue
            mtype = msg.get("type")
            if mtype == "worker_ready":
                return
            if mtype == "worker_init_warning":
                self._init_warning = msg.get("error")
                # init warning means QGIS env is broken; worker still running and will
                # reject every step with QGIS_ENV_NOT_READY. Keep going so callers get
                # a structured error rather than a hang.
                continue
            if mtype == "worker_crashed":
                raise RuntimeError(msg.get("message") or "worker crashed before ready")
        # Timed out
        logger.warning("PyQGIS worker did not signal readiness in %.1fs", self.startup_timeout)

    def init_warning(self) -> Optional[Dict[str, Any]]:
        """Return any init-time error reported by the worker (e.g. missing QGIS)."""
        return dict(self._init_warning) if self._init_warning else None

    def shutdown(self, timeout: float = 5.0) -> None:
        with self._lock:
            if self._process is None:
                return
            try:
                if self._input_queue is not None:
                    self._input_queue.put({"type": "shutdown"})
            except Exception:  # pragma: no cover
                pass
            self._process.join(timeout)
            self._cleanup_locked()

    def _cleanup_locked(self) -> None:
        process = self._process
        self._process = None
        self._input_queue = None
        self._output_queue = None
        if process is not None and process.is_alive():
            try:
                process.terminate()
                process.join(2.0)
            except Exception:  # pragma: no cover
                pass

    # ------------------------------------------------------------------
    # Step execution
    # ------------------------------------------------------------------

    def run_step(
        self,
        workflow_id: str,
        step: Dict[str, Any],
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Send ``step`` to the worker and block until a result returns.

        Returns the dict the worker emits (``{type: step_result, status, outputs, error}``).
        """
        self.ensure_started()
        with self._lock:
            input_queue = self._input_queue
            output_queue = self._output_queue
        if input_queue is None or output_queue is None:
            return self._build_crash_response(
                workflow_id, step.get("id", ""), "worker queues unavailable"
            )

        message = {"type": "run_step", "workflow_id": workflow_id, "step": step}
        try:
            input_queue.put(message)
        except Exception as exc:
            return self._build_crash_response(workflow_id, step.get("id", ""), str(exc))

        deadline = time.time() + (timeout if timeout is not None else self.step_timeout)
        while time.time() < deadline:
            remaining = max(0.5, deadline - time.time())
            try:
                msg = output_queue.get(timeout=remaining)
            except Exception:
                break
            if not isinstance(msg, dict):
                continue
            mtype = msg.get("type")
            if mtype == "step_result" and msg.get("step_id") == step.get("id"):
                return msg
            if mtype == "worker_crashed":
                self._cleanup_locked()
                return self._build_crash_response(
                    workflow_id, step.get("id", ""), msg.get("message") or "worker crashed"
                )
            # ignore other messages (pong, etc.)
        return self._build_crash_response(
            workflow_id,
            step.get("id", ""),
            f"worker did not respond within {self.step_timeout}s",
        )

    def release_workflow(self, workflow_id: str) -> None:
        with self._lock:
            input_queue = self._input_queue
        if input_queue is None:
            return
        try:
            input_queue.put({"type": "release_workflow", "workflow_id": workflow_id})
        except Exception:  # pragma: no cover
            pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_crash_response(self, workflow_id: str, step_id: str, message: str) -> Dict[str, Any]:
        return {
            "type": "step_result",
            "workflow_id": workflow_id,
            "step_id": step_id,
            "status": "error",
            "outputs": {},
            "error": {
                "code": "WORKER_CRASHED",
                "message": message,
                "user_friendly": "PyQGIS Worker 进程异常退出，请重新提交任务。",
                "step_id": step_id,
                "details": {},
            },
        }
