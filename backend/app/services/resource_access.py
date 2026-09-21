"""Normalized resource-identity helpers for file-serving authorization.

Phase-1 audit task T2: authorization must be derived from *normalized
registered resources* (the configured uploads/outputs trees, the explicit
shared-public directory, the artifact registry, per-project roots) — never
from raw URL substrings. The HTTP layer (``get_public_file``,
``_grant_response_files``) and the workflow preflight share this module so
API checks and worker-side loads follow the same boundary.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Sequence

_FILES_URL_PREFIX = "/files/"
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")

#: Directory under ``uploads`` whose contents are registered as shared
#: teaching assets (builtin teaching maps copied in by the teaching-map
#: service). Membership is decided on the *resolved* path, not the URL text.
SHARED_PUBLIC_UPLOAD_DIRNAME = "teaching_maps"


def normalize_file_reference(reference: str) -> Optional[Path]:
    """Normalize a ``/files/...`` URL or a relative uploads/outputs reference.

    Returns a relative ``Path`` anchored at the data root whose first segment
    is ``uploads`` or ``outputs`` — or ``None`` when the reference is not a
    valid public-file reference (foreign text, URL-encoded or raw traversal,
    drive letters, backslashes). Normalization happens *before* any
    filesystem access so malformed input can never widen authorization.
    """
    if not isinstance(reference, str):
        return None
    value = reference.strip()
    if value.startswith(_FILES_URL_PREFIX):
        value = value[len(_FILES_URL_PREFIX):]
    if not value:
        return None
    if value.startswith("/") or "\\" in value or _WINDOWS_DRIVE.match(value):
        return None
    parts = tuple(part for part in value.split("/") if part not in ("", "."))
    if not parts or any(part == ".." for part in parts):
        return None
    if parts[0] not in {"uploads", "outputs"}:
        return None
    return Path(*parts)


def resolve_public_reference(config, reference: str) -> Optional[Path]:
    """Resolve a public reference to a real path inside the configured trees.

    Symlinks are followed *before* the containment check, so a link planted
    under uploads/outputs pointing outside the data root resolves to ``None``.
    """
    relative = normalize_file_reference(reference)
    if relative is None:
        return None
    root = config.uploads_dir if relative.parts[0] == "uploads" else config.outputs_dir
    root_resolved = Path(root).resolve()
    candidate = (root_resolved / Path(*relative.parts[1:])).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError:
        return None
    return candidate


def is_shared_public_asset(config, resolved: Path) -> bool:
    """True for registered shared teaching assets (uploads/teaching_maps)."""
    shared_root = (Path(config.uploads_dir) / SHARED_PUBLIC_UPLOAD_DIRNAME).resolve()
    try:
        Path(resolved).resolve().relative_to(shared_root)
    except ValueError:
        return False
    return Path(resolved).is_file()


def path_within(candidate: Path, root: Path) -> bool:
    """Containment on resolved paths (symlink/junction aware)."""
    try:
        Path(candidate).resolve().relative_to(Path(root).resolve())
    except ValueError:
        return False
    return True


def project_grant_roots(config, project_id: str) -> tuple:
    """Uploads/outputs roots owned by a project (used to scope response grants)."""
    return (Path(config.uploads_dir) / project_id, Path(config.outputs_dir) / project_id)


def bank_grant_roots(config, bank_ids: Sequence[str]) -> tuple:
    """Per-bank image roots; only banks the request already authorized."""
    return tuple(
        Path(config.uploads_dir) / "question_banks" / str(bank_id) for bank_id in bank_ids if bank_id
    )
