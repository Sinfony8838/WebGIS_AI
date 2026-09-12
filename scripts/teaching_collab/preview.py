"""Owned preview subprocesses. Never stop or reuse an unknown listening service."""
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
from urllib.request import urlopen
from urllib.parse import urlparse

from .coordinator import Conflict, encoded, git


class Preview:
    def __init__(self, queue):
        self.queue = queue
        self.children = []
        self.sha = None
        self.manifest = queue.root / "preview.json"

    def close(self):
        self.manifest.unlink(missing_ok=True)
        for child, log in self.children:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=8)
            log.close()
        self.children.clear()
        self.sha = None

    def ensure(self, batch):
        config, sha = batch["config"], batch["target_sha"]
        root = Path(config["worktree"])
        if self.sha == sha and self.children and all(p.poll() is None for p, _ in self.children):
            return
        with self.queue.transaction() as con:
            lock = con.execute("SELECT * FROM locks WHERE name='surface' AND expires>?", (self.queue.clock(),)).fetchone()
            if lock:
                return  # Wait for agent to release; never interrupt its browser operation.
            con.execute("INSERT OR REPLACE INTO locks VALUES('surface','preview-manager','preview-manager',?)",
                        (self.queue.clock() + 120,))
        try:
            self.close()
            if git(root, "branch", "--show-current") != config["branch"]:
                raise Conflict("Assigned preview branch changed")
            if git(root, "rev-parse", "HEAD") != sha or git(root, "status", "--porcelain"):
                raise Conflict("Preview requires a clean worktree at the target commit")
            front_port = urlparse(config["preview_url"]).port
            back_port = 19079
            if front_port == back_port:
                raise Conflict("Preview frontend and backend ports must differ")
            for port in (front_port, back_port):
                with socket.socket() as sock:
                    if sock.connect_ex(("127.0.0.1", port)) == 0:
                        raise Conflict(f"Port {port} belongs to an existing service; will not reuse it")
            node = shutil.which("node")
            vite = root / "frontend/node_modules/vite/bin/vite.js"
            if not node or not vite.is_file():
                raise Conflict("Install frontend dependencies in the assigned worktree before preview")
            env = os.environ.copy()
            env.update(WEBGIS_AI_HOST="127.0.0.1", WEBGIS_AI_PORT=str(back_port),
                       WEBGIS_AI_AUTH_MODE="users", WEBGIS_AI_AUTH_DB=str(root / "backend/data/auth/collab.db"),
                       WEBGIS_AI_CORS_ALLOW_ORIGINS=config["preview_url"],
                       VITE_API_BASE_URL=f"http://127.0.0.1:{back_port}", PYTHONIOENCODING="utf-8")
            commands = [(root, [config["python"], "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", str(back_port)]),
                        (root / "frontend", [node, str(vite), "--host", "127.0.0.1", "--port", str(front_port), "--strictPort"])]
            for i, (cwd, command) in enumerate(commands):
                log = (self.queue.root / f"artifacts/preview-{i}.log").open("a", encoding="utf-8")
                child = subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT,
                                         creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                self.children.append((child, log))
            deadline = time.monotonic() + 60
            urls = [config["preview_url"], f"http://127.0.0.1:{back_port}/health"]
            while time.monotonic() < deadline:
                if any(p.poll() is not None for p, _ in self.children):
                    raise Conflict("Owned preview process exited; inspect preview logs")
                try:
                    for url in urls:
                        with urlopen(url, timeout=2) as response:
                            if response.status != 200:
                                raise OSError("Health status is not 200")
                    break
                except OSError:
                    time.sleep(1)
            else:
                raise Conflict("Owned preview health timeout")
            self.sha = sha
            self.manifest.write_text(encoded({"target_sha": sha, "url": config["preview_url"],
                                      "backend": urls[1], "worktree": str(root),
                                      "pids": [p.pid for p, _ in self.children], "started": time.time(),
                                      "auth": "isolated-users"}), encoding="utf-8")
        except Exception:
            self.close()
            raise
        finally:
            with self.queue.transaction() as con:
                con.execute("DELETE FROM locks WHERE name='surface' AND task='preview-manager'")


def prepare_preview(queue, preview):
    status = queue.status()
    running = [b for b in status["batches"] if b["status"] == "running"]
    if not running:
        return
    b = running[-1]
    active = [t for t in status["tasks"] if t["batch"] == b["id"] and t["status"] in ("pending", "leased")]
    if active and active[0]["phase"] in ("discover", "review", "agree", "verify"):
        preview.ensure(b)
