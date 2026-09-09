"""Post-step artifact validation inside the PyQGIS worker.

After a handler reports success we verify that every path-like output it
published actually exists, is non-empty, and can be re-opened with the right
format signature. This catches "algorithm reported success but wrote
nothing / truncated" failures before the executor publishes artifacts.

A legitimate empty result is NOT a failure: e.g. ``filter_features`` with no
matches exports a valid GeoJSON ``FeatureCollection`` with zero features and
reports ``feature_count: 0``. Empty-but-valid is expressed by the data
itself, so validation passes and the count travels to the frontend.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from .errors import WorkflowExecutionError
from .workspace import Workspace

#: Output keys that never hold file paths (aliases, scalars, relative twins
#: of validated absolute paths, ...).
_NON_PATH_KEYS = {
    "layer", "crs", "kind", "name", "id",
    "geojson_relative", "png_relative", "style_relative", "gpkg_relative",
    "stats", "summary", "fields", "extent", "units", "breaks", "palette",
}

_MAGIC_SIGNATURES = {
    ".png": b"\x89PNG\r\n\x1a\n",
    ".gpkg": b"SQLite format 3\x00",
    ".tif": None,  # little/big endian TIFF handled below
    ".tiff": None,
}

_PATH_SUFFIXES = {
    ".geojson", ".json", ".png", ".gpkg", ".tif", ".tiff", ".csv", ".style",
}


def _looks_like_path(value: str) -> bool:
    try:
        p = Path(value)
    except Exception:  # pragma: no cover - defensive
        return False
    if not p.suffix or p.suffix.lower() not in _PATH_SUFFIXES:
        return False
    return p.is_absolute()


def _raise_invalid(key: str, path: Path, reason: str) -> None:
    raise WorkflowExecutionError(
        code="OUTPUT_INVALID",
        message=f"output '{key}' failed validation at {path}: {reason}",
        user_friendly=f"步骤产物校验失败：{path.name} {reason}。",
        details={"key": key, "path": str(path), "reason": reason},
    )


def _check_reopenable(suffix: str, path: Path) -> str:
    """Read the head of the file and verify its format signature.

    Returns the head bytes' length consumed. Raises on mismatch.
    """
    needed = 512
    with path.open("rb") as fh:
        head = fh.read(needed)
    expected = _MAGIC_SIGNATURES.get(suffix)
    if expected is not None:
        if not head.startswith(expected):
            _raise_invalid_magic(path, suffix)
    elif suffix in (".tif", ".tiff"):
        if not (head.startswith(b"II*\x00") or head.startswith(b"MM\x00*")):
            _raise_invalid_magic(path, suffix)
    elif suffix in (".geojson", ".json"):
        stripped = head.lstrip()
        if not stripped[:1] in (b"{", b"["):
            _raise_invalid_magic(path, suffix)
        # A GeoJSON must also parse as JSON — guard against truncated writes.
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise WorkflowExecutionError(
                code="OUTPUT_INVALID",
                message=f"output at {path} is not valid JSON: {exc}",
                user_friendly=f"步骤产物校验失败：{path.name} 不是有效的 JSON。",
                details={"key": "", "path": str(path), "reason": "invalid json"},
            ) from exc
    # .csv / .style: non-empty is the best cheap check
    return ""


def _raise_invalid_magic(path: Path, suffix: str) -> None:
    raise WorkflowExecutionError(
        code="OUTPUT_INVALID",
        message=f"output at {path} does not look like a {suffix} file",
        user_friendly=f"步骤产物校验失败：{path.name} 格式损坏。",
        details={"path": str(path), "expected": suffix},
    )


def validate_step_outputs(outputs: Dict[str, Any], workspace: Workspace) -> None:
    """Validate every path-like output published by a successful step."""
    for key, value in (outputs or {}).items():
        if key in _NON_PATH_KEYS or not isinstance(value, str) or not value.strip():
            continue
        if not _looks_like_path(value):
            continue
        path = Path(value)
        if not path.exists():
            _raise_invalid(key, path, "file does not exist")
        try:
            size = path.stat().st_size
        except OSError as exc:  # pragma: no cover - defensive
            _raise_invalid(key, path, f"stat failed: {exc}")
        if size == 0:
            _raise_invalid(key, path, "file is empty")
        _check_reopenable(path.suffix.lower(), path)
