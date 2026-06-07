from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from .ppt_renderer import _attempt_powerpoint_comtypes, _attempt_powerpoint_pywin32


def main(argv: List[str]) -> int:
    if len(argv) != 4:
        return 64
    source_path = Path(argv[1])
    export_dir = Path(argv[2])
    result_path = Path(argv[3])
    attempts: List[Dict[str, str]] = []

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
