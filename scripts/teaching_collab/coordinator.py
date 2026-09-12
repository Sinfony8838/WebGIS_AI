"""Durable, bounded collaboration. No model APIs and no automatic main merge.

Run `python -m scripts.teaching_collab --help` from the tool worktree.
All client assertions are evidence claims, never proof of human learning.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import secrets
import sqlite3
import subprocess
import time
from contextlib import contextmanager
from urllib.parse import urlparse


class Conflict(ValueError):
    pass


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True,
                                   encoding="utf-8", stderr=subprocess.PIPE).strip()


PHASE_ROLE = {"probe": None, "discover": "teacher", "review": "expert",
              "agree": "teacher", "implement": "expert", "checks": "runner",
              "verify": "teacher", "handoff": "expert"}
ISSUE_FIELDS = ("id", "stage", "steps", "impact", "proposal", "acceptance", "paths")
FULL_FLOW = ("lesson_accept", "eight_stages", "layers_legends", "questions_hints",
             "snapshot", "assistant", "end_class", "report", "viewport_1920",
             "viewport_1366", "globe", "top20", "health")
FORBIDDEN = (".git", ".env", "node_modules", "backend/data", "frontend/dist",
             "scratch", ".claude", ".zcode")


class Coordinator:
    def __init__(self, state_dir, clock=time.time):
        self.root = Path(state_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "artifacts").mkdir(exist_ok=True)
        self.db = self.root / "queue.sqlite3"
        self.clock = clock
        with self.connect() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS batches (
                    id TEXT PRIMARY KEY, status TEXT NOT NULL, config TEXT NOT NULL,
                    target_sha TEXT NOT NULL, round INTEGER NOT NULL DEFAULT 0,
                    reason TEXT NOT NULL DEFAULT '', created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, batch TEXT NOT NULL, phase TEXT NOT NULL,
                    role TEXT NOT NULL, round INTEGER NOT NULL, seq INTEGER NOT NULL,
                    target_sha TEXT NOT NULL, payload TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending', token TEXT,
                    expires REAL, attempts INTEGER NOT NULL DEFAULT 0,
                    result TEXT, UNIQUE(batch, seq));
                CREATE TABLE IF NOT EXISTS locks (
                    name TEXT PRIMARY KEY, task TEXT NOT NULL, token TEXT NOT NULL,
                    expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, batch TEXT, task TEXT, kind TEXT NOT NULL,
                    payload TEXT NOT NULL, at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS failures (
                    batch TEXT NOT NULL, issue TEXT NOT NULL, count INTEGER NOT NULL,
                    PRIMARY KEY(batch, issue));
            """)

    def connect(self):
        con = sqlite3.connect(self.db, timeout=15, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA busy_timeout=15000")
        return con

    @contextmanager
    def transaction(self):
        con = self.connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    def event(self, con, batch, task, kind, value):
        con.execute("INSERT INTO events(batch,task,kind,payload,at) VALUES(?,?,?,?,?)",
                    (batch, task, kind, encoded(value), self.clock()))

    def _enqueue(self, con, batch, phase, payload=None, role=None):
        b = con.execute("SELECT * FROM batches WHERE id=?", (batch,)).fetchone()
        seq = con.execute("SELECT COALESCE(MAX(seq),0)+1 FROM tasks WHERE batch=?",
                          (batch,)).fetchone()[0]
        task = "task_" + secrets.token_hex(8)
        con.execute("INSERT INTO tasks(id,batch,phase,role,round,seq,target_sha,payload) "
                    "VALUES(?,?,?,?,?,?,?,?)", (task, batch, phase, role or PHASE_ROLE[phase],
                    b["round"], seq, b["target_sha"], encoded(payload or {})))
        self.event(con, batch, task, "queued", {"phase": phase})
        return task

    def init(self, worktree, preview_url, allowed_paths, python, npm, rounds=3):
        worktree = Path(worktree).resolve()
        if not 1 <= rounds <= 3:
            raise Conflict("rounds must be between 1 and 3")
        branch = git(worktree, "branch", "--show-current")
        if not branch.startswith("codex/") or branch in ("main", "master"):
            raise Conflict("Use a dedicated codex/ worktree")
        if git(worktree, "status", "--porcelain"):
            raise Conflict("Assigned worktree is dirty; do not overwrite it")
        parsed = urlparse(preview_url)
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port:
            raise Conflict("preview must be an explicit loopback HTTP port")
        if parsed.port in (5173, 18080, 18999):
            raise Conflict("Use isolated preview ports, not known live ports")
        for path in allowed_paths:
            self.validate_path(path)
        sha = git(worktree, "rev-parse", "HEAD")
        config = dict(worktree=str(worktree), preview_url=preview_url,
                      allowed_paths=allowed_paths, python=str(python), npm=str(npm),
                      rounds=rounds, branch=branch, start_sha=sha,
                      lesson="人口分布：上海—中国—世界，40分钟")
        batch = "batch_" + secrets.token_hex(6)
        with self.transaction() as con:
            if con.execute("SELECT 1 FROM batches WHERE status IN ('running','paused')").fetchone():
                raise Conflict("Finish the existing batch before creating another")
            con.execute("INSERT INTO batches(id,status,config,target_sha,created) VALUES(?,?,?,?,?)",
                        (batch, "running", encoded(config), sha, self.clock()))
            self._enqueue(con, batch, "probe", {"step": 1, "challenge": secrets.token_hex(4)}, "teacher")
        return {"batch": batch, "config": config}

    @staticmethod
    def validate_path(path):
        p = Path(path)
        normalized = str(path).replace("\\", "/").rstrip("/")
        if not normalized or p.is_absolute() or normalized.startswith("/") or ":" in normalized or ".." in PurePosixPath(normalized).parts:
            raise Conflict("Unsafe relative path")
        if any(normalized == x or normalized.startswith(x + "/") for x in FORBIDDEN):
            raise Conflict("Runtime/private paths cannot be assigned")
        if any(x.startswith(".env") for x in normalized.split("/")) or normalized.endswith(".tsbuildinfo"):
            raise Conflict("Secret/build paths cannot be assigned")
        return normalized

    def claim(self, role, lease_seconds=900):
        if role not in ("teacher", "expert", "runner") or not 5 <= lease_seconds <= 3600:
            raise Conflict("Invalid role or lease duration")
        with self.transaction() as con:
            con.execute("DELETE FROM locks WHERE expires<=?", (self.clock(),))
            expired = con.execute("SELECT t.* FROM tasks t JOIN batches b ON b.id=t.batch "
                                  "WHERE b.status='running' AND t.status='leased' AND t.expires<=?",
                                  (self.clock(),)).fetchall()
            for task in expired:
                con.execute("UPDATE tasks SET status='pending',token=NULL,expires=NULL WHERE id=?", (task["id"],))
                self.event(con, task["batch"], task["id"], "lease_expired", {})
                if task["attempts"] >= 3:
                    con.execute("UPDATE batches SET status='paused',reason=? WHERE id=?",
                                ("Three expired leases; inspect client availability", task["batch"]))
            task = con.execute("SELECT t.* FROM tasks t JOIN batches b ON b.id=t.batch "
                               "WHERE b.status='running' AND t.status='pending' AND t.role=? "
                               "ORDER BY t.seq LIMIT 1", (role,)).fetchone()
            if not task:
                b = con.execute("SELECT status,reason FROM batches ORDER BY created DESC LIMIT 1").fetchone()
                return {"task": None, "status": b["status"] if b else "empty",
                        "reason": b["reason"] if b else ""}
            token = secrets.token_hex(16)
            con.execute("UPDATE tasks SET status='leased',token=?,expires=?,attempts=attempts+1 WHERE id=?",
                        (token, self.clock() + lease_seconds, task["id"]))
            b = con.execute("SELECT config FROM batches WHERE id=?", (task["batch"],)).fetchone()
            result = dict(task)
            result.update(token=token, expires=self.clock() + lease_seconds,
                          status="leased", attempts=task["attempts"] + 1,
                          payload=json.loads(task["payload"]), config=json.loads(b["config"]))
            result.pop("result")
            self.event(con, task["batch"], task["id"], "claimed", {"role": role})
            return {"task": result, "status": "running"}

    def _leased(self, con, task_id, token):
        task = con.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not task or task["token"] != token or task["status"] != "leased" or task["expires"] <= self.clock():
            raise Conflict("Lease missing, expired or replaced; re-claim and inspect before acting")
        b = con.execute("SELECT * FROM batches WHERE id=?", (task["batch"],)).fetchone()
        if b["status"] != "running":
            raise Conflict("Batch is not running")
        return task, b

    def heartbeat(self, task_id, token, progress):
        with self.transaction() as con:
            task, _ = self._leased(con, task_id, token)
            until = self.clock() + 900
            con.execute("UPDATE tasks SET expires=? WHERE id=?", (until, task_id))
            con.execute("UPDATE locks SET expires=? WHERE task=? AND token=?", (until, task_id, token))
            self.event(con, task["batch"], task_id, "progress", progress)
        return {"expires": until}

    def surface(self, task_id, token, release=False):
        """One lock for all browsers and preview restart, across roles."""
        with self.transaction() as con:
            task, _ = self._leased(con, task_id, token)
            if release:
                con.execute("DELETE FROM locks WHERE name='surface' AND task=? AND token=?", (task_id, token))
                return {"released": True}
            con.execute("DELETE FROM locks WHERE expires<=?", (self.clock(),))
            lock = con.execute("SELECT * FROM locks WHERE name='surface'").fetchone()
            if lock and (lock["task"], lock["token"]) != (task_id, token):
                raise Conflict("Browser/preview surface is occupied")
            con.execute("INSERT OR REPLACE INTO locks VALUES('surface',?,?,?)", (task_id, token, task["expires"]))
            return {"acquired": True, "expires": task["expires"]}

    def probe_click(self, task_id, token):
        with self.transaction() as con:
            task, _ = self._leased(con, task_id, token)
            if task["phase"] != "probe":
                raise Conflict("Not a probe")
            lock = con.execute("SELECT * FROM locks WHERE name='surface' AND task=? AND token=? AND expires>?",
                               (task_id, token, self.clock())).fetchone()
            if not lock:
                raise Conflict("Acquire the surface before browser interaction")
            challenge = json.loads(task["payload"])["challenge"]
            self.event(con, task["batch"], task_id, "probe_click", {"challenge": challenge})
            return {"observed": challenge, "message": "已点击；此页只验证连接，不代表课堂验收"}

    def artifact(self, relative, image=False):
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root / "artifacts") or not path.is_file() or path.stat().st_size == 0:
            raise Conflict("Evidence must be a nonempty file under state/artifacts")
        content = path.read_bytes()
        if image and not (content.startswith(b"\x89PNG\r\n\x1a\n") or content.startswith(b"\xff\xd8\xff")):
            raise Conflict("Screenshot must be PNG or JPEG")
        return {"path": relative, "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}

    def _issues(self, issues, config):
        if not isinstance(issues, list) or len(issues) > 3:
            raise Conflict("At most three issues per round")
        ids = set()
        for issue in issues:
            if not isinstance(issue, dict) or any(not issue.get(k) for k in ISSUE_FIELDS):
                raise Conflict("Each issue requires id/stage/steps/impact/proposal/acceptance/paths")
            if issue["id"] in ids:
                raise Conflict("Duplicate issue id")
            ids.add(issue["id"])
            if not isinstance(issue["paths"], list):
                raise Conflict("Issue paths must be a list")
            for path in issue["paths"]:
                path = self.validate_path(path)
                if not any(path == x.rstrip("/") or (x.endswith("/") and path.startswith(x))
                           for x in config["allowed_paths"]):
                    raise Conflict("Issue path not delegated: " + path)

    def submit(self, task_id, token, result):
        with self.transaction() as con:
            old = con.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if old and old["status"] == "done" and old["token"] == token:
                if json.loads(old["result"])["submitted"] != result:
                    raise Conflict("Completed result is immutable")
                return {"accepted": True, "duplicate": True}
            task, batch = self._leased(con, task_id, token)
            config = json.loads(batch["config"])
            payload = json.loads(task["payload"])
            if git(config["worktree"], "branch", "--show-current") != config["branch"]:
                raise Conflict("Assigned branch changed; do not submit from another branch")
            if result.get("target_sha") != task["target_sha"]:
                raise Conflict("Stale target SHA")
            if not result.get("summary") or not result.get("next_step"):
                raise Conflict("summary and next_step are required")
            artifacts = [self.artifact(x) for x in result.get("evidence", [])]
            phase = task["phase"]
            if phase != "implement" and git(config["worktree"], "rev-parse", "HEAD") != task["target_sha"]:
                raise Conflict("Preview worktree moved; results are stale")
            if phase != "implement" and git(config["worktree"], "status", "--porcelain"):
                raise Conflict("Worktree is dirty; cannot attribute evidence to committed version")
            if phase == "probe":
                clicks = con.execute("SELECT 1 FROM events WHERE task=? AND kind='probe_click'", (task_id,)).fetchone()
                if not clicks or result.get("observed") != payload["challenge"]:
                    raise Conflict("Probe requires browser click and observed challenge")
                artifacts.append(self.artifact(result.get("screenshot", ""), image=True))
                if result.get("client") != {"teacher": "MiMo Desktop", "expert": "ZCode"}[task["role"]]:
                    raise Conflict("Report the actual client identity")
                if result.get("screenshot_read") is not True:
                    raise Conflict("Client must read its screenshot")
            elif phase == "discover":
                self._issues(result.get("issues"), config)
                self._browser_result(result, task, artifacts, complete_flow=True)
            elif phase == "review":
                self._issues(result.get("issues"), config)
                if not {x["id"] for x in result["issues"]}.issubset({x["id"] for x in payload["issues"]}):
                    raise Conflict("Review must retain existing issue identities")
                if result.get("verdict") not in ("accept", "revise", "defer"):
                    raise Conflict("Review verdict must be accept, revise or defer")
                if not artifacts:
                    raise Conflict("Review needs independent reproduction or source evidence")
            elif phase == "agree":
                if not isinstance(result.get("accepted"), bool):
                    raise Conflict("Teacher must explicitly accept or reject reviewed issues")
            elif phase == "implement":
                new_sha = result.get("new_sha", "")
                if new_sha != git(config["worktree"], "rev-parse", "HEAD") or new_sha == task["target_sha"]:
                    raise Conflict("Implementation requires a new committed HEAD")
                git(config["worktree"], "merge-base", "--is-ancestor", task["target_sha"], new_sha)
                if git(config["worktree"], "status", "--porcelain"):
                    raise Conflict("Review and commit explicit scoped paths first; worktree is dirty")
                changed = git(config["worktree"], "diff", "--name-only", task["target_sha"], new_sha).splitlines()
                allowed = {p for issue in payload["issues"] for p in issue["paths"]}
                if not changed or any(p not in allowed for p in changed):
                    raise Conflict("Commit changes files outside agreed task ownership")
                con.execute("UPDATE batches SET target_sha=? WHERE id=?", (new_sha, task["batch"]))
            elif phase == "checks":
                if result.get("runner") != "local-subprocess" or not isinstance(result.get("passed"), bool):
                    raise Conflict("Checks require coordinator subprocess results")
            elif phase == "verify":
                self._browser_result(result, task, artifacts, complete_flow=True)
                expected = {x["id"] for x in payload["issues"]}
                if set(result.get("outcomes", {})) != expected or any(
                    x not in ("improved", "unchanged", "regressed") for x in result["outcomes"].values()
                ):
                    raise Conflict("Report every agreed issue as improved/unchanged/regressed")
            elif phase == "handoff":
                if not artifacts or not result.get("commit") or not result.get("pr_status"):
                    raise Conflict("Handoff needs report artifact, commit and PR status")
            wrapped = {"submitted": result, "artifacts": artifacts}
            con.execute("UPDATE tasks SET status='done',result=? WHERE id=?", (encoded(wrapped), task_id))
            con.execute("DELETE FROM locks WHERE task=?", (task_id,))
            self.event(con, task["batch"], task_id, "completed", {"phase": phase})
            self._advance(con, task, batch, payload, result)
        return {"accepted": True, "duplicate": False}

    def _browser_result(self, result, task, artifacts, complete_flow=False):
        if result.get("preview_sha") != task["target_sha"]:
            raise Conflict("Browser evidence must name the tested preview SHA")
        manifest = self.root / "preview.json"
        if not manifest.is_file() or json.loads(manifest.read_text(encoding="utf-8"))["target_sha"] != task["target_sha"]:
            raise Conflict("Owned preview has not started at this commit")
        artifacts.append(self.artifact(result.get("screenshot", ""), image=True))
        artifacts.append(self.artifact(result.get("flow_evidence", "")))
        checks = result.get("flow_checks", {})
        if complete_flow and (set(checks) != set(FULL_FLOW) or any(
            x not in ("pass", "fail", "blocked") for x in checks.values()
        )):
            raise Conflict("Report all classroom and viewport checks; never fill missing evidence as pass")

    def _advance(self, con, task, batch, payload, result):
        bid, phase = task["batch"], task["phase"]
        if phase == "probe":
            step = payload["step"]
            if step < 6:
                self._enqueue(con, bid, "probe", {"step": step + 1, "challenge": secrets.token_hex(4),
                              "previous": result}, "expert" if step % 2 else "teacher")
            else:
                con.execute("UPDATE batches SET round=1 WHERE id=?", (bid,))
                self._enqueue(con, bid, "discover", {"focus": "完整课堂基线；连接探针已完成，尚无课堂验收"})
        elif phase == "discover":
            if not result["issues"]:
                if any(x != "pass" for x in result["flow_checks"].values()):
                    self._pause(con, bid, "Incomplete classroom evidence; inspect baseline blockers")
                    self._enqueue(con, bid, "discover", {"previous": result})
                else:
                    self._finish(con, bid, "No actionable issues", result)
            else:
                self._enqueue(con, bid, "review", {"issues": result["issues"], "teacher": result, "discussion": 1})
        elif phase == "review":
            self._enqueue(con, bid, "agree", {**payload, "issues": result["issues"], "review": result})
        elif phase == "agree":
            if result["accepted"] and payload["review"]["verdict"] == "accept" and payload["issues"]:
                self._enqueue(con, bid, "implement", payload)
            elif payload["discussion"] < 2 and payload["review"]["verdict"] != "defer":
                self._enqueue(con, bid, "review", {**payload, "discussion": 2, "teacher_reply": result})
            else:
                self.event(con, bid, task["id"], "deferred", payload["issues"])
                self._next_round(con, bid, {"deferred": payload["issues"]})
        elif phase == "implement":
            self._enqueue(con, bid, "checks", {**payload, "implementation": result})
        elif phase == "checks":
            if result["passed"]:
                self._enqueue(con, bid, "verify", {**payload, "checks": result})
            else:
                self._pause(con, bid, "Regression checks failed; inspect logs before resuming")
                self._enqueue(con, bid, "implement", {**payload, "checks": result})
        elif phase == "verify":
            unchanged = []
            for issue, outcome in result["outcomes"].items():
                con.execute("INSERT INTO failures VALUES(?,?,?) ON CONFLICT(batch,issue) "
                            "DO UPDATE SET count=excluded.count", (bid, issue,
                            0 if outcome == "improved" else 1 + (con.execute(
                                "SELECT count FROM failures WHERE batch=? AND issue=?", (bid, issue)
                            ).fetchone() or [0])[0]))
                count = con.execute("SELECT count FROM failures WHERE batch=? AND issue=?", (bid, issue)).fetchone()[0]
                if count >= 2:
                    self._finish(con, bid, "Two unsuccessful fixes for " + issue, result)
                    return
                if outcome != "improved":
                    unchanged.append(issue)
            if unchanged:
                self._enqueue(con, bid, "review", {"issues": [x for x in payload["issues"] if x["id"] in unchanged],
                              "discussion": 1, "teacher": result})
            else:
                if any(x != "pass" for x in result["flow_checks"].values()):
                    self._pause(con, bid, "Full classroom verification still has failed/blocked checks")
                    self._enqueue(con, bid, "discover", {"previous": result})
                else:
                    self._next_round(con, bid, {"verification": result})
        elif phase == "handoff":
            con.execute("UPDATE batches SET status='complete' WHERE id=?", (bid,))

    def _next_round(self, con, bid, payload):
        b = con.execute("SELECT * FROM batches WHERE id=?", (bid,)).fetchone()
        if b["round"] >= json.loads(b["config"])["rounds"]:
            self._finish(con, bid, "Round limit reached", payload)
        else:
            con.execute("UPDATE batches SET round=round+1 WHERE id=?", (bid,))
            self._enqueue(con, bid, "discover", payload)

    def _finish(self, con, bid, reason, payload):
        con.execute("UPDATE batches SET reason=? WHERE id=?", (reason, bid))
        self._enqueue(con, bid, "handoff", {"reason": reason, "last_result": payload})

    def _pause(self, con, bid, reason):
        con.execute("UPDATE batches SET status='paused',reason=? WHERE id=?", (reason, bid))

    def pause(self, batch, reason):
        if not reason.strip():
            raise Conflict("Pause reason required")
        with self.transaction() as con:
            b = con.execute("SELECT * FROM batches WHERE id=?", (batch,)).fetchone()
            if not b or b["status"] == "complete":
                raise Conflict("No active batch")
            self._pause(con, batch, reason)
            con.execute("UPDATE tasks SET status='pending',token=NULL,expires=NULL WHERE batch=? AND status='leased'", (batch,))
            con.execute("DELETE FROM locks WHERE task IN (SELECT id FROM tasks WHERE batch=?)", (batch,))
            self.event(con, batch, None, "paused", reason)
        return {"status": "paused", "reason": reason}

    def resume(self, batch):
        with self.transaction() as con:
            b = con.execute("SELECT * FROM batches WHERE id=?", (batch,)).fetchone()
            if not b or b["status"] != "paused":
                raise Conflict("Only a paused batch can resume")
            config = json.loads(b["config"])
            if git(config["worktree"], "rev-parse", "HEAD") != b["target_sha"]:
                raise Conflict("Worktree changed; reconcile before resume")
            pending = con.execute("SELECT phase FROM tasks WHERE batch=? AND status='pending' ORDER BY seq LIMIT 1", (batch,)).fetchone()
            if pending and pending["phase"] != "implement" and git(config["worktree"], "status", "--porcelain"):
                raise Conflict("Worktree is dirty; review unrelated changes before resume")
            con.execute("UPDATE batches SET status='running',reason='' WHERE id=?", (batch,))
            self.event(con, batch, None, "resumed", {})
        return {"status": "running"}

    def status(self):
        with self.connect() as con:
            batches = [dict(x) for x in con.execute("SELECT * FROM batches ORDER BY created")]
            tasks = [dict(x) for x in con.execute("SELECT id,batch,phase,role,round,seq,target_sha,status,expires,attempts,result FROM tasks ORDER BY seq")]
            events = [dict(x) for x in con.execute("SELECT * FROM events ORDER BY id")]
        for b in batches:
            b["config"] = json.loads(b["config"])
        for t in tasks:
            t["result"] = json.loads(t["result"]) if t["result"] else None
        return {"batches": batches, "tasks": tasks, "events": events}

    def run_checks(self):
        task = self.claim("runner", lease_seconds=3600)["task"]
        if not task:
            return None
        config = task["config"]
        root = Path(config["worktree"])
        commands = [(root, [config["python"], "-m", "pytest", "backend/tests", "-q"]),
                    (root / "frontend", [config["npm"], "test"]),
                    (root / "frontend", [config["npm"], "run", "build"]),
                    (root, ["git", "diff", "--check"])]
        evidence, outcomes = [], []
        try:
            for index, (cwd, command) in enumerate(commands):
                name = f"artifacts/{task['id']}-check-{index}.log"
                with (self.root / name).open("w", encoding="utf-8") as log:
                    log.write(encoded({"cwd": str(cwd), "argv": command, "sha": task["target_sha"]}) + "\n")
                    log.flush()
                    try:
                        completed = subprocess.run(command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, timeout=600)
                        code = completed.returncode
                    except (OSError, subprocess.TimeoutExpired) as exc:
                        log.write(str(exc))
                        code = -1
                evidence.append(name)
                outcomes.append({"argv": command, "exit_code": code})
                self.heartbeat(task["id"], task["token"], outcomes[-1])
            result = dict(target_sha=task["target_sha"], summary="Local regression subprocess results",
                          next_step="Teacher browser verification" if all(x["exit_code"] == 0 for x in outcomes) else "Inspect failed checks",
                          runner="local-subprocess", passed=all(x["exit_code"] == 0 for x in outcomes),
                          commands=outcomes, evidence=evidence)
            return self.submit(task["id"], task["token"], result)
        except Exception as exc:
            self.pause(task["batch"], "Check runner interrupted: " + str(exc))
            raise
