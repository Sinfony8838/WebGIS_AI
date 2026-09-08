"""Manage the PyQGIS worker subprocess from the FastAPI main process.

Execution model (correctness first):

* ONE worker subprocess hosts ``QgsApplication`` and executes steps strictly
  serially — QGIS objects must stay on the worker thread that owns them, so
  we never fan steps out to a thread pool.
* A single dispatcher thread on the manager side is the ONLY reader of the
  shared worker output queue. Callers never touch it directly; each
  ``run_step`` caller gets a private ``queue.Queue`` reply box and the
  dispatcher routes messages to it by unique ``request_id``. This makes it
  impossible for two concurrent workflows to steal or swallow each other's
  results, even when they use identical ``step_id``s.
* Every message carries ``request_id`` + ``workflow_id`` + ``step_id``.
  Late results (after timeout/cancel), duplicates, and results for unknown
  requests are dropped and counted, never delivered to a newer request.
* Queueing time (waiting behind another step) and execution time (worker
  actually running the step) are bounded separately: the worker acknowledges
  ``step_started`` when it dequeues a request, so a queued timeout and an
  execution timeout produce distinct, accurate error codes.
* A hard worker crash fails only the requests of the current worker
  generation. Requests that are provably safe to re-run (their params do not
  reference in-memory ``${step.key}`` layers that died with the process) are
  automatically retried once on a fresh worker. Recovery only ever touches
  the manager's own child process handle — never other Python/QGIS
  processes on the machine.

The manager never imports ``qgis.core`` itself — only forwards
already-validated step payloads consisting of plain Python types.
"""
from __future__ import annotations

import logging
import multiprocessing as mp
import queue as queue_module
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional


logger = logging.getLogger(__name__)

#: ``${step_id.key}`` references resolve against in-memory worker state that
#: is lost when the worker process dies; steps carrying them are NOT safely
#: auto-retriable after a crash.
_REFERENCE_PATTERN = re.compile(r"\$\{[A-Za-z0-9_]+\.[A-Za-z0-9_]+\}")
_LAYER_ALIAS_PATTERN = re.compile(r"_layer__")


class _PendingRequest:
    """Per-call reply box; the only place a caller waits for messages.

    Message sequence: at most one ``step_started`` ack, then exactly one
    terminal message (``step_result`` / ``step_cancelled``). Further terminal
    messages for the same request are duplicates and rejected.
    """

    __slots__ = (
        "request_id", "workflow_id", "step_id", "generation",
        "reply", "settled", "ack_delivered", "ack_at", "sent_at",
    )

    def __init__(self, request_id: str, workflow_id: str, step_id: str, generation: int) -> None:
        self.request_id = request_id
        self.workflow_id = workflow_id
        self.step_id = step_id
        self.generation = generation
        self.sent_at = time.time()
        self.ack_at: Optional[float] = None
        self.settled = False
        self.ack_delivered = False
        self.reply: "queue_module.Queue[Dict[str, Any]]" = queue_module.Queue()

    def deliver(self, msg: Dict[str, Any]) -> bool:
        """Deliver a message; returns False for out-of-sequence duplicates."""
        mtype = msg.get("type")
        if mtype == "step_started":
            if self.ack_delivered or self.settled:
                return False
            self.ack_delivered = True
            self.ack_at = time.time()
            self.reply.put(msg)
            return True
        # step_result / step_cancelled are terminal
        if self.settled:
            return False
        self.settled = True
        self.reply.put(msg)
        return True

    def deliver_cancelled(self, detail: str) -> bool:
        """Settle the request with a ``step_cancelled`` terminal message."""
        if self.settled:
            return False
        self.settled = True
        self.reply.put({
            "type": "step_cancelled",
            "request_id": self.request_id,
            "workflow_id": self.workflow_id,
            "step_id": self.step_id,
            "message": detail,
        })
        return True


class PyQgisWorkerManager:
    """Lifecycle owner of the PyQGIS worker subprocess."""

    def __init__(
        self,
        workflows_root: Path,
        qgis_root: str = "",
        qgis_python: str = "",
        startup_timeout: float = 60.0,
        step_timeout: float = 600.0,
        queue_timeout: Optional[float] = None,
        worker_target: Optional[Any] = None,
    ) -> None:
        self.workflows_root = Path(workflows_root)
        self.qgis_root = qgis_root or ""
        # Optional override for the worker subprocess Python executable. The
        # FastAPI main process commonly runs under a system Python that does
        # NOT have qgis.core importable; passing the QGIS-bundled interpreter
        # here makes the spawned worker actually able to load QGIS.
        self.qgis_python = (qgis_python or "").strip()
        self.startup_timeout = startup_timeout
        # ``timeout`` passed to run_step bounds EXECUTION (measured from the
        # worker's step_started ack). ``queue_timeout`` bounds waiting in the
        # input queue while another step runs. Defaults keep the previous
        # generous behaviour.
        self.step_timeout = step_timeout
        self.queue_timeout = queue_timeout if queue_timeout is not None else step_timeout
        # Test hook: alternate worker entry point speaking the same protocol.
        self._worker_target = worker_target

        self._lock = threading.RLock()
        self._process: Optional[mp.Process] = None
        self._input_queue: Optional[Any] = None
        self._output_queue: Optional[Any] = None
        self._init_warning: Optional[Dict[str, Any]] = None

        self._generation = 0
        self._restart_needed = False
        self._ready = threading.Event()
        self._pending: Dict[str, _PendingRequest] = {}
        self._dispatcher: Optional[threading.Thread] = None
        self._dispatcher_stop = threading.Event()
        # Control-plane replies (pong, config acks, workflow_released, …).
        self._control_cond = threading.Condition()
        self._control_log: Dict[str, Any] = []
        # Set after an execution timeout: the worker may still be stuck in a
        # step nobody waits for any more. New requests fast-fail instead of
        # silently queueing behind it until the window elapses (or an orphan
        # result proves the worker made progress again).
        self._suspect_until = 0.0
        self.stats: Dict[str, int] = {
            "late_messages_dropped": 0,
            "duplicate_messages_dropped": 0,
            "crashes_recovered": 0,
            "auto_retries": 0,
            "auto_retries_skipped_refs": 0,
        }
        self.last_error: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    # Process lifecycle
    # ------------------------------------------------------------------

    def is_alive(self) -> bool:
        with self._lock:
            return bool(self._process and self._process.is_alive())

    def generation(self) -> int:
        with self._lock:
            return self._generation

    def ensure_started(self) -> None:
        with self._lock:
            # A crashed generation must never serve new requests, even while
            # the dying process is still technically alive.
            if self._restart_needed:
                self._restart_needed = False
                self._cleanup_locked()
            if self._process is not None and self._process.is_alive():
                self._ensure_dispatcher_locked()
                need_wait = not self._ready.is_set()
            else:
                # Stale or dead process? clean up first
                if self._process is not None:
                    self._cleanup_locked()
                self._start_worker_locked()
                need_wait = True
        if need_wait:
            self._wait_ready()

    def _start_worker_locked(self) -> None:
        ctx = mp.get_context("spawn")  # spawn keeps Windows imports clean
        # If a QGIS-bundled Python is available, point the spawned worker
        # at it. Without this, the worker inherits the parent's
        # sys.executable, which on a standard install can't import
        # qgis.core and yields QGIS_ENV_NOT_READY on every step.
        if self.qgis_python:
            qgis_python_path = Path(self.qgis_python)
            if qgis_python_path.exists():
                ctx.set_executable(str(qgis_python_path))
                logger.info("PyQGIS worker will spawn under %s", qgis_python_path)
            else:
                logger.warning(
                    "qgis_python path does not exist, falling back to sys.executable: %s",
                    qgis_python_path,
                )
        self._input_queue = ctx.Queue()
        self._output_queue = ctx.Queue()
        self._generation += 1
        self._ready.clear()
        self._dispatcher_stop.clear()
        # Dispatcher must read the output queue from the first message on.
        self._ensure_dispatcher_locked()
        # Avoid importing worker_main eagerly here; the spawn will import.
        if self._worker_target is not None:
            target = self._worker_target
        else:
            from .worker_main import run_worker as target  # type: ignore[assignment]

        process = ctx.Process(
            target=target,
            args=(self._input_queue, self._output_queue, self.qgis_root, str(self.workflows_root)),
            name="PyQgisWorker",
            daemon=True,
        )
        try:
            process.start()
        except Exception as exc:
            self._cleanup_locked()
            raise RuntimeError(f"failed to spawn PyQGIS worker process: {exc}") from exc
        self._process = process
        self._init_warning = None
        logger.info(
            "PyQGIS worker process spawned pid=%s generation=%s", process.pid, self._generation
        )

    def _wait_ready(self) -> None:
        """Wait for ``worker_ready``; raise on early death, warn on silence."""
        deadline = time.time() + self.startup_timeout
        while time.time() < deadline:
            if self._ready.wait(0.2):
                return
            if not self.is_alive():
                warning = self._init_warning
                message = "worker process exited before signalling readiness"
                if warning:
                    message = str(warning.get("message") or message)
                raise RuntimeError(message)
        logger.warning("PyQGIS worker did not signal readiness in %.1fs", self.startup_timeout)

    def _ensure_dispatcher_locked(self) -> None:
        if self._dispatcher is not None and self._dispatcher.is_alive():
            return
        self._dispatcher_stop.clear()
        self._dispatcher = threading.Thread(
            target=self._dispatch_loop, name="PyQgisWorkerDispatcher", daemon=True
        )
        self._dispatcher.start()

    def init_warning(self) -> Optional[Dict[str, Any]]:
        """Return any init-time error reported by the worker (e.g. missing QGIS)."""
        return dict(self._init_warning) if self._init_warning else None

    def shutdown(self, timeout: float = 5.0) -> None:
        with self._lock:
            process = self._process
            input_queue = self._input_queue
            self._dispatcher_stop.set()
            if process is not None and process.is_alive() and input_queue is not None:
                try:
                    input_queue.put({"type": "shutdown"})
                except Exception:  # pragma: no cover
                    pass
            if process is not None:
                process.join(timeout)
            self._cleanup_locked()
            self._fail_all_pending_locked("WORKER_CRASHED", "worker shut down by manager")

    def _cleanup_locked(self) -> None:
        process = self._process
        self._process = None
        self._input_queue = None
        self._output_queue = None
        self._ready.clear()
        if process is not None and process.is_alive():
            # Only ever terminate our OWN child handle — never any other
            # Python/QGIS process on the machine.
            try:
                process.terminate()
                process.join(2.0)
            except Exception:  # pragma: no cover
                pass

    # ------------------------------------------------------------------
    # Dispatcher: sole reader of the shared output queue
    # ------------------------------------------------------------------

    def _dispatch_loop(self) -> None:
        while not self._dispatcher_stop.is_set():
            output_queue = self._output_queue
            if output_queue is None:
                break
            try:
                msg = output_queue.get(timeout=0.25)
            except queue_module.Empty:
                self._check_worker_death()
                continue
            except Exception:  # queue closed / handle invalidated
                break
            if not isinstance(msg, dict):
                continue
            try:
                self._route(msg)
            except Exception:  # pragma: no cover - routing must never kill the loop
                logger.exception("dispatcher failed to route message: %r", msg)

    def _check_worker_death(self) -> None:
        with self._lock:
            if not self._pending:
                return
            process = self._process
            if process is not None and not process.is_alive():
                pid = process.pid
                self._fail_all_pending_locked(
                    "WORKER_CRASHED",
                    f"PyQGIS worker process (pid={pid}) exited unexpectedly",
                    count_as_crash=True,
                )

    def _route(self, msg: Dict[str, Any]) -> None:
        mtype = msg.get("type")
        if mtype in ("step_result", "step_started", "step_cancelled"):
            request_id = str(msg.get("request_id") or "")
            with self._lock:
                pending = self._pending.get(request_id) if request_id else None
                if pending is None:
                    # Late (timed out / cancelled), duplicate, or orphaned
                    # message: never hand it to a newer request.
                    self.stats["late_messages_dropped"] += 1
                    if mtype == "step_result":
                        # The worker finished *something* after a timeout —
                        # evidence it is not wedged forever.
                        self._suspect_until = 0.0
                    logger.info(
                        "dropped %s for unknown/completed request (request_id=%s workflow=%s step=%s)",
                        mtype, request_id or "<missing>",
                        msg.get("workflow_id"), msg.get("step_id"),
                    )
                    return
                delivered = pending.deliver(msg)
                if mtype == "step_result":
                    self._pending.pop(request_id, None)
                if not delivered:
                    self.stats["duplicate_messages_dropped"] += 1
            return
        if mtype == "worker_ready":
            self._ready.set()
            return
        if mtype == "worker_init_warning":
            self._init_warning = msg.get("error")
            return
        if mtype == "worker_crashed":
            with self._lock:
                self._fail_all_pending_locked(
                    "WORKER_CRASHED", str(msg.get("message") or "worker crashed"),
                    count_as_crash=True,
                )
            return
        # pong / config_applied / workflow_released / unknown → control log
        with self._control_cond:
            self._control_log.append(msg)
            if len(self._control_log) > 200:
                del self._control_log[:-200]
            self._control_cond.notify_all()

    # ------------------------------------------------------------------
    # Control plane (ping health checks, protocol acks)
    # ------------------------------------------------------------------

    def send_control(self, message: Dict[str, Any]) -> bool:
        """Send a control message (ping, config, …) to the worker."""
        self.ensure_started()
        with self._lock:
            input_queue = self._input_queue
        if input_queue is None:
            return False
        try:
            input_queue.put(message)
            return True
        except Exception:
            return False

    def wait_for_control(self, mtype: str, timeout: float = 10.0) -> Optional[Dict[str, Any]]:
        """Wait for (and consume) the next control message of ``mtype``."""
        deadline = time.time() + timeout
        with self._control_cond:
            while True:
                for index, msg in enumerate(self._control_log):
                    if msg.get("type") == mtype:
                        del self._control_log[index]
                        return msg
                remaining = deadline - time.time()
                if remaining <= 0:
                    return None
                self._control_cond.wait(min(remaining, 0.25))

    def _fail_all_pending_locked(
        self, code: str, message: str, count_as_crash: bool = False
    ) -> None:
        if count_as_crash and self._pending:
            self.stats["crashes_recovered"] += 1
            self._restart_needed = True
        pending_requests = list(self._pending.values())
        self._pending.clear()
        self._suspect_until = 0.0
        for pending in pending_requests:
            pending.deliver(
                self._error_response(
                    pending.workflow_id,
                    pending.step_id,
                    code,
                    message,
                    request_id=pending.request_id,
                )
            )

    # ------------------------------------------------------------------
    # Step execution
    # ------------------------------------------------------------------

    def run_step(
        self,
        workflow_id: str,
        step: Dict[str, Any],
        timeout: Optional[float] = None,
        queue_timeout: Optional[float] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> Dict[str, Any]:
        """Send ``step`` to the worker and block until its result returns.

        ``timeout`` bounds execution time counted from the worker's
        ``step_started`` acknowledgement; ``queue_timeout`` bounds time spent
        waiting behind other steps. Returns the worker's
        ``{type: step_result, status, outputs, error}`` dict with an extra
        ``timings`` entry, or a structured error response.
        """
        response, meta = self._dispatch_once(
            workflow_id, step, timeout, queue_timeout, cancel_event
        )
        attempt = 1
        if meta.get("failure") == "crash" and self._auto_retriable(step):
            # Crash recovery: fresh worker generation, fresh request_id, so
            # nothing from the dead generation can leak into the retry.
            self.stats["auto_retries"] += 1
            logger.warning(
                "worker crashed during step %s/%s; retrying once on a fresh worker",
                workflow_id, step.get("id"),
            )
            response, meta = self._dispatch_once(
                workflow_id, step, timeout, queue_timeout, cancel_event
            )
            attempt = 2
        elif meta.get("failure") == "crash":
            self.stats["auto_retries_skipped_refs"] += 1
        timings = meta.get("timings") or {}
        if isinstance(response, dict):
            response.setdefault("timings", timings)
            response["attempt"] = attempt
        return response

    def _dispatch_once(
        self,
        workflow_id: str,
        step: Dict[str, Any],
        exec_timeout: Optional[float],
        queue_timeout: Optional[float],
        cancel_event: Optional[threading.Event],
    ) -> tuple:
        step_id = str(step.get("id") or "")
        meta: Dict[str, Any] = {"failure": None, "timings": {}}
        sent_at = time.time()

        with self._lock:
            if time.time() < self._suspect_until:
                meta["timings"] = {"total_ms": round((time.time() - sent_at) * 1000, 1)}
                return (
                    self._error_response(
                        workflow_id,
                        step_id,
                        "WORKER_STUCK",
                        "worker is suspected stuck on a previously timed-out step; "
                        "request rejected without queueing",
                        request_id="",
                    ),
                    meta,
                )
        # 1) Ensure worker (spawns + waits for readiness on first use).
        try:
            self.ensure_started()
        except Exception as exc:
            self.last_error = {"code": "WORKER_START_FAILED", "message": str(exc)}
            meta["timings"] = {"total_ms": round((time.time() - sent_at) * 1000, 1)}
            return (
                self._error_response(
                    workflow_id, step_id, "WORKER_START_FAILED", str(exc), request_id=""
                ),
                meta,
            )

        # 2) Register pending request under a unique id, then enqueue.
        with self._lock:
            generation = self._generation
            request_id = uuid.uuid4().hex
            pending = _PendingRequest(request_id, workflow_id, step_id, generation)
            self._pending[request_id] = pending
            input_queue = self._input_queue
        try:
            if input_queue is None:
                raise RuntimeError("worker queues unavailable")
            input_queue.put({
                "type": "run_step",
                "request_id": request_id,
                "workflow_id": workflow_id,
                "step": step,
            })
        except Exception as exc:
            self._drop_pending(request_id)
            meta["failure"] = "crash"
            meta["timings"] = {"total_ms": round((time.time() - sent_at) * 1000, 1)}
            return (
                self._error_response(
                    workflow_id, step_id, "WORKER_CRASHED",
                    f"failed to send step to worker: {exc}", request_id=request_id,
                ),
                meta,
            )

        # 3) Phase one: wait for the worker to dequeue and acknowledge.
        q_budget = queue_timeout if queue_timeout is not None else self.queue_timeout
        reply = pending.reply
        queue_deadline = time.time() + q_budget
        msg: Optional[Dict[str, Any]] = None
        while True:
            if self._poll_cancel(cancel_event):
                self._drop_pending(request_id)
                self._send_worker_cancel(request_id, workflow_id)
                meta["timings"] = self._timings(sent_at, None)
                return (
                    self._error_response(
                        workflow_id, step_id, "STEP_CANCELLED",
                        "step cancelled while queued", request_id=request_id,
                    ),
                    meta,
                )
            remaining = queue_deadline - time.time()
            if remaining <= 0:
                self._drop_pending(request_id)
                self._send_worker_cancel(request_id, workflow_id)
                meta["timings"] = self._timings(sent_at, None)
                return (
                    self._error_response(
                        workflow_id, step_id, "STEP_QUEUED_TIMEOUT",
                        f"step still queued behind other work after {q_budget:.1f}s; "
                        "result will be isolated and never reused",
                        request_id=request_id,
                    ),
                    meta,
                )
            try:
                msg = reply.get(timeout=min(remaining, 0.2))
            except queue_module.Empty:
                continue
            break

        if msg.get("type") == "step_started":
            queued_ms = (time.time() - sent_at) * 1000
            meta["timings"]["queued_ms"] = round(queued_ms, 1)
            # 4) Phase two: wait for the actual result.
            e_budget = exec_timeout if exec_timeout is not None else self.step_timeout
            exec_deadline = time.time() + e_budget
            msg = None
            while True:
                if self._poll_cancel(cancel_event):
                    self._drop_pending(request_id)
                    self._send_worker_cancel(request_id, workflow_id)
                    meta["timings"]["exec_ms"] = round((time.time() - pending.ack_at) * 1000, 1)
                    meta["timings"]["total_ms"] = round((time.time() - sent_at) * 1000, 1)
                    return (
                        self._error_response(
                            workflow_id, step_id, "STEP_CANCELLED",
                            "step cancelled during execution; late results are isolated",
                            request_id=request_id,
                        ),
                        meta,
                    )
                remaining = exec_deadline - time.time()
                if remaining <= 0:
                    self._drop_pending(request_id)
                    with self._lock:
                        self._suspect_until = time.time() + self.step_timeout
                    meta["failure"] = "timeout"
                    meta["timings"]["exec_ms"] = round(e_budget * 1000, 1)
                    return (
                        self._error_response(
                            workflow_id, step_id, "STEP_EXEC_TIMEOUT",
                            f"step did not finish within {e_budget:.1f}s of starting; "
                            "the late result will be isolated and never reused",
                            request_id=request_id,
                        ),
                        meta,
                    )
                try:
                    msg = reply.get(timeout=min(remaining, 0.2))
                except queue_module.Empty:
                    continue
                break
            if isinstance(msg, dict) and msg.get("type") == "step_cancelled":
                # Woken by cancel_request()/cancel_workflow() from another
                # thread; the worker keeps running the step but its late
                # result is now orphaned and will be dropped.
                self._send_worker_cancel(request_id, workflow_id)
                meta["timings"]["exec_ms"] = round((time.time() - pending.ack_at) * 1000, 1)
                meta["timings"]["total_ms"] = round((time.time() - sent_at) * 1000, 1)
                return (
                    self._error_response(
                        workflow_id, step_id, "STEP_CANCELLED",
                        str(msg.get("message") or "step cancelled during execution"),
                        request_id=request_id,
                    ),
                    meta,
                )
        elif msg.get("type") == "step_cancelled":
            meta["timings"]["queued_ms"] = round((time.time() - sent_at) * 1000, 1)
            return (
                self._error_response(
                    workflow_id, step_id, "STEP_CANCELLED",
                    "step cancelled before the worker started it", request_id=request_id,
                ),
                meta,
            )

        # 5) Result (or in-flight crash report) arrived.
        exec_ms = None
        if pending.ack_at is not None:
            exec_ms = (time.time() - pending.ack_at) * 1000
            meta["timings"]["exec_ms"] = round(exec_ms, 1)
        meta["timings"]["queued_ms"] = meta["timings"].get("queued_ms") or round(
            ((pending.ack_at or time.time()) - sent_at) * 1000, 1
        )
        meta["timings"]["total_ms"] = round((time.time() - sent_at) * 1000, 1)
        if isinstance(msg, dict) and msg.get("type") == "step_result" and msg.get("status") == "error":
            code = str((msg.get("error") or {}).get("code") or "")
            if code == "WORKER_CRASHED":
                meta["failure"] = "crash"
        result = dict(msg)
        result["request_id"] = request_id
        return result, meta

    # ------------------------------------------------------------------
    # Cancellation
    # ------------------------------------------------------------------

    @staticmethod
    def _poll_cancel(cancel_event: Optional[threading.Event]) -> bool:
        return bool(cancel_event is not None and cancel_event.is_set())

    def _send_worker_cancel(self, request_id: str, workflow_id: str) -> None:
        """Best-effort: ask the worker to skip the request if still queued."""
        with self._lock:
            input_queue = self._input_queue
        if input_queue is None:
            return
        try:
            input_queue.put({
                "type": "cancel_step",
                "request_id": request_id,
                "workflow_id": workflow_id,
            })
        except Exception:  # pragma: no cover - worker may be dead already
            pass

    def cancel_request(self, request_id: str) -> bool:
        """Cancel a specific in-flight request by id.

        The waiting caller (if any) is woken with a ``step_cancelled``
        terminal message immediately; the worker is additionally asked to
        skip the step if it is still queued.
        """
        with self._lock:
            pending = self._pending.pop(request_id, None)
        if pending is None:
            return False
        pending.deliver_cancelled("cancelled via cancel_request")
        self._send_worker_cancel(request_id, pending.workflow_id)
        return True

    def cancel_workflow(self, workflow_id: str) -> int:
        """Cancel every in-flight request belonging to ``workflow_id``."""
        with self._lock:
            request_ids = [
                rid for rid, pending in self._pending.items()
                if pending.workflow_id == workflow_id
            ]
        cancelled = 0
        for rid in request_ids:
            if self.cancel_request(rid):
                cancelled += 1
        return cancelled

    # ------------------------------------------------------------------
    # Workflow resources
    # ------------------------------------------------------------------

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

    def _drop_pending(self, request_id: str) -> None:
        with self._lock:
            self._pending.pop(request_id, None)

    @staticmethod
    def _auto_retriable(step: Dict[str, Any]) -> bool:
        """Crash retries are only safe for steps whose inputs are not
        in-memory ``${step.key}`` references — those die with the worker
        process and would just fail with REFERENCE_NOT_RESOLVED."""
        def _walk(value: Any) -> bool:
            if isinstance(value, str):
                if _REFERENCE_PATTERN.search(value) or _LAYER_ALIAS_PATTERN.search(value):
                    return False
                return True
            if isinstance(value, dict):
                return all(_walk(v) for v in value.values())
            if isinstance(value, (list, tuple)):
                return all(_walk(v) for v in value)
            return True

        return _walk((step or {}).get("params") or {})

    @staticmethod
    def _timings(sent_at: float, exec_ms: Optional[float]) -> Dict[str, Any]:
        timings: Dict[str, Any] = {"queued_ms": round((time.time() - sent_at) * 1000, 1)}
        timings["exec_ms"] = round(exec_ms, 1) if exec_ms is not None else None
        timings["total_ms"] = round((time.time() - sent_at) * 1000, 1)
        return timings

    def _error_response(
        self,
        workflow_id: str,
        step_id: str,
        code: str,
        message: str,
        request_id: str = "",
    ) -> Dict[str, Any]:
        from .errors import make_error

        return {
            "type": "step_result",
            "workflow_id": workflow_id,
            "step_id": step_id,
            "request_id": request_id,
            "status": "error",
            "outputs": {},
            "error": make_error(
                code,
                message=message,
                user_friendly="",
                step_id=step_id,
                details={"request_id": request_id} if request_id else {},
            ),
        }
