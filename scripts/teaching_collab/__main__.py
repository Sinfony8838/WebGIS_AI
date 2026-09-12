"""CLI and loopback probe page for the teaching collaboration queue."""
import argparse
import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import threading
import time
from urllib.parse import parse_qs, urlparse

from .coordinator import Conflict, Coordinator, encoded
from .preview import Preview, prepare_preview


def serve(queue, port):
    preview = Preview(queue)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass  # Probe URLs contain short-lived leases; do not log them.

        def reply(self, data, status=200, content_type="application/json; charset=utf-8"):
            body = data.encode("utf-8") if isinstance(data, str) else encoded(data).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/status":
                data = queue.status()
                # Public dashboard only exposes progress, not payloads/paths or lease tokens.
                return self.reply({"batches": [{k: b[k] for k in ("id", "status", "round", "reason")} for b in data["batches"]],
                                   "tasks": [{k: t[k] for k in ("id", "phase", "role", "status")} for t in data["tasks"]]})
            if parsed.path == "/preview":
                if not preview.manifest.is_file():
                    return self.reply({"ready": False}, 503)
                return self.reply(json.loads(preview.manifest.read_text(encoding="utf-8")))
            if parsed.path == "/":
                return self.reply('''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>课堂协作运行状态</title><style>body{font:18px system-ui;margin:40px;max-width:1000px}pre{white-space:pre-wrap}</style>
<h1>MiMo × ZCode 课堂协作</h1><p>这里只显示队列状态。连接探针不代表课堂验收。</p><pre id="state"></pre>
<script>async function refresh(){document.getElementById('state').textContent=JSON.stringify(await(await fetch('/status')).json(),null,2)}refresh();setInterval(refresh,5000)</script></html>''', content_type="text/html; charset=utf-8")
            if parsed.path.startswith("/probe/"):
                task_id = parsed.path.rsplit("/", 1)[-1]
                token = parse_qs(parsed.query).get("lease", [""])[0]
                try:
                    with queue.transaction() as con:
                        task, _ = queue._leased(con, task_id, token)
                        if task["phase"] != "probe":
                            raise Conflict("Not a probe task")
                    body = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>课堂协作连接探针</title>
<style>body{font:24px system-ui;margin:60px;background:#f5f7fb;color:#172b4d}button{font:inherit;padding:20px;background:#245bc3;color:white;border:0;border-radius:8px}pre{white-space:pre-wrap}</style>
<h1>课堂协作：连接探针</h1><p>任务：TASK</p><p>请实际点击按钮，然后截图并读取结果。</p>
<button id="probe">验证网页操作</button><pre id="result">尚未点击</pre>
<p>本页是连接测试，未运行真实课堂，也未采集学生数据。</p>
<script>document.getElementById('probe').onclick=async()=>{let r=await fetch('/probe-click',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(PAYLOAD)});document.getElementById('result').textContent=JSON.stringify(await r.json(),null,2)}</script></html>'''
                    body = body.replace("TASK", html.escape(task_id)).replace("PAYLOAD", encoded({"task_id": task_id, "token": token}))
                    return self.reply(body, content_type="text/html; charset=utf-8")
                except Conflict as exc:
                    return self.reply({"error": str(exc)}, 409)
            return self.reply({"error": "not found"}, 404)

        def do_POST(self):
            if self.path != "/probe-click":
                return self.reply({"error": "not found"}, 404)
            if self.headers.get("Origin") != f"http://127.0.0.1:{port}":
                return self.reply({"error": "Probe must originate in its local page"}, 403)
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size < 4096 or self.headers.get("Content-Type") != "application/json":
                    raise ValueError("invalid request")
                value = json.loads(self.rfile.read(size))
                result = queue.probe_click(value["task_id"], value["token"])
                return self.reply(result)
            except (Conflict, ValueError, KeyError) as exc:
                return self.reply({"error": str(exc)}, 409)

    stop = threading.Event()

    def checks_loop():
        while not stop.wait(2):
            try:
                prepare_preview(queue, preview)
                queue.run_checks()
            except Exception as exc:
                print(encoded({"check_runner_error": str(exc)}), flush=True)
                for batch in queue.status()["batches"]:
                    if batch["status"] == "running":
                        queue.pause(batch["id"], "Local service unavailable: " + str(exc))

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    worker = threading.Thread(target=checks_loop, daemon=True)
    worker.start()
    print(encoded({"url": f"http://127.0.0.1:{port}", "state": str(queue.root)}), flush=True)
    try:
        server.serve_forever()
    finally:
        stop.set()
        server.server_close()
        preview.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True, help="Absolute shared runtime directory; never commit it")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--worktree", required=True)
    init.add_argument("--preview", required=True)
    init.add_argument("--allow-path", action="append", default=[])
    init.add_argument("--python", default=sys.executable)
    init.add_argument("--npm", default="npm.cmd" if sys.platform == "win32" else "npm")
    init.add_argument("--rounds", type=int, default=3)
    claim = sub.add_parser("claim")
    claim.add_argument("--role", choices=("teacher", "expert"), required=True)
    claim.add_argument("--wait", type=int, default=45)
    claim.add_argument("--lease-seconds", type=int, default=900)
    claim.add_argument("--out", help="Optional runtime JSON file to remember lease after context compression")
    for command in ("submit", "heartbeat", "surface"):
        p = sub.add_parser(command)
        p.add_argument("--task", required=True)
        p.add_argument("--token", required=True)
        if command == "submit":
            p.add_argument("--result", required=True, help="UTF-8 JSON file")
        if command == "heartbeat":
            p.add_argument("--progress", required=True)
        if command == "surface":
            p.add_argument("--release", action="store_true")
    for command in ("pause", "resume"):
        p = sub.add_parser(command)
        p.add_argument("--batch", required=True)
        if command == "pause":
            p.add_argument("--reason", required=True)
    sub.add_parser("status")
    report = sub.add_parser("report")
    report.add_argument("--out", required=True)
    server = sub.add_parser("serve")
    server.add_argument("--port", type=int, default=18765)
    args = parser.parse_args(argv)
    queue = Coordinator(args.state)
    try:
        if args.command == "init":
            result = queue.init(args.worktree, args.preview, args.allow_path, args.python, args.npm, args.rounds)
        elif args.command == "claim":
            if not 0 <= args.wait <= 45:
                raise Conflict("wait must be 0..45 seconds")
            output = Path(args.out).resolve() if args.out else None
            if output and not output.is_relative_to(queue.root):
                raise Conflict("Lease output must remain inside runtime directory")
            deadline = time.monotonic() + args.wait
            while True:
                result = queue.claim(args.role, args.lease_seconds)
                if result["task"] or result["status"] != "running" or time.monotonic() >= deadline:
                    break
                time.sleep(min(1, max(0, deadline - time.monotonic())))
            if args.out:
                output.write_text(encoded(result), encoding="utf-8")
        elif args.command == "submit":
            value = json.loads(Path(args.result).read_text(encoding="utf-8-sig"))
            result = queue.submit(args.task, args.token, value)
        elif args.command == "heartbeat":
            result = queue.heartbeat(args.task, args.token, args.progress)
        elif args.command == "surface":
            result = queue.surface(args.task, args.token, args.release)
        elif args.command == "pause":
            result = queue.pause(args.batch, args.reason)
        elif args.command == "resume":
            result = queue.resume(args.batch)
        elif args.command == "status":
            result = queue.status()
        elif args.command == "report":
            value = queue.status()
            report = ["# 课堂协作批次记录", "", "连接探针、自动回归、AI试讲和真人课堂效果分别记录。", ""]
            for batch in value["batches"]:
                report.extend([f"## {batch['id']}", f"状态：{batch['status']}；轮次：{batch['round']}；原因：{batch['reason']}",
                               f"起点：{batch['config']['start_sha']}；当前提交：{batch['target_sha']}", ""])
            for task in value["tasks"]:
                report.extend([f"### {task['seq']}. {task['role']} / {task['phase']} / {task['status']}",
                               f"任务：{task['id']}；目标：{task['target_sha']}",
                               "```json", json.dumps(task["result"], ensure_ascii=False, indent=2), "```", ""])
            Path(args.out).write_text("\n".join(report), encoding="utf-8")
            result = {"report": str(Path(args.out).resolve())}
        else:
            serve(queue, args.port)
            return 0
        print(encoded(result))
        return 0
    except (Conflict, ValueError, OSError) as exc:
        print(encoded({"error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
