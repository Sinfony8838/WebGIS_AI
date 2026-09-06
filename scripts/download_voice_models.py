#!/usr/bin/env python3
"""Download the local streaming ASR model for the voice interaction mode.

One-time deployment step for the classroom demo machine:

    python scripts/download_voice_models.py

Pulls the sherpa-onnx streaming Paraformer bilingual (zh-en) model from the
k2-fsa GitHub release area into ``backend/data/voice-models/`` (gitignored).
After it finishes, ``GET /health`` reports ``voice_asr.available == true``
and the frontend uses the local WebSocket recognizer instead of the browser
Web Speech API.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

MODEL_VERSION = "1.13.7"
MODEL_NAME = "sherpa-onnx-streaming-paraformer-bilingual-zh-en"
MODEL_DIR_NAME = "voice-models"
# Release assets live under github.com/k2-fsa/sherpa-onnx/releases/tag/asr-models
BASE_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models"

NEEDED_FILES = ("encoder.int8.onnx", "decoder.int8.onnx", "tokens.txt")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def download_and_extract(target_dir: Path) -> None:
    # Release assets live under github.com/k2-fsa/sherpa-onnx/releases/tag/asr-models
    # (asset names are not version-stamped for this model).
    base_url = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models"
    urls = [
        f"{base_url}/{MODEL_NAME}.tar.bz2",
        f"{base_url}/{MODEL_NAME}.zip",
    ]

    target_dir.mkdir(parents=True, exist_ok=True)
    final_dir = target_dir / MODEL_NAME
    final_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        archive_path = None
        last_error: Exception | None = None
        for candidate in urls:
            try:
                print(f"downloading {candidate} ...")
                archive_path = tmp_path / candidate.rsplit("/", 1)[-1]
                urllib.request.urlretrieve(candidate, archive_path)
                break
            except Exception as exc:  # noqa: BLE001 - report and try next mirror
                last_error = exc
                archive_path = None
        if archive_path is None:
            raise SystemExit(f"download failed: {last_error}")

        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        if archive_path.name.endswith(".zip"):
            with zipfile.ZipFile(archive_path) as zf:
                zf.extractall(extract_dir)
        else:
            shutil.unpack_archive(str(archive_path), str(extract_dir))

        # The archive contains a top-level folder; find the model files.
        for name in NEEDED_FILES:
            matches = list(extract_dir.rglob(name))
            if not matches:
                raise SystemExit(f"{name} not found in archive {archive_path.name}")
            shutil.copy2(matches[0], final_dir / name)
            print(f"installed {final_dir / name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-download even if the model files already exist",
    )
    args = parser.parse_args()

    target_dir = repo_root() / "backend" / "data" / MODEL_DIR_NAME
    final_dir = target_dir / MODEL_NAME
    existing = [name for name in NEEDED_FILES if (final_dir / name).is_file()]
    if existing and not args.force:
        print(f"model already present ({len(existing)}/{len(NEEDED_FILES)} files) at {final_dir}")
        print("use --force to re-download")
        return 0

    download_and_extract(target_dir)
    missing = [name for name in NEEDED_FILES if not (final_dir / name).is_file()]
    if missing:
        print(f"ERROR: missing after install: {missing}", file=sys.stderr)
        return 1
    print("done — restart the backend, /health should report voice_asr.available == true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
