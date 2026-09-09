"""Helpers shared by the dataset-integrity test modules."""
from __future__ import annotations

from pathlib import Path

from backend.app.config import AppConfig


def upload_files(config: AppConfig, project_id: str) -> list[str]:
    """Names of files persisted under the project's upload dir (sorted)."""
    upload_dir = config.project_upload_dir(project_id)
    if not upload_dir.exists():
        return []
    return sorted(path.name for path in upload_dir.iterdir() if path.is_file())
