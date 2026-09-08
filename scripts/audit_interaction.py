"""Opt-in live interaction audit against an isolated local test server.

Creates a synthetic project and classroom; may call the configured MiniMax.
Uses only the standard library. See INTERACTION_AUDIT.md.
"""
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse


NOVEL_COMMANDS = [
    "先切换到二维地图，再打开图层管理器",
    "不要结束上课，只打开图层管理器",
    "把画面调成适合讲解长江三角洲的范围，并用卫星底图",
    "把地图中心设为东经120度北纬30度，缩放到7级",
    "请把不存在的火星矿产图层调到半透明",
    "找出人口最多的五座城市，然后定位到第一名",
    "给人口图层换一种醒目的蓝色并将它放到最上面",
    "查询2020年人口最多的20个城市",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="Isolated local backend URL")
    parser.add_argument("--allow-model-calls", action="store_true", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if urlparse(args.base_url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        parser.error("Use an isolated local test backend, not a shared or production server")
    if args.output.exists():
        parser.error("Output already exists; choose a new path to preserve previous evidence")

    def request(path: str, payload=None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(args.base_url.rstrip("/") + path, data=data,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=90) as response:
            return json.load(response)

    def wait_job(job_id: str):
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            job = request("/jobs/" + job_id)
            if job["status"] in {"completed", "failed"}:
                return job
            time.sleep(0.05)
        raise TimeoutError(job_id)

    project_id = request("/projects", {})["project_id"]
    context = {"lesson_id": "lesson_builtin_population_distribution", "phase": "course_prep"}
    report = {"project_id": project_id, "cases": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    def run(label: str, message: str, category: str, conversation_id: str = ""):
        start = time.perf_counter()
        submitted = request("/assistant/messages", {
            "project_id": project_id, "message": message, "assistant_mode": "interaction",
            "conversation_id": conversation_id, "teaching_context": context,
            "map_context": {"teaching_context": context, "view_mode": "plane"},
        })
        ack_ms = (time.perf_counter() - start) * 1000
        job = wait_job(submitted["job_id"])
        row = {"label": label, "message": message, "category": category,
               "ack_ms": round(ack_ms, 1), "elapsed_ms": round((time.perf_counter() - start) * 1000, 1), "job": job}
        report["cases"].append(row)
        result = job.get("result") or {}
        # Only approve the explicitly enumerated end-class preset, in this
        # newly created test classroom. Never approve a model-generated plan.
        if label == "end-class" and result.get("requires_confirmation"):
            row["confirmation_job"] = wait_job(request("/assistant/confirm", {
                "confirmation_id": result["confirmation_id"], "decision": "approve",
            })["job_id"])
        actual = row.get("confirmation_job", job).get("result") or {}
        for entry in actual.get("actions_executed", []):
            session = entry.get("result", {}).get("class_session") or {}
            if session.get("session_id"):
                context.update(session_id=session["session_id"], phase="in_class" if session["status"] == "running" else "post_class")
        row["project_after"] = request("/projects/" + project_id)
        save()
        print(json.dumps({"label": label, "ms": row["elapsed_ms"], "planner": result.get("planner"),
                          "reply": result.get("assistant_message")}, ensure_ascii=False), flush=True)
        return result

    root = Path(__file__).resolve().parents[1]
    source = (root / "frontend/src/components/CopilotWidget.tsx").read_text(encoding="utf-8")
    chips = {key: prompt for key, _, prompt in re.findall(r'\{ key: "([^"]+)", label: "([^"]+)", prompt: "([^"]+)" \}', source)}
    for key in ("globe", "plane", "layers", "database", "start-class", "next-stage", "hu-line", "end-class"):
        run(key, chips[key], "preset")
    for command in NOVEL_COMMANDS:
        run(command, command, "novel")
    first = run("reference-setup", "请记住，接下来“这两个面板”指图层管理器和数据库面板，暂时不用打开。", "conversation")
    run("reference-followup", "现在打开这两个面板", "conversation", first.get("conversation_id", ""))
    for row in report["cases"]:
        for entry in (row["job"].get("result") or {}).get("actions_executed", []):
            workflow = entry.get("result", {}).get("workflow") or {}
            if workflow.get("workflow_id"):
                row["workflow_final"] = request("/workflow/" + workflow["workflow_id"])
    save()


if __name__ == "__main__":
    main()
