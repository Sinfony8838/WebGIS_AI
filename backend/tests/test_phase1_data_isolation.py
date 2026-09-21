"""Phase-1 audit task T1: unified data-root resolution and sandbox isolation.

Covers:
* the single ``resolve_data_root`` used by the main process (env override +
  legacy default);
* the worker-side ``workspace_root`` fallback (must land on
  ``<repo>/backend/data``, not ``backend/app/data``);
* builtin-root decoupling from a relocated data root;
* the test-launcher boundary check (inherited production overrides are
  scrubbed; every derived data target stays inside the sandbox).

No real worker is started and no file outside the pytest sandbox is opened.
Output only ever contains labels — never resolved local paths.
"""
from __future__ import annotations

import os
from pathlib import Path

from backend.tests.phase1_sandbox import (
    build_isolated_config,
    probe_worker_workspace_root,
    sandbox_escape_labels,
    scrub_data_root_env,
)

import backend.app.services.pyqgis_worker.handlers._common as worker_common
from backend.app.config import AppConfig, resolve_data_root

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_resolve_data_root_default_matches_legacy_layout(monkeypatch) -> None:
    scrub_data_root_env()
    config = AppConfig(root_dir=Path("/opt/webgis"))
    assert config.data_dir == Path("/opt/webgis") / "backend" / "data"
    assert config.state_dir == config.data_dir / "state"
    assert config.auth_dir == config.data_dir / "auth"
    assert config.uploads_dir == config.data_dir / "uploads"
    assert config.outputs_dir == config.data_dir / "outputs"
    assert config.workflows_dir == config.data_dir / "workflows"
    assert config.state_file == config.state_dir / "runtime.json"


def test_resolve_data_root_honors_env_override(monkeypatch, tmp_path) -> None:
    relocated = tmp_path / "relocated-instance"
    relocated.mkdir()
    monkeypatch.setenv("WEBGIS_AI_DATA_DIR", str(relocated))
    config = AppConfig(root_dir=tmp_path)
    assert config.data_dir == relocated
    assert config.state_dir == relocated / "state"
    assert config.auth_dir == relocated / "auth"
    assert config.auth_db_path == relocated / "auth" / "auth.db"
    assert config.uploads_dir == relocated / "uploads"
    assert config.workflows_dir == relocated / "workflows"
    assert config.state_file == relocated / "state" / "runtime.json"
    assert sandbox_escape_labels(config, tmp_path) == []


def test_explicit_auth_db_override_follows_env(monkeypatch, tmp_path) -> None:
    alt_db = tmp_path / "alt-auth" / "auth.db"
    monkeypatch.setenv("WEBGIS_AI_AUTH_DB", str(alt_db))
    config = AppConfig(root_dir=tmp_path)
    assert config.auth_db_path == alt_db
    # The launcher-scrub removes the override so sandboxed configs are safe.
    removed = scrub_data_root_env()
    assert "WEBGIS_AI_AUTH_DB" in removed


def test_worker_workspace_root_fallback_targets_backend_data(monkeypatch, tmp_path) -> None:
    """Regression: the old walk-up stopped at the first ancestor containing
    ``data`` and therefore landed on ``backend/app/data`` (builtin assets)."""
    fake_repo = tmp_path / "fake-repo"
    (fake_repo / "backend" / "app" / "data").mkdir(parents=True)  # builtin layout only
    (fake_repo / "backend" / "data").mkdir(parents=True)
    fake_module = fake_repo / "backend" / "app" / "services" / "pyqgis_worker" / "handlers" / "_common.py"
    fake_module.parent.mkdir(parents=True)
    fake_module.write_text("", encoding="utf-8")
    monkeypatch.delenv("WEBGIS_AI_DATA_DIR", raising=False)
    monkeypatch.setattr(worker_common, "__file__", str(fake_module))
    resolved = worker_common.workspace_root()
    assert resolved == fake_repo / "backend" / "data"


def test_worker_builtin_root_is_independent_of_data_root(monkeypatch, tmp_path) -> None:
    relocated = tmp_path / "relocated"
    relocated.mkdir()
    monkeypatch.setenv("WEBGIS_AI_DATA_DIR", str(relocated))
    # Module really lives in this worktree/repo: builtin stays under backend/app/data.
    expected_tail = Path("backend") / "app" / "data" / "builtin"
    assert worker_common.builtin_root().as_posix().endswith(expected_tail.as_posix())


def test_worker_workspace_root_probe_sandbox_env(tmp_path) -> None:
    sandbox = tmp_path / "worker-sandbox"
    sandbox.mkdir()
    label = probe_worker_workspace_root({"WEBGIS_AI_DATA_DIR": str(sandbox)}, REPO_ROOT)
    assert label == "sandbox", label


def test_worker_workspace_root_probe_without_env(tmp_path) -> None:
    """Without env, the fresh subprocess must NOT land inside ``backend/app``
    (the historical bug); any repo-layout hit must be ``backend/data``."""
    label = probe_worker_workspace_root({}, REPO_ROOT)
    assert label in {"relative-fallback", "unexpected"}, label


def test_phase1_launcher_builds_fully_contained_config(tmp_path) -> None:
    config = build_isolated_config(tmp_path)
    assert config.state_file.exists() or config.state_file.parent.exists()
    assert sandbox_escape_labels(config, tmp_path) == []
    assert config.auth_db_path == config.auth_dir / "auth.db"


def test_launcher_scrub_covers_both_override_vars() -> None:
    os.environ["WEBGIS_AI_DATA_DIR"] = "sentinel-data"
    os.environ["WEBGIS_AI_AUTH_DB"] = "sentinel-auth"
    try:
        removed = scrub_data_root_env()
        assert "WEBGIS_AI_DATA_DIR" in removed
        assert "WEBGIS_AI_AUTH_DB" in removed
        assert "WEBGIS_AI_DATA_DIR" not in os.environ
        assert "WEBGIS_AI_AUTH_DB" not in os.environ
    finally:
        scrub_data_root_env()


def test_executor_does_not_pollute_process_env(tmp_path) -> None:
    """WorkflowExecutor must NOT mutate the process environment.

    ``backend.app.main`` builds the default runtime at import time, so any
    env write during executor construction would leak an absolute data-root
    override into every later ``AppConfig`` in the process (shared auth DB —
    the exact failure the phase-1 sandbox exists to prevent). Isolated
    deployments instead set ``WEBGIS_AI_DATA_DIR`` before launching the
    server; the spawned worker inherits that value, and without it the
    corrected repo-layout fallback applies.
    """
    from backend.app.services.workflow_executor import WorkflowExecutor
    from backend.app.store import RuntimeStore

    scrub_data_root_env()
    config = build_isolated_config(tmp_path)
    executor = WorkflowExecutor(config=config, store=RuntimeStore(config.state_file))
    assert executor.worker_manager.workflows_root == config.workflows_dir
    assert "WEBGIS_AI_DATA_DIR" not in os.environ
    assert executor.config.data_dir == config.data_dir
