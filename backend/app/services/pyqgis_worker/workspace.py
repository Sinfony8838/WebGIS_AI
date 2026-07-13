"""Workspace bookkeeping inside the PyQGIS worker process.

The :class:`Workspace` is created lazily for each ``workflow_id`` the worker
sees. It owns:

* the per-workflow disk directory (``data/workflows/{wf_id}/``);
* a registry of in-memory layers loaded so far (only inside the worker —
  these objects must NEVER be sent back to FastAPI);
* a registry of step outputs so we can resolve ``${step_id.key}`` references
  from later steps;
* counters for unique intermediate file names.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .errors import WorkflowExecutionError


logger = logging.getLogger(__name__)
_REFERENCE_PATTERN = re.compile(r"^\$\{([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)\}$")


class Workspace:
    """Owns the file layout and step bookkeeping for a single workflow."""

    def __init__(self, workflow_id: str, root_dir: Path) -> None:
        if not workflow_id or not re.match(r"^[A-Za-z0-9_-]+$", workflow_id):
            raise ValueError(f"invalid workflow id: {workflow_id!r}")
        self.workflow_id = workflow_id
        self.root_dir = root_dir.resolve()
        self.steps_dir = self.root_dir / "steps"
        self.outputs_dir = self.root_dir / "outputs"
        self.logs_dir = self.root_dir / "logs"
        for path in (self.steps_dir, self.outputs_dir, self.logs_dir):
            path.mkdir(parents=True, exist_ok=True)

        self._lock = threading.RLock()
        self._counter = 0
        self._step_outputs: Dict[str, Dict[str, Any]] = {}
        # Worker-only in-memory layer registry; never serialized.
        self._layers: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Path management
    # ------------------------------------------------------------------

    def alloc_step_dir(self, step_id: str) -> Path:
        """Return (and create) a per-step working directory."""
        safe = re.sub(r"[^A-Za-z0-9_-]+", "_", step_id) or "step"
        path = self.steps_dir / safe
        path.mkdir(parents=True, exist_ok=True)
        return path

    def alloc_intermediate_path(self, step_id: str, suffix: str = ".gpkg") -> Path:
        with self._lock:
            self._counter += 1
            counter = self._counter
        step_dir = self.alloc_step_dir(step_id)
        return step_dir / f"out_{counter:04d}{suffix}"

    def alloc_output_path(self, name: str, suffix: str) -> Path:
        clean_name = re.sub(r"[^A-Za-z0-9_-]+", "_", name) or "output"
        if not suffix.startswith("."):
            suffix = "." + suffix
        return self.outputs_dir / f"{clean_name}{suffix}"

    def relative(self, path: Path) -> str:
        """Return ``path`` relative to the workflow root, using forward slashes."""
        try:
            return path.resolve().relative_to(self.root_dir).as_posix()
        except ValueError:
            return path.resolve().as_posix()

    # ------------------------------------------------------------------
    # Reference / step output bookkeeping
    # ------------------------------------------------------------------

    def register_step_outputs(self, step_id: str, outputs: Dict[str, Any]) -> None:
        with self._lock:
            self._step_outputs[step_id] = dict(outputs or {})

    def resolve_reference(self, value: Any) -> Any:
        """Resolve ``${stepId.key}`` to the actual stored value.

        Plain (non-reference) values pass through unchanged. Lists and dicts
        are walked recursively.
        """
        if isinstance(value, str):
            match = _REFERENCE_PATTERN.match(value.strip())
            if not match:
                return value
            step_id, key = match.group(1), match.group(2)
            with self._lock:
                outputs = self._step_outputs.get(step_id)
            if outputs is None:
                raise WorkflowExecutionError(
                    code="REFERENCE_NOT_RESOLVED",
                    message=f"step {step_id} has no recorded outputs",
                    user_friendly=f"工作流引用了未执行的步骤 {step_id}。",
                    details={"reference": value},
                )
            if key not in outputs:
                raise WorkflowExecutionError(
                    code="REFERENCE_NOT_RESOLVED",
                    message=f"step {step_id} did not produce output '{key}'",
                    user_friendly=f"步骤 {step_id} 没有产出 {key}。",
                    details={"reference": value, "available": sorted(outputs.keys())},
                )
            return outputs[key]
        if isinstance(value, list):
            return [self.resolve_reference(item) for item in value]
        if isinstance(value, dict):
            return {key: self.resolve_reference(val) for key, val in value.items()}
        return value

    # ------------------------------------------------------------------
    # Worker-private layer registry
    # ------------------------------------------------------------------

    def store_layer(self, alias: str, layer: Any) -> str:
        """Store a QgsMapLayer-ish object under a worker-internal alias.

        The alias is opaque to the FastAPI process; it is returned in step
        outputs so later steps can reference the layer via ``${...}`` syntax,
        but external code only sees a string.
        """
        with self._lock:
            self._layers[alias] = layer
        return alias

    def get_layer(self, alias_or_path: Any) -> Any:
        """Return the layer object for an alias, or the path string itself."""
        if not isinstance(alias_or_path, str):
            return alias_or_path
        with self._lock:
            return self._layers.get(alias_or_path, alias_or_path)

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def append_log(self, message: str) -> None:
        log_path = self.logs_dir / "workflow.log"
        try:
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(message.rstrip() + "\n")
        except Exception:  # pragma: no cover - logging best-effort
            logger.exception("failed to append workspace log")

    def write_status(self, status: Dict[str, Any]) -> None:
        path = self.root_dir / "status.json"
        try:
            path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:  # pragma: no cover
            logger.exception("failed to write status.json")

    def cleanup(self) -> None:
        """Drop in-memory layers; on-disk artifacts are retained."""
        with self._lock:
            self._layers.clear()
            self._step_outputs.clear()
