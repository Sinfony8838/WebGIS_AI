#!/usr/bin/env python3
"""Write every QA sample to a directory with a manifest of expected outcomes.

Usage (from the repo root, Python 3.12):

    python scripts/qa/dataset_integrity/generate_samples.py --out <dir>

The output directory is git-ignored runtime material; the committed source
of truth is :mod:`sample_factory`, which regenerates everything
deterministically.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sample_factory


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        required=True,
        help="Directory to write samples into (created on demand).",
    )
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    samples = sample_factory.generate_all()
    catalog = {entry["file"]: entry for entry in sample_factory.build_catalog()}

    for filename, payload in sorted(samples.items()):
        (out_dir / filename).write_bytes(payload)

    manifest = {
        "generated_by": "scripts/qa/dataset_integrity/generate_samples.py",
        "sample_count": len(samples),
        "samples": [
            {
                "file": filename,
                "bytes": len(payload),
                **catalog.get(filename, {}),
            }
            for filename, payload in sorted(samples.items())
        ],
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {len(samples)} samples + manifest.json to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
