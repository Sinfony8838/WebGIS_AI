from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from .ppt_renderer import (
    _attempt_powerpoint_comtypes,
    _attempt_powerpoint_pywin32,
    _export_slides_incrementally,
)


def main(argv: List[str]) -> int:
    if len(argv) not in (4, 5):
        return 64
    source_path = Path(argv[1])
    export_dir = Path(argv[2])
    result_path = Path(argv[3])
    progress_path = Path(argv[4]) if len(argv) == 5 else None
    attempts: List[Dict[str, str]] = []

    result = None
    if progress_path is not None:
        # Per-slide export so the parent can serve page 1 while the rest render.
        result = _export_slides_incrementally(source_path, export_dir, progress_path, attempts)
        if result is None:
            attempts.append(
                {
                    "renderer": "powerpoint-incremental",
                    "status": "fallback",
                    "detail": "per-slide export failed; trying whole-deck export",
                }
            )
    if result is None:
        result = _attempt_powerpoint_pywin32(source_path, export_dir, attempts)
    if result is None:
        result = _attempt_powerpoint_comtypes(source_path, export_dir, attempts)

    payload: Dict[str, Any] = {"attempts": attempts, "result": None}
    if result is not None:
        payload["result"] = {
            **result,
            "image_paths": [str(path) for path in result.get("image_paths") or []],
        }

    result_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return 0 if result is not None else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
