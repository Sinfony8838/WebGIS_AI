"""Isolation helpers for the phase-1 audit test files (audit task T1).

Import this module *before* constructing any ``AppConfig`` for tests: it
scrubs inherited production data-root overrides from the process environment
so a stray ``WEBGIS_AI_DATA_DIR`` / ``WEBGIS_AI_AUTH_DB`` can never redirect
the app under test at a real deployment data tree.

Every helper reports labels and booleans only — never resolved absolute
paths — so test output stays safe to paste into audit evidence.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

#: Environment variables that can redirect identity/data storage at startup.
DATA_ROOT_ENV_VARS = ("WEBGIS_AI_DATA_DIR", "WEBGIS_AI_AUTH_DB")

#: Derived AppConfig attributes that must all live inside the sandbox.
_SANDBOX_LABELS = (
    "data_dir",
    "state_dir",
    "auth_dir",
    "auth_db_path",
    "uploads_dir",
    "outputs_dir",
    "workflows_dir",
    "state_file",
    "builtin_dir",
    "knowledge_dir",
)


def scrub_data_root_env() -> list[str]:
    """Remove inherited data-root overrides from ``os.environ``.

    Returns the *names* that were removed (values are never reported).
    """
    removed: list[str] = []
    for name in DATA_ROOT_ENV_VARS:
        value = os.environ.pop(name, None)
        if value is not None and value.strip():
            removed.append(name)
    return removed


def build_isolated_config(tmp_path: Path):
    """Build an ``AppConfig`` whose every data target lives inside ``tmp_path``.

    Mirrors the dominant existing test pattern (override the derived path
    attributes after construction) but also pins ``builtin_dir`` so the whole
    configuration — including source-controlled builtin content — stays inside
    the sandbox.
    """
    from backend.app.config import AppConfig

    config = AppConfig(root_dir=tmp_path)
    sandbox_data = tmp_path / "backend" / "data"
    config.data_dir = sandbox_data
    config.state_dir = sandbox_data / "state"
    config.auth_dir = sandbox_data / "auth"
    config.auth_db_path = config.auth_dir / "auth.db"
    config.uploads_dir = sandbox_data / "uploads"
    config.outputs_dir = sandbox_data / "outputs"
    config.workflows_dir = sandbox_data / "workflows"
    config.state_file = config.state_dir / "runtime.json"
    config.ensure_dirs()
    return config


def sandbox_escape_labels(config, sandbox_root: Path) -> list[str]:
    """Return labels of data targets that resolve outside ``sandbox_root``.

    Uses ``Path.resolve`` so symlink/junction escapes are caught even when the
    lexical path is inside. An empty list means every target is contained.
    """
    resolved_root = Path(sandbox_root).resolve()
    escapes: list[str] = []
    for label in _SANDBOX_LABELS:
        target = getattr(config, label, None)
        if target is None:
            escapes.append(label + ":missing")
            continue
        try:
            Path(target).resolve().relative_to(resolved_root)
        except ValueError:
            escapes.append(label)
    return escapes


def probe_worker_workspace_root(env_overrides: dict[str, str], repo_root: Path) -> str:
    """Run ``workspace_root()`` in a fresh subprocess and classify the result.

    Returns one of the labels ``"sandbox"``, ``"relative-fallback"``,
    ``"unexpected"`` — the resolved path itself is never returned.
    """
    code = (
        "import sys;"
        f"sys.path.insert(0, r'{repo_root}');"
        "from backend.app.services.pyqgis_worker.handlers._common import workspace_root;"
        "print(workspace_root())"
    )
    env = {k: v for k, v in os.environ.items() if k not in DATA_ROOT_ENV_VARS}
    env.update(env_overrides)
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        cwd=str(repo_root),
        check=True,
    )
    resolved = Path(result.stdout.strip().strip('"')).resolve()
    for key, value in env_overrides.items():
        if key == "WEBGIS_AI_DATA_DIR" and value:
            return "sandbox" if resolved == Path(value).resolve() else "unexpected"
    return "relative-fallback" if not resolved.is_absolute() else "unexpected"


# Import-time hygiene: a phase-1 test module that imports this helper before
# touching ``backend.app`` can rely on a clean data-root environment.
scrub_data_root_env()
