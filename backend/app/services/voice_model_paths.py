"""Shared resolution of the local voice-model storage directory.

The backend and ``scripts/download_voice_models.py`` must agree on where the
sherpa-onnx models live, otherwise a model downloaded once shows up as "not
downloaded" in another checkout/worktree. Resolution order:

1. Explicit override (``WEBGIS_AI_VOICE_MODEL_DIR`` / config injection) —
   per-machine choice, always kept out of Git.
2. The legacy in-repo location ``<repo>/backend/data/voice-models`` — only
   when it already holds the complete model, so existing deployments keep
   working without moving 227 MB of files.
3. A stable per-user directory that does not depend on which worktree the
   code runs from: ``%LOCALAPPDATA%/WebGIS-AI/voice-models`` on Windows,
   ``~/.local/share/WebGIS-AI/voice-models`` elsewhere. Fresh downloads
   land here (never inside a worktree).

Pure ``pathlib``/``os`` only: the download script imports this module without
pulling in any backend runtime dependencies.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

MODEL_DIR_NAME = "voice-models"
PARAFORMER_SUBDIR = "sherpa-onnx-streaming-paraformer-bilingual-zh-en"

# The release ships fp32 and int8 variants; int8 is the right size/speed
# trade-off for a teacher laptop CPU. Sizes guard against truncated or
# partially extracted downloads being reported as "installed".
MODEL_FILES: Tuple[str, ...] = ("encoder.int8.onnx", "decoder.int8.onnx", "tokens.txt")
MIN_FILE_BYTES: Dict[str, int] = {
    "encoder.int8.onnx": 100 * 1024 * 1024,
    "decoder.int8.onnx": 40 * 1024 * 1024,
    "tokens.txt": 10_000,
}

ENV_MODEL_DIR = "WEBGIS_AI_VOICE_MODEL_DIR"
ENV_STABLE_ROOT = "WEBGIS_AI_VOICE_MODEL_STABLE_ROOT"


def env_override() -> Optional[Path]:
    """``WEBGIS_AI_VOICE_MODEL_DIR`` if set to a non-empty value."""
    value = (os.environ.get(ENV_MODEL_DIR) or "").strip()
    return Path(value) if value else None


def default_stable_root() -> Path:
    """Worktree-independent per-user default (created on demand)."""
    custom = (os.environ.get(ENV_STABLE_ROOT) or "").strip()
    if custom:
        return Path(custom)
    local_app_data = (os.environ.get("LOCALAPPDATA") or "").strip()
    if local_app_data:
        return Path(local_app_data) / "WebGIS-AI" / MODEL_DIR_NAME
    xdg_data_home = (os.environ.get("XDG_DATA_HOME") or "").strip()
    if xdg_data_home:
        return Path(xdg_data_home) / "WebGIS-AI" / MODEL_DIR_NAME
    return Path.home() / ".local" / "share" / "WebGIS-AI" / MODEL_DIR_NAME


def paraformer_dir(model_root: Path) -> Path:
    return model_root / PARAFORMER_SUBDIR


def missing_files(directory: Path) -> List[str]:
    return [name for name in MODEL_FILES if not (directory / name).is_file()]


def undersized_files(directory: Path) -> List[str]:
    return [
        name
        for name in MODEL_FILES
        if (directory / name).is_file() and (directory / name).stat().st_size < MIN_FILE_BYTES[name]
    ]


def files_complete(directory: Path) -> bool:
    """True when every model file exists and passes the size sanity check."""
    return not missing_files(directory) and not undersized_files(directory)


def resolve_model_dir(
    legacy_data_dir: Optional[Path] = None,
    override: Optional[Path] = None,
    stable_root: Optional[Path] = None,
) -> Path:
    """Resolve the paraformer model directory.

    ``legacy_data_dir`` is the caller's ``backend/data`` directory (injectable
    so tests stay hermetic); ``override``/``stable_root`` default to the
    environment lookups so the download script and the backend share one rule.
    """
    explicit = override if override is not None else env_override()
    if explicit:
        return paraformer_dir(explicit)
    if legacy_data_dir is not None:
        legacy = paraformer_dir(legacy_data_dir / MODEL_DIR_NAME)
        if files_complete(legacy):
            return legacy
    return paraformer_dir(stable_root if stable_root is not None else default_stable_root())


def install_target_dir(
    legacy_data_dir: Optional[Path] = None,
    override: Optional[Path] = None,
    stable_root: Optional[Path] = None,
) -> Path:
    """Where the download script installs: explicit override or the stable
    per-user directory. Never writes into a repository/worktree."""
    explicit = override if override is not None else env_override()
    if explicit:
        return paraformer_dir(explicit)
    return paraformer_dir(stable_root if stable_root is not None else default_stable_root())
