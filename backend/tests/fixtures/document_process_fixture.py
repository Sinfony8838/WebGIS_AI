"""Trusted test-only child for exercising the real production process boundary."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from backend.app.services.document_worker import worker_main


def dispatch(operation, raw, filename, kind):
    data = json.loads(raw)
    if data.get("pid_file"):
        Path(data["pid_file"]).write_text(str(os.getpid()), encoding="utf-8")
    if data.get("child_pid_file"):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
        Path(data["child_pid_file"]).write_text(str(child.pid), encoding="utf-8")
    mode = data.get("mode", "echo")
    if mode in {"oversized_result", "invalid_result", "invalid_schema", "late_result"}:
        content = {"oversized_result": "x" * 10000, "invalid_result": "not JSON",
                   "invalid_schema": '{"ok":true,"value":23}',
                   "late_result": '{"ok":true,"value":{"value":"too late"}}'}[mode]
        (Path(sys.argv[1]) / "result.json").write_text(content, encoding="utf-8")
        if mode == "late_result":
            time.sleep(data["seconds"])
        os._exit(0)
    if mode == "unserializable":
        return object()
    if mode in {"archive_limit", "docx_budget"}:
        from backend.app.services.archive_safety import ArchiveLimitError
        from backend.app.services.question_bank_parser import DocxBudgetError
        raise {"archive_limit": ArchiveLimitError, "docx_budget": DocxBudgetError}[mode]("fixture budget")
    if mode == "memory":
        return len(bytearray(512 * 1024 * 1024))
    if mode == "crash":
        os._exit(23)
    if mode == "gate":
        while not Path(data["gate_file"]).exists():
            time.sleep(0.01)
    if mode == "sleep":
        time.sleep(data["seconds"])
    if mode == "large":
        return "x" * 10000
    if data.get("order_file"):
        with Path(data["order_file"]).open("a", encoding="utf-8") as target:
            target.write(str(data["value"]) + "\n")
    return {"value": data.get("value", "finished"),
            "pid": os.getpid(), "memory_cap": int(sys.argv[2]),
            "secret": os.environ.get("WEBGIS_AI_MINIMAX_API_KEY"),
            "loaded_forbidden": [name for name in sys.modules if name in (
                "backend.app.main", "backend.app.runtime", "backend.app.config",
                "backend.app.services.minimax_client")]}


if __name__ == "__main__":
    raise SystemExit(worker_main(dispatch))
