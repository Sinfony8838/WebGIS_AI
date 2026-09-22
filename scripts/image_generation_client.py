"""Authenticated WebGIS image API example. No provider key is needed on the client."""
from __future__ import annotations

import argparse
import getpass
import hashlib
import http.cookiejar
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


class WebGISImageClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        parsed = urllib.parse.urlsplit(self.base_url)
        if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}):
            raise ValueError("Use HTTPS, or HTTP on localhost for development.")
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.csrf = ""

    def request(self, path: str, payload: dict | None = None) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.csrf and payload is not None:
            headers["X-WebGIS-CSRF"] = self.csrf
        req = urllib.request.Request(self.base_url + path, headers=headers,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None)
        try:
            with self.opener.open(req, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                detail = json.load(exc).get("detail", "Request failed")
                message = detail.get("message", "Request failed") if isinstance(detail, dict) else str(detail)
            except (ValueError, AttributeError):
                message = "Request failed"
            raise RuntimeError(f"HTTP {exc.code}: {message}") from exc

    def login(self, email: str, password: str) -> None:
        result = self.request("/auth/login", {"email": email, "password": password})
        if result["user"].get("must_change_password"):
            raise RuntimeError("Please change your temporary password in the website first.")
        self.csrf = result["csrf_token"]

    def wait(self, job_id: str, timeout: float = 180) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = self.request("/jobs/" + urllib.parse.quote(job_id, safe=""))
            if job["status"] == "failed":
                raise RuntimeError(job.get("error") or "Image generation failed")
            if job["status"] == "completed":
                return job["result"]["artifact"]
            time.sleep(1.5)
        raise TimeoutError(f"Job {job_id} is still pending. Resume this job; do not submit it again.")

    def download(self, artifact: dict, destination: Path) -> Path:
        relative = str(artifact["metadata"]["public_url"])
        if not relative.startswith("/files/") or "\\" in relative:
            raise ValueError("Unexpected artifact URL")
        suffix = Path(urllib.parse.urlsplit(relative).path).suffix
        name = re.sub(r"[^a-zA-Z0-9_-]", "_", artifact["artifact_id"]) + suffix
        path = destination / name
        with self.opener.open(self.base_url + relative, timeout=30) as response:
            path.write_bytes(response.read())
        return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="https://webgisai.com")
    parser.add_argument("--email", default=os.getenv("WEBGIS_IMAGE_EMAIL", ""))
    parser.add_argument("--project-id")
    parser.add_argument("--prompt-file", type=Path)
    parser.add_argument("--model", default="image-01", choices=["image-01", "image-01-live"])
    parser.add_argument("--aspect-ratio", default="16:9")
    parser.add_argument("--title", default="地理教学素材")
    parser.add_argument("--no-prompt-optimizer", action="store_true")
    parser.add_argument("--confirmed", action="store_true", help="Confirm paid use for a non-admin account.")
    parser.add_argument("--resume-job", help="Only poll this existing job; never resubmit generation.")
    parser.add_argument("--output-dir", type=Path, default=Path("image-generation-output"))
    args = parser.parse_args()
    if not args.email or (not args.resume_job and (not args.project_id or not args.prompt_file)):
        parser.error("Supply --email and either --resume-job or --project-id with --prompt-file.")
    client = WebGISImageClient(args.base_url)
    client.login(args.email, os.getenv("WEBGIS_IMAGE_PASSWORD") or getpass.getpass("WebGIS password: "))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    job_id = args.resume_job
    if not job_id:
        caps = client.request("/image-generation/capabilities")
        if not caps["configured"]:
            raise RuntimeError("The server image provider is not configured.")
        if caps["requires_confirmation"] and not args.confirmed:
            raise RuntimeError("This account requires --confirmed for paid image generation.")
        accepted = client.request("/image-generation/jobs", {
            "project_id": args.project_id, "prompt": args.prompt_file.read_text(encoding="utf-8-sig"),
            "title": args.title, "model": args.model, "aspect_ratio": args.aspect_ratio,
            "prompt_optimizer": not args.no_prompt_optimizer, "confirmed": args.confirmed,
        })
        job_id = accepted["job_id"]
    print(f"job_id={job_id}", flush=True)
    safe_job_id = re.sub(r"[^a-zA-Z0-9_-]", "_", job_id)
    manifest_path = args.output_dir / f"{safe_job_id}.json"
    manifest = {"job_id": job_id, "base_url": args.base_url, "status": "submitted"}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    artifact = client.wait(job_id)
    path = client.download(artifact, args.output_dir)
    manifest.update(status="completed", artifact_id=artifact["artifact_id"], path=str(path),
                    model=artifact["metadata"].get("model"), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(path))


if __name__ == "__main__":
    main()
