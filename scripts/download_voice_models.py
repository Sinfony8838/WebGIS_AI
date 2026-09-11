#!/usr/bin/env python3
"""Download / verify the local streaming ASR model for the voice mode.

Deployment steps for the classroom demo machine:

    python scripts/download_voice_models.py          # download if incomplete
    python scripts/download_voice_models.py --check  # verify deps + real load

Model location rule (shared with the backend, see
``backend/app/services/voice_model_paths.py``):

1. ``WEBGIS_AI_VOICE_MODEL_DIR`` if set;
2. the legacy in-repo ``backend/data/voice-models`` — only when it already
   holds the complete model (existing deployments keep working);
3. the stable per-user directory ``%LOCALAPPDATA%/WebGIS-AI/voice-models``
   (or ``~/.local/share/WebGIS-AI/voice-models``), so the model survives
   switching worktrees. Downloads always install there (or into the explicit
   override) — never into a repository checkout.

The install is atomic: the archive is unpacked into a temp directory,
validated (all three files, minimum sizes), staged next to the target and
only then moved into place. Re-running is safe; a failed run never leaves a
half-installed model behind and never touches a complete install without
``--force``.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.voice_model_paths import (  # noqa: E402
    MIN_FILE_BYTES,
    MODEL_FILES,
    PARAFORMER_SUBDIR,
    files_complete,
    install_target_dir,
    missing_files,
    resolve_model_dir,
    undersized_files,
)

# Release assets live under github.com/k2-fsa/sherpa-onnx/releases/tag/asr-models
# (asset names are not version-stamped for this model).
BASE_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models"
ARCHIVE_URLS = [
    f"{BASE_URL}/{PARAFORMER_SUBDIR}.tar.bz2",
    f"{BASE_URL}/{PARAFORMER_SUBDIR}.zip",
]


def legacy_data_dir() -> Path:
    return BACKEND_DIR / "data"


def download_archive(tmp_path: Path) -> Path:
    archive_path: Path | None = None
    last_error: Exception | None = None
    for candidate in ARCHIVE_URLS:
        try:
            print(f"downloading {candidate} ...")
            archive_path = tmp_path / candidate.rsplit("/", 1)[-1]
            urllib.request.urlretrieve(candidate, archive_path)
            break
        except Exception as exc:  # noqa: BLE001 - report and try next mirror
            last_error = exc
            archive_path = None
    if archive_path is None:
        raise RuntimeError(f"download failed: {last_error}")
    return archive_path


def extract_and_validate(archive_path: Path, extract_dir: Path) -> dict[str, Path]:
    """Unpack the archive and locate the three validated model files."""
    if archive_path.name.endswith(".zip"):
        with zipfile.ZipFile(archive_path) as zf:
            zf.extractall(extract_dir)
    else:
        shutil.unpack_archive(str(archive_path), str(extract_dir))

    found: dict[str, Path] = {}
    for name in MODEL_FILES:
        matches = list(extract_dir.rglob(name))
        if not matches:
            raise RuntimeError(f"{name} not found in archive {archive_path.name}")
        source = matches[0]
        minimum = MIN_FILE_BYTES[name]
        actual = source.stat().st_size
        if actual < minimum:
            raise RuntimeError(f"{name} is truncated ({actual} bytes < required {minimum})")
        found[name] = source
    return found


def install_into(target_dir: Path, found: dict[str, Path]) -> None:
    """Stage the validated files next to the target and move them in."""
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = target_dir.parent / f".{target_dir.name}.staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    try:
        for name, source in found.items():
            shutil.copy2(source, staging / name)
        broken = missing_files(staging) + undersized_files(staging)
        if broken:
            raise RuntimeError(f"staged install failed validation: {broken}")
        if target_dir.exists():
            shutil.rmtree(target_dir)
        staging.rename(target_dir)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def print_state(title: str) -> tuple[Path, bool]:
    resolved = resolve_model_dir(legacy_data_dir=legacy_data_dir())
    print(f"{title} model dir: {resolved}")
    missing = missing_files(resolved)
    undersized = undersized_files(resolved)
    if not missing and not undersized:
        for name in MODEL_FILES:
            print(f"  ok       {name} ({(resolved / name).stat().st_size:,} bytes)")
        return resolved, True
    for name in MODEL_FILES:
        path = resolved / name
        if not path.is_file():
            print(f"  missing  {name}")
        elif path.stat().st_size < MIN_FILE_BYTES[name]:
            print(f"  undersized {name} ({path.stat().st_size:,} bytes, need >= {MIN_FILE_BYTES[name]:,})")
        else:
            print(f"  ok       {name} ({path.stat().st_size:,} bytes)")
    return resolved, False


def check() -> int:
    """Deployment readiness probe: dependencies + files + a real model load."""
    print("== voice ASR deployment check ==")
    print(f"python: {sys.executable}")

    resolved, files_ok = print_state("resolved")

    try:
        import numpy  # noqa: F401
        import sherpa_onnx
    except Exception as exc:  # noqa: BLE001
        print(f"dependency sherpa-onnx: NOT IMPORTABLE ({exc})")
        print("install with: pip install sherpa-onnx numpy  (see backend/requirements.txt)")
        return 1
    print("dependency sherpa-onnx: ok")

    if not files_ok:
        print("result: NOT READY — model files missing or incomplete")
        print("run: python scripts/download_voice_models.py")
        return 1

    print("loading recognizer (real ONNX session) ...")
    started = time.monotonic()
    try:
        import sherpa_onnx

        recognizer = sherpa_onnx.OnlineRecognizer.from_paraformer(
            tokens=str(resolved / "tokens.txt"),
            encoder=str(resolved / "encoder.int8.onnx"),
            decoder=str(resolved / "decoder.int8.onnx"),
            num_threads=1,
            sample_rate=16000,
            feature_dim=80,
            enable_endpoint_detection=True,
        )
        del recognizer
    except Exception as exc:  # noqa: BLE001
        print(f"result: LOAD FAILED — {exc}")
        return 1
    print(f"recognizer loaded in {time.monotonic() - started:.1f}s")
    print("result: READY — /health should report voice_asr available/state=ready")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-download even if the model files already exist",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify dependencies, file integrity and a real model load; exit 1 when not ready",
    )
    args = parser.parse_args()

    if args.check:
        return check()

    resolved = resolve_model_dir(legacy_data_dir=legacy_data_dir())
    if files_complete(resolved) and not args.force:
        print(f"model already complete at {resolved}")
        print("use --force to re-download, --check to verify a real load")
        return 0

    target = install_target_dir(legacy_data_dir=legacy_data_dir())
    if args.force and target.exists():
        print(f"removing existing install at {target}")
        shutil.rmtree(target)

    with tempfile.TemporaryDirectory(prefix="webgis-voice-models-") as tmp:
        tmp_path = Path(tmp)
        archive_path = download_archive(tmp_path)
        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        found = extract_and_validate(archive_path, extract_dir)

        print(f"installing into {target} ...")
        install_into(target, found)

    final_missing = missing_files(target)
    if final_missing:
        print(f"ERROR: missing after install: {final_missing}", file=sys.stderr)
        return 1
    print("done — verify with: python scripts/download_voice_models.py --check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
