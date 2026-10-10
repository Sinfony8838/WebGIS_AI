"""User-session PowerPoint connector; separate from the web API and data store.

Run on the teacher's Windows computer. Only a native picker can introduce a
path; browsers can neither submit paths nor retrieve file bytes. This module
uses only the standard library and never imports the WebGIS runtime/config.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

SERVICE = "webgis-desktop-powerpoint"
DEFAULT_ORIGINS = ("https://webgisai.com", "https://www.webgisai.com", "http://127.0.0.1:5173", "http://localhost:5173", "http://127.0.0.1:18080", "http://localhost:18080")
WORKER = Path(__file__).resolve().parents[2] / "deploy" / "desktop-powerpoint" / "Open-PowerPoint.ps1"


def native_action(action: str, selected_path: str) -> dict:
    command = [str(Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"),
               "-NoProfile", "-STA", "-File", str(WORKER), "-Action", action]
    if selected_path and action == "focus":
        command += ["-SelectedPath", selected_path]
    # User-visible picker and Office windows are intentional. The worker's
    # console is hidden; it never kills, saves or closes PowerPoint documents.
    result = subprocess.run(command, capture_output=True, encoding="utf-8-sig", errors="replace",
                            timeout=600, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError("PowerPoint 操作失败，请检查本机已安装 PowerPoint，并关闭阻塞操作的 Office 提示框。")
    try:
        return json.loads(result.stdout.strip())
    except (ValueError, TypeError) as exc:
        raise RuntimeError("本机 PowerPoint 未返回有效结果，请检查 Office 窗口。") from exc


class DesktopActions:
    def __init__(self, runner=native_action):
        self.token = secrets.token_urlsafe(32)
        self.runner = runner
        self.lock = threading.Lock()
        self.selected_path = ""
        self.jobs: dict[str, dict] = {}
        self.active = False

    def start(self, action: str) -> str:
        if action not in {"open", "focus"}:
            raise ValueError("只支持打开或切回 PowerPoint。")
        with self.lock:
            if self.active:
                raise RuntimeError("本机文件选择或 PowerPoint 操作尚未结束，请先完成或取消。")
            self.active = True
            self.jobs = {key: job for key, job in self.jobs.items() if time.monotonic() - job["created"] < 900}
            if len(self.jobs) >= 32:
                del self.jobs[next(iter(self.jobs))]
            key = uuid4().hex
            self.jobs[key] = {"created": time.monotonic(), "result": {"status": "pending"}}
        threading.Thread(target=self._run, args=(key, action), daemon=True).start()
        return key

    def _run(self, key: str, action: str):
        try:
            result = self.runner(action, self.selected_path)
            if result.get("status") not in {"opened", "focused", "cancelled", "failed"}:
                raise RuntimeError("本机 PowerPoint 返回了未知状态。")
            path = result.pop("selected_path", "")
            if path and result["status"] in {"opened", "focused"}:
                self.selected_path = path
            # No raw worker errors or local paths are returned to the browser.
            public = {name: result[name] for name in ("status", "file_name", "foreground", "message") if name in result}
        except subprocess.TimeoutExpired:
            public = {"status": "failed", "message": "本机操作等待超时。请检查文件选择框或 Office 提示，确认实际结果后重试。"}
        except Exception:
            public = {"status": "failed", "message": "本机 PowerPoint 操作失败，请检查软件安装与 Office 提示框；课件没有被自动保存或关闭。"}
        finally:
            with self.lock:
                self.jobs[key]["result"] = public
                self.active = False

    def get(self, key: str) -> dict | None:
        with self.lock:
            job = self.jobs.get(key)
            return dict(job["result"]) if job else None


class DesktopServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int, origins: tuple[str, ...], actions: DesktopActions | None = None):
        self.origins = frozenset(origins)
        self.actions = actions or DesktopActions()
        super().__init__(("127.0.0.1", port), DesktopHandler)


class DesktopHandler(BaseHTTPRequestHandler):
    server: DesktopServer

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *_):
        pass  # Never write connector tokens, paths or requests into logs.

    def _allowed(self) -> bool:
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin", "")
        proxy = any(name.lower().startswith(("x-forwarded-", "cf-")) or name.lower() == "forwarded" for name in self.headers)
        return (self.client_address[0] == "127.0.0.1"
                and host == f"127.0.0.1:{self.server.server_port}"
                and origin in self.server.origins and not proxy)

    def _reply(self, status: int, data: dict):
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Vary", "Origin")
        if self._allowed():
            self.send_header("Access-Control-Allow-Origin", self.headers["Origin"])
        self.end_headers()
        self.wfile.write(raw)

    def _guard(self, token: bool = False) -> bool:
        if not self._allowed():
            self._reply(403, {"message": "本机连接器拒绝此来源或代理请求。"})
            return False
        if token and not secrets.compare_digest(self.headers.get("X-WebGIS-Desktop", ""), self.server.actions.token):
            self._reply(403, {"message": "本机连接已失效，请重新打开。"})
            return False
        return True

    def do_OPTIONS(self):
        if not self._guard():
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", self.headers["Origin"])
        self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-WebGIS-Desktop")
        # Older browsers use a private-network preflight; newer ones ask the
        # user for local-network permission. Neither is bypassed here.
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.end_headers()

    def do_GET(self):
        if not self._guard():
            return
        if self.path == "/connection":
            self._reply(200, {"service": SERVICE, "protocol": 1, "token": self.server.actions.token})
        elif self.path.startswith("/actions/"):
            if not self._guard(token=True):
                return
            result = self.server.actions.get(self.path.removeprefix("/actions/"))
            self._reply(200 if result else 404, result or {"message": "本机操作不存在，请重新选择。"})
        else:
            self._reply(404, {"message": "本机接口不存在。"})

    def do_POST(self):
        if not self._guard(token=True):
            return
        if self.path != "/actions":
            self._reply(404, {"message": "本机接口不存在。"}); return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 256 or self.headers.get("Transfer-Encoding") or self.headers.get_content_type() != "application/json":
                raise ValueError()
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict) or set(body) != {"action"} or body["action"] not in {"open", "focus"}:
                raise ValueError()
        except (ValueError, TypeError):
            self._reply(400, {"message": "只接受打开或切回操作，不能提交路径或文件。"}); return
        try:
            key = self.server.actions.start(body["action"])
            self._reply(202, {"action_id": key})
        except RuntimeError as exc:
            self._reply(409, {"message": str(exc)})


def main():
    parser = argparse.ArgumentParser(description="WebGIS teacher-session PowerPoint connector")
    parser.add_argument("--port", type=int, default=18998)
    parser.add_argument("--origin", action="append")
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("PowerPoint connector requires Windows and installed Microsoft PowerPoint")
    origins = tuple(args.origin or DEFAULT_ORIGINS)
    for origin in origins:
        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.path or parsed.query or parsed.fragment:
            parser.error("Origins must be exact HTTP(S) origins without paths, wildcards or credentials")
    with DesktopServer(args.port, origins) as server:
        print(f"PowerPoint connector listening on 127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
