"""Set exactly one project layer visible (or none), hiding all others.

Usage: python set_layer_visibility.py <dataset_id|none>
WEBGIS_TEST_PROJECT is required; this script changes visibility in that project.
Set WEBGIS_TEST_BASE, WEBGIS_TEST_EMAIL, WEBGIS_TEST_PASSWORD and WEBGIS_TEST_PROJECT.
"""
import os
import http.cookiejar
import json
import sys
import urllib.request

BASE = os.environ.get("WEBGIS_TEST_BASE", "http://127.0.0.1:19000")
EMAIL = os.environ.get("WEBGIS_TEST_EMAIL", "")
PASSWORD = os.environ.get("WEBGIS_TEST_PASSWORD", "")
PROJECT = os.environ.get("WEBGIS_TEST_PROJECT", "")

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
    global PROJECT
    if not PROJECT:
        raise ValueError("WEBGIS_TEST_PROJECT is required")
    target = sys.argv[1] if len(sys.argv) > 1 else "none"
    if EMAIL and PASSWORD:
        login = call("POST", "/auth/login", {"email": EMAIL, "password": PASSWORD})
    else:
        # Only a deliberately auth-disabled local test service permits this.
        login = call("GET", "/auth/me")
    csrf = login.get("csrf_token", "")
    if not PROJECT:
        PROJECT = call("POST", "/projects", {"name": "GIS acceptance test"}, csrf=csrf)["project_id"]
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
