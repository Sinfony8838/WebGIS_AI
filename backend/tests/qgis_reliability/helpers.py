"""Shared helpers for the qgis_reliability tests."""
from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Any, Dict

from backend.app.services.pyqgis_worker import PyQgisWorkerManager

from .fake_worker import run_fake_worker


def make_tmp_dir(prefix: str = "qgis_reliability_") -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))


def make_manager(
    workflows_root: Path,
    *,
    step_timeout: float = 20.0,
    queue_timeout: float = 20.0,
    startup_timeout: float = 20.0,
    **kwargs: Any,
) -> PyQgisWorkerManager:
    """Manager wired to the fake worker with test-friendly timeouts."""
    return PyQgisWorkerManager(
        workflows_root=workflows_root,
        qgis_root="",
        qgis_python="",
        startup_timeout=startup_timeout,
        step_timeout=step_timeout,
        queue_timeout=queue_timeout,
        worker_target=run_fake_worker,
        **kwargs,
    )


def configure(manager: PyQgisWorkerManager, rules: Dict[str, Any]) -> None:
    """Push fault-injection rules into the fake worker and wait for ack."""
    if not manager.send_control({"type": "config", "rules": rules}):
        raise RuntimeError("failed to send config to fake worker")
    ack = manager.wait_for_control("config_applied", timeout=15)
    if ack is None:
        raise RuntimeError("fake worker did not acknowledge config")


def step(step_id: str, op: str = "probe", **params: Any) -> Dict[str, Any]:
    return {"id": step_id, "op": op, "params": params}


def assert_success(result: Dict[str, Any], workflow_id: str, step_id: str) -> None:
    assert result.get("type") == "step_result", result
    assert result.get("status") == "success", result
    assert result.get("workflow_id") == workflow_id, result
    assert result.get("step_id") == step_id, result
