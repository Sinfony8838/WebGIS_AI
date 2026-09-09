"""A protocol-faithful fake PyQGIS worker for reliability tests.

Speaks exactly the same queue protocol as
``backend.app.services.pyqgis_worker.worker_main`` (request_id echo,
``step_started`` acks, ``cancel_step`` handling, ``release_workflow``
temp-dir purge), so :class:`PyQgisWorkerManager` cannot tell the difference
except that no QGIS is loaded.

Fault injection works through a ``{"type": "config", "rules": {...}}``
control message sent before the steps under test:

* ``default_delay`` / ``delay_by_op`` — artificial execution time;
* ``crash_ops`` — ``{"op": "hard"|"soft"}``; hard = ``os._exit(1)`` without
  any message (simulates a native crash), soft = ``worker_crashed`` message
  then exit;
* ``duplicate_result`` — emit every ``step_result`` twice;
* ``orphan_after_op`` — after the named op, emit one result with a forged
  unknown ``request_id`` (simulates a late result of a timed-out request);
* ``ignore_shutdown`` — keep running after ``shutdown`` so the manager's
  terminate path is exercised;
* ``marker`` (default on) — write
  ``{workflows_root}/{workflow_id}/steps/{step_id}/marker.txt`` containing
  ``"{workflow_id}|{step_id}|{request_id}"`` and return it as the ``path``
  output, so crossed-results / crossed-directories become detectable.

Must stay a module-level function: ``multiprocessing`` spawn pickles the
target by qualified name.
"""
from __future__ import annotations

import os
import queue as queue_module
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, Optional


def run_fake_worker(
    input_queue: Any,
    output_queue: Any,
    qgis_root: str,
    workflows_root: str,
    cancel_queue: Optional[Any] = None,
) -> None:  # noqa: C901
    workflows_dir = Path(workflows_root)
    workflows_dir.mkdir(parents=True, exist_ok=True)

    output_queue.put({"type": "worker_ready", "timestamp": time.time()})

    rules: Dict[str, Any] = {}
    cancelled: "OrderedDict[str, None]" = OrderedDict()

    def drain_cancellations() -> None:
        if cancel_queue is None:
            return
        while True:
            try:
                cancel = cancel_queue.get_nowait()
            except queue_module.Empty:
                break
            except (EOFError, OSError):
                break
            if isinstance(cancel, dict) and cancel.get("type") == "cancel_step":
                request_id = str(cancel.get("request_id") or "")
                if request_id:
                    cancelled[request_id] = None
                    cancelled.move_to_end(request_id)
                    if len(cancelled) > 4096:
                        cancelled.popitem(last=False)

    def emit(msg: Dict[str, Any]) -> None:
        output_queue.put(msg)
        if rules.get("duplicate_result") and msg.get("type") == "step_result":
            output_queue.put(dict(msg))

    while True:
        drain_cancellations()
        message = input_queue.get()
        drain_cancellations()
        if not isinstance(message, dict):
            continue
        msg_type = message.get("type")

        if msg_type == "config":
            rules = dict(message.get("rules") or {})
            output_queue.put({"type": "config_applied"})
            continue

        if msg_type == "ping":
            output_queue.put({"type": "pong"})
            continue

        if msg_type == "shutdown":
            if rules.get("ignore_shutdown"):
                continue
            break

        if msg_type == "cancel_step":
            request_id = str(message.get("request_id") or "")
            if request_id:
                cancelled[request_id] = None
            continue

        if msg_type == "release_workflow":
            workflow_id = str(message.get("workflow_id") or "")
            steps_dir = workflows_dir / workflow_id / "steps"
            if steps_dir.exists():
                import shutil

                shutil.rmtree(steps_dir, ignore_errors=True)
            output_queue.put({
                "type": "workflow_released", "workflow_id": workflow_id,
            })
            continue

        if msg_type != "run_step":
            continue

        request_id = str(message.get("request_id") or "")
        workflow_id = str(message.get("workflow_id") or "")
        step = message.get("step") or {}
        step_id = str(step.get("id") or "")
        op = str(step.get("op") or "")

        if request_id and request_id in cancelled:
            cancelled.pop(request_id, None)
            output_queue.put({
                "type": "step_cancelled",
                "request_id": request_id,
                "workflow_id": workflow_id,
                "step_id": step_id,
            })
            continue

        output_queue.put({
            "type": "step_started",
            "request_id": request_id,
            "workflow_id": workflow_id,
            "step_id": step_id,
            "timestamp": time.time(),
        })

        crash = rules.get("crash_ops") or {}
        if op in crash:
            if crash[op] == "soft":
                output_queue.put({
                    "type": "worker_crashed",
                    "code": "WORKER_CRASHED",
                    "message": f"soft crash on op {op}",
                    "user_friendly": "fake soft crash",
                })
                time.sleep(0.05)
                os._exit(1)
            os._exit(1)  # hard crash: no message at all

        delay = float(rules.get("default_delay") or 0.0)
        delay_by_op = rules.get("delay_by_op") or {}
        delay += float(delay_by_op.get(op) or 0.0)
        if delay > 0:
            time.sleep(delay)

        marker_dir = workflows_dir / workflow_id / "steps" / step_id
        marker_dir.mkdir(parents=True, exist_ok=True)
        marker_file = marker_dir / "marker.txt"
        marker_file.write_text(f"{workflow_id}|{step_id}|{request_id}", encoding="utf-8")

        outputs = {
            "path": str(marker_file),
            "marker": workflow_id,
            "content": f"{workflow_id}|{step_id}|{request_id}",
            "step_id": step_id,
            "feature_count": 1,
        }
        params = step.get("params") or {}
        if isinstance(params.get("outputs_extra"), dict):
            outputs.update(params["outputs_extra"])

        emit({
            "type": "step_result",
            "request_id": request_id,
            "workflow_id": workflow_id,
            "step_id": step_id,
            "status": "success",
            "outputs": outputs,
            "error": None,
        })

        orphan_op = rules.get("orphan_after_op")
        if orphan_op == op:
            output_queue.put({
                "type": "step_result",
                "request_id": "forged-unknown-request-id",
                "workflow_id": "forged-workflow",
                "step_id": "forged_step",
                "status": "success",
                "outputs": {"marker": "forged"},
                "error": None,
            })
