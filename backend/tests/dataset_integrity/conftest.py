"""Shared fixtures for dataset-import integrity acceptance tests.

Each test runs against its own temporary state directory, project and
store, so the suite never touches real classroom data.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
FACTORY_DIR = REPO_ROOT / "scripts" / "qa" / "dataset_integrity"
if str(FACTORY_DIR) not in sys.path:
    sys.path.insert(0, str(FACTORY_DIR))

import sample_factory  # noqa: E402

from backend.app.config import AppConfig  # noqa: E402
from backend.app.services import crs_reprojector  # noqa: E402
from backend.app.services.datasets import DatasetService  # noqa: E402
from backend.app.store import RuntimeStore  # noqa: E402

__all__ = ["sample_factory", "service_env", "no_pyproj", "pyproj_available"]


@pytest.fixture
def service_env(tmp_path):
    """A DatasetService wired to a fully isolated temporary state dir."""
    config = AppConfig(root_dir=REPO_ROOT)
    config.data_dir = tmp_path / "backend" / "data"
    config.state_dir = config.data_dir / "state"
    config.uploads_dir = config.data_dir / "uploads"
    config.outputs_dir = config.data_dir / "outputs"
    config.state_file = config.state_dir / "runtime.json"
    config.ensure_dirs()
    store = RuntimeStore(config.state_file)
    project = store.create_project(base_map=config.default_basemap())
    service = DatasetService(config, store)
    return service, store, project.project_id, config


@pytest.fixture
def no_pyproj(monkeypatch):
    """Simulate a deployment where pyproj is missing."""
    monkeypatch.setattr(crs_reprojector, "_PYPROJ_AVAILABLE", False)


@pytest.fixture
def pyproj_available() -> bool:
    return crs_reprojector.pyproj_available()
