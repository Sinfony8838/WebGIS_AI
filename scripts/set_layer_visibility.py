"""Set exactly one project layer visible (or none), hiding all others.

Usage: python set_layer_visibility.py <dataset_id|none> [project_id]
Requires the test session account baked in (claude-test@example.com).
"""
import http.cookiejar
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:19000"
EMAIL = "claude-test@example.com"
PASSWORD = "Test-Replay-2026!"
PROJECT = "project_d619628093ae445691536cd1950a5ca0"

jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def call(method, path, payload=None, csrf=""):
    data = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if csrf:
        req.add_header("X-WebGIS-CSRF", csrf)
    with opener.open(req, timeout=60) as r:
        b = r.read().decode()
    return json.loads(b) if b.strip() else {}


def main() -> int:
    target = sys.argv[1] if len(sys.argv) > 1 else "none"
    login = call("POST", "/auth/login", {"email": EMAIL, "password": PASSWORD})
    csrf = login["csrf_token"]
    project = call("GET", f"/projects/{PROJECT}")
    changed = []
    for layer in project.get("layers", []):
        lid = layer.get("layer_id") or layer.get("id")
        meta = layer.get("metadata") or {}
        catalog_id = str(meta.get("catalog_id") or lid.replace("one_map_", ""))
        want = (target != "none" and catalog_id == target)
        if bool(layer.get("visible")) != want:
            call("PATCH", "/layers", {"project_id": PROJECT, "layer_id": lid, "patch": {"visible": want}}, csrf=csrf)
            changed.append((catalog_id, want))
    print(json.dumps({"target": target, "changed": changed}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
