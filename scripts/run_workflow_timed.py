"""Timed end-to-end workflow run against the local test backend.

Logs in, submits the population choropleth workflow, polls until terminal
status, and prints a wall-clock timeline (submit, worker steps, artifacts).
"""
import http.cookiejar
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:19000"
EMAIL = "claude-test@example.com"
PASSWORD = "Test-Replay-2026!"
PROJECT = "project_d619628093ae445691536cd1950a5ca0"
DATASET = "builtin:one_map/population/china_province_population_density.geojson"

jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def call(method: str, path: str, payload: dict | None = None, csrf: str = ""):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if csrf:
        req.add_header("X-WebGIS-CSRF", csrf)
    with opener.open(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    t0 = time.perf_counter()
    login = call("POST", "/auth/login", {"email": EMAIL, "password": PASSWORD})
    csrf = login["csrf_token"]
    print(f"[{time.perf_counter() - t0:7.2f}s] login ok (csrf {csrf[:8]}…)")

    submit = call(
        "POST",
        "/workflow/submit",
        {
            "project_id": PROJECT,
            "message": "制作中国人口密度分级设色图",
            "mode": "template",
            "template_id": "population_choropleth",
            "parameters": {"dataset": DATASET},
        },
        csrf=csrf,
    )
    if submit.get("status") != "success":
        print("submit failed:", json.dumps(submit, ensure_ascii=False)[:500])
        return 1
    wf_id = submit["workflow_id"]
    print(f"[{time.perf_counter() - t0:7.2f}s] submitted workflow {wf_id} template={submit.get('template_id')}")

    seen_steps: set[str] = set()
    seen_artifacts: set[str] = set()
    last_status = ""
    deadline = time.time() + 240
    record: dict = {}
    while time.time() < deadline:
        record = call("GET", f"/workflow/{wf_id}")
        status = record.get("workflow_status") or record.get("status")
        if status != last_status:
            print(f"[{time.perf_counter() - t0:7.2f}s] status -> {status}")
            last_status = status
        for step in record.get("steps", []):
            key = f"{step.get('id')}:{step.get('status')}"
            if key not in seen_steps:
                seen_steps.add(key)
                detail = step.get("error") or ""
                print(f"[{time.perf_counter() - t0:7.2f}s] step {step.get('id')} ({step.get('title', '')}) -> {step.get('status')} {detail[:80]}")
        for artifact in record.get("artifacts", []):
            if artifact.get("artifact_id") not in seen_artifacts:
                seen_artifacts.add(artifact["artifact_id"])
                print(
                    f"[{time.perf_counter() - t0:7.2f}s] artifact {artifact.get('kind'):8s} {artifact.get('title', '')} {artifact.get('public_url', '')}"
                )
        if status in ("success", "error"):
            break
        time.sleep(0.5)

    total = time.perf_counter() - t0
    print(f"[{total:7.2f}s] terminal status={record.get('workflow_status')} error={json.dumps(record.get('error'), ensure_ascii=False) if record.get('error') else '-'}")
    print("\nstep timestamps from record:")
    for step in record.get("steps", []):
        print(
            " ",
            step.get("id"),
            step.get("status"),
            f"started={step.get('started_at', '')} finished={step.get('finished_at', '')}",
        )
    return 0 if record.get("workflow_status") == "success" else 2


if __name__ == "__main__":
    sys.exit(main())
