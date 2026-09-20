"""Standard-entry isolation preflight (phase-1 acceptance task A).

This conftest runs before any test module (and therefore before
``backend.app.main`` is imported at collection time). It closes the two
ways the standard ``pytest backend/tests`` entry could touch a non-test
data tree:

1. Inherited environment overrides (``WEBGIS_AI_DATA_DIR`` /
   ``WEBGIS_AI_AUTH_DB`` pointing at an operator's production instance)
   are scrubbed from the process environment.
2. If the checkout's default data root already holds a live instance
   (``auth/auth.db`` or ``state/runtime.json``), collection aborts with an
   explicit error instead of silently opening it. Opt out deliberately
   with ``WEBGIS_AI_ALLOW_EXISTING_DATA=1`` — normally you either run
   tests from a clean worktree or delete test-generated ``backend/data``.

Output uses repo-relative labels only, never absolute local paths.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: Overrides that can redirect identity/data storage into a real instance.
INHERITED_OVERRIDE_VARS = ("WEBGIS_AI_DATA_DIR", "WEBGIS_AI_AUTH_DB")

#: Markers of a live (previously used) data instance.
INSTANCE_MARKERS = (("auth_db", "auth/auth.db"), ("state_file", "state/runtime.json"))


def scrub_inherited_overrides() -> list[str]:
    """Remove inherited data-root overrides; return removed variable names."""
    removed = []
    for name in INHERITED_OVERRIDE_VARS:
        value = os.environ.pop(name, None)
        if value is not None and value.strip():
            removed.append(name)
    return removed


def default_data_root() -> Path:
    """Default data root for this checkout (env already scrubbed)."""
    sys.path.insert(0, str(_REPO_ROOT))
    from backend.app.config import resolve_data_root

    return resolve_data_root(_REPO_ROOT)


def instance_marker_labels(data_root: Path) -> list[str]:
    """Labels of live-instance markers present under ``data_root``."""
    found = []
    for label, relative in INSTANCE_MARKERS:
        if (Path(data_root) / relative).exists():
            found.append(label)
    return found


def run_preflight() -> None:
    scrub_inherited_overrides()
    if os.environ.get("WEBGIS_AI_ALLOW_EXISTING_DATA", "").strip() in {"1", "true", "yes", "on"}:
        return
    markers = instance_marker_labels(default_data_root())
    if markers:
        pytest.exit(
            "Refusing to run tests against this checkout's existing data instance "
            f"(markers: {', '.join(markers)} under backend/data). "
            "Run tests from a clean worktree, delete test-generated backend/data, "
            "or set WEBGIS_AI_ALLOW_EXISTING_DATA=1 to explicitly opt in.",
            returncode=2,
        )


run_preflight()
