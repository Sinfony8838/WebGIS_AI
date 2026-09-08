"""Matrix test for every GIS workflow template (POST /workflow/submit).

Submits each template with sensible parameters, waits for the terminal
status, and prints one JSON line per template with timing, per-step status,
and artifact sanity info (feature counts, style classes, stats rows).
"""
import os
import http.cookiejar
import json
import sys
import time
import urllib.request

BASE = os.environ.get("WEBGIS_TEST_BASE", "http://127.0.0.1:19000")
EMAIL = os.environ.get("WEBGIS_TEST_EMAIL", "")
PASSWORD = os.environ.get("WEBGIS_TEST_PASSWORD", "")
PROJECT = os.environ.get("WEBGIS_TEST_PROJECT", "")

PROVINCES = "builtin:one_map/population/china_province_population_density.geojson"
CENTROIDS = "builtin:population/population_centroids.geojson"
MIGRATION = "builtin:population/migration_flows.geojson"

CASES = [
    {"template_id": "population_choropleth", "message": "制作中国人口密度分级设色图", "parameters": {"dataset": PROVINCES}},
    {"template_id": "facility_buffer", "message": "对大区中心点做500公里缓冲区", "parameters": {"facility_dataset": CENTROIDS, "distance_m": 500000}},
    {"template_id": "hu_line_compare", "message": "胡焕庸线两侧人口密度对比", "parameters": {"province_dataset": PROVINCES}},
    {"template_id": "clip_to_region", "message": "把中心点图层裁剪到省域范围", "parameters": {"input_dataset": CENTROIDS, "region_dataset": PROVINCES}},
    {"template_id": "overlay_intersection", "message": "迁徙连线与省域图层求交集", "parameters": {"input_dataset": MIGRATION, "overlay_dataset": PROVINCES}},
    {"template_id": "spatial_join_attributes", "message": "中心点图层连接省域属性", "parameters": {"input_dataset": CENTROIDS, "join_dataset": PROVINCES}},
    {"template_id": "classify_field", "message": "对人口字段做分级", "parameters": {"dataset": PROVINCES, "field": "population"}},
]

jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def call(method: str, path: str, payload=None, csrf: str = "", timeout: int = 30, raw: bool = False):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if csrf:
        req.add_header("X-WebGIS-CSRF", csrf)
    with opener.open(req, timeout=timeout) as resp:
        body = resp.read()
    if raw:
        return body
    body = body.decode("utf-8")
    return json.loads(body) if body.strip() else {}


def artifact_summary(wf_id: str, artifacts: list) -> list:
    summary = []
    for artifact in artifacts:
        kind = artifact.get("kind")
        entry = {"kind": kind, "title": artifact.get("title")}
        url = artifact.get("public_url", "")
        try:
            payload = call("GET", url if url.startswith("/") else f"/{url}", timeout=20, raw=kind in {"png", "summary"})
            if kind == "geojson":
                feats = payload.get("features", [])
                entry["features"] = len(feats)
                entry["geom_types"] = sorted({f.get("geometry", {}).get("type") for f in feats if f.get("geometry")})
            elif kind == "style":
                entry["type"] = payload.get("type")
                entry["field"] = payload.get("field")
                entry["classes"] = len(payload.get("classes", []))
            elif kind == "stats":
                entry["rows"] = payload.get("all_rows_count", len(payload.get("rows", [])))
            elif kind == "png":
                if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
                    raise ValueError("invalid PNG signature")
                entry["bytes"] = len(payload)
            elif kind == "summary":
                entry["characters"] = len(payload.decode("utf-8"))
        except Exception as exc:
            entry["error"] = str(exc)[:80]
        summary.append(entry)
    return summary


def run_case(case: dict, csrf: str, timeout_s: float = 240) -> dict:
    t0 = time.perf_counter()
    submit = call("POST", "/workflow/submit", {"project_id": PROJECT, "mode": "template", **case}, csrf=csrf)
    if submit.get("status") != "success":
        return {"template": case["template_id"], "result": "SUBMIT_FAIL", "error": submit.get("error") or submit}
    wf = submit["workflow_id"]
    deadline = time.time() + timeout_s
    record = {}
    status = ""
    while time.time() < deadline:
        record = call("GET", f"/workflow/{wf}")
        status = record.get("workflow_status") or record.get("status")
        if status in ("success", "error"):
            break
        time.sleep(0.4)
    total = time.perf_counter() - t0
    steps = [
        {
            "id": s.get("id"),
            "op": s.get("op") or s.get("title"),
            "status": s.get("status"),
            "s": round((parse_ts(s.get("finished_at")) - parse_ts(s.get("started_at"))), 3)
            if s.get("started_at") and s.get("finished_at")
            else None,
        }
        for s in record.get("steps", [])
    ]
    return {
        "template": case["template_id"],
        "workflow_id": wf,
        "result": status,
        "total_s": round(total, 2),
        "steps": steps,
        "artifacts": artifact_summary(wf, record.get("artifacts", [])),
        "error": record.get("error"),
    }


def parse_ts(value):
    if not value:
        return None
    from datetime import datetime

    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def main() -> int:
    global PROJECT
    if EMAIL and PASSWORD:
        login = call("POST", "/auth/login", {"email": EMAIL, "password": PASSWORD})
    else:
        # Only a deliberately auth-disabled local test service permits this.
        login = call("GET", "/auth/me")
    csrf = login.get("csrf_token", "")
    if not PROJECT:
        PROJECT = call("POST", "/projects", {"name": "GIS acceptance test"}, csrf=csrf)["project_id"]
    results = []
    for case in CASES:
        outcome = run_case(case, csrf)
        results.append(outcome)
        print(json.dumps(outcome, ensure_ascii=False), flush=True)
    fails = [r for r in results if r["result"] != "success" or any(a.get("error") for a in r.get("artifacts", []))]
    print(f"\n== {len(results) - len(fails)}/{len(results)} templates succeeded ==", file=sys.stderr)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
