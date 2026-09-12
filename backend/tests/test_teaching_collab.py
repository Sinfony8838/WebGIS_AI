"""Coordinator fault tests. Synthetic probes do NOT qualify as client acceptance."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.teaching_collab import coordinator as module
from scripts.teaching_collab.coordinator import Conflict, Coordinator, FULL_FLOW


SHA = "a" * 40
NEXT = "b" * 40


@pytest.fixture
def q(tmp_path, monkeypatch):
    now = [1000.0]
    head = [SHA]

    def fake_git(root, *args):
        if args == ("branch", "--show-current"):
            return "codex/test"
        if args == ("rev-parse", "HEAD"):
            return head[0]
        if args[:2] == ("diff", "--name-only"):
            return "frontend/src/lesson-workflow.css"
        return ""

    monkeypatch.setattr(module, "git", fake_git)
    c = Coordinator(tmp_path / "state", clock=lambda: now[0])
    c.init(tmp_path / "worktree", "http://127.0.0.1:5197", ["frontend/src/lesson-workflow.css"], sys.executable, "npm")
    # Deliberately synthetic signatures only; no browser/platform claim is made.
    (c.root / "artifacts/probe.png").write_bytes(b"\x89PNG\r\n\x1a\nUNIT TEST FIXTURE")
    (c.root / "artifacts/flow.md").write_text("Synthetic flow evidence", encoding="utf-8")
    c.now, c.head = now, head
    return c


def basic(task):
    return dict(target_sha=task["target_sha"], summary="unit test", next_step="unit test next")


def finish_probe(q, task):
    q.surface(task["id"], task["token"])
    clicked = q.probe_click(task["id"], task["token"])
    value = dict(**basic(task), client="MiMo Desktop" if task["role"] == "teacher" else "ZCode",
                 observed=clicked["observed"], screenshot="artifacts/probe.png", screenshot_read=True)
    q.submit(task["id"], task["token"], value)
    return value


def pass_gate(q):
    for role in ["teacher", "expert"] * 3:
        finish_probe(q, q.claim(role)["task"])


def issue():
    return dict(id="population-hint-1", stage="中国绘线", steps=["打开提示"], impact="答案提前出现",
                proposal="分级提示", acceptance="首次只显示观察问题", paths=["frontend/src/lesson-workflow.css"])


def flow(q, task):
    (q.root / "preview.json").write_text(json.dumps({"target_sha": task["target_sha"]}), encoding="utf-8")
    return dict(**basic(task), preview_sha=task["target_sha"], screenshot="artifacts/probe.png",
                flow_evidence="artifacts/flow.md", flow_checks={k: "pass" for k in FULL_FLOW})


def finish_discovery(q, issues=None):
    task = q.claim("teacher")["task"]
    assert task["phase"] == "discover"
    q.submit(task["id"], task["token"], dict(**flow(q, task), issues=[issue()] if issues is None else issues))


def agree(q):
    task = q.claim("expert")["task"]
    assert task["phase"] == "review"
    q.submit(task["id"], task["token"], dict(**basic(task), verdict="accept", issues=[issue()], evidence=["artifacts/flow.md"]))
    task = q.claim("teacher")["task"]
    assert task["phase"] == "agree"
    q.submit(task["id"], task["token"], dict(**basic(task), accepted=True))


def test_competing_claimers_get_one_lease(q):
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda _: q.claim("teacher"), range(8)))
    assert sum(x["task"] is not None for x in results) == 1
    assert q.claim("expert")["task"] is None


def test_expiry_restarts_same_task_and_rejects_old_worker(q):
    first = q.claim("teacher", lease_seconds=5)["task"]
    q.now[0] += 6
    replacement = q.claim("teacher")["task"]
    assert first["id"] == replacement["id"]
    assert first["token"] != replacement["token"]
    with pytest.raises(Conflict, match="Lease"):
        q.submit(first["id"], first["token"], basic(first))
    finish_probe(q, replacement)


def test_repeated_crashes_pause_batch(q):
    for _ in range(3):
        assert q.claim("teacher", lease_seconds=5)["task"]
        q.now[0] += 6
    state = q.claim("teacher")
    assert state["task"] is None and state["status"] == "paused"


def test_replay_is_idempotent_and_different_result_rejected(q):
    task = q.claim("teacher")["task"]
    result = finish_probe(q, task)
    assert q.submit(task["id"], task["token"], result)["duplicate"]
    assert len(q.status()["tasks"]) == 2
    with pytest.raises(Conflict, match="immutable"):
        q.submit(task["id"], task["token"], {**result, "summary": "changed"})


def test_pause_invalidates_leases_and_resume_preserves_task(q):
    task = q.claim("teacher")["task"]
    q.surface(task["id"], task["token"])
    q.pause(task["batch"], "Client login expired")
    assert q.claim("teacher")["status"] == "paused"
    with pytest.raises(Conflict):
        q.heartbeat(task["id"], task["token"], "late")
    q.resume(task["batch"])
    fresh = q.claim("teacher")["task"]
    assert fresh["id"] == task["id"] and fresh["token"] != task["token"]


def test_preview_manager_and_browser_exclude_each_other(q):
    task = q.claim("teacher")["task"]
    with q.transaction() as con:
        con.execute("INSERT INTO locks VALUES('surface','preview-manager','manager',?)", (q.now[0] + 10,))
    with pytest.raises(Conflict, match="occupied"):
        q.surface(task["id"], task["token"])
    q.now[0] += 11
    assert q.surface(task["id"], task["token"])["acquired"]
    q.heartbeat(task["id"], task["token"], "reading page")
    with q.connect() as con:
        assert con.execute("SELECT expires FROM locks").fetchone()[0] == q.now[0] + 900


def test_cannot_claim_classroom_before_six_probes(q):
    for i, role in enumerate(["teacher", "expert"] * 3):
        task = q.claim(role)["task"]
        assert task["phase"] == "probe" and task["payload"]["step"] == i + 1
        finish_probe(q, task)
    assert q.claim("teacher")["task"]["phase"] == "discover"


def test_probe_requires_click_screenshot_and_identity(q):
    task = q.claim("teacher")["task"]
    with pytest.raises(Conflict, match="click"):
        q.submit(task["id"], task["token"], basic(task))
    with pytest.raises(Conflict, match="surface"):
        q.probe_click(task["id"], task["token"])


@pytest.mark.parametrize("path", ["../secret", "..\\secret", ".env", "backend/data/state/x", "C:/secret", "frontend/.env.local", ".git/config"])
def test_forbidden_paths(path):
    with pytest.raises(Conflict):
        Coordinator.validate_path(path)


def test_artifact_traversal_and_wrong_format(q):
    with pytest.raises(Conflict):
        q.artifact("../secret")
    with pytest.raises(Conflict, match="PNG"):
        q.artifact("artifacts/flow.md", image=True)


def test_stale_commit_cannot_advance_queue(q):
    task = q.claim("teacher")["task"]
    q.head[0] = NEXT
    with pytest.raises(Conflict, match="stale"):
        q.submit(task["id"], task["token"], basic(task))
    assert len(q.status()["tasks"]) == 1


def test_classroom_requires_owned_preview(q):
    pass_gate(q)
    task = q.claim("teacher")["task"]
    data = flow(q, task)
    (q.root / "preview.json").unlink()
    with pytest.raises(Conflict, match="Owned preview"):
        q.submit(task["id"], task["token"], dict(**data, issues=[issue()]))


def test_issue_limit_and_scope(q):
    pass_gate(q)
    task = q.claim("teacher")["task"]
    data = flow(q, task)
    with pytest.raises(Conflict, match="three"):
        q.submit(task["id"], task["token"], dict(**data, issues=[issue()] * 4))
    with pytest.raises(Conflict, match="delegated"):
        q.submit(task["id"], task["token"], dict(**data, issues=[{**issue(), "paths": ["frontend/src/App.tsx"]}]))


def test_full_fix_and_teacher_verification(q):
    pass_gate(q)
    finish_discovery(q)
    agree(q)
    task = q.claim("expert")["task"]
    assert task["phase"] == "implement"
    q.head[0] = NEXT
    q.submit(task["id"], task["token"], dict(**basic(task), new_sha=NEXT))
    assert q.claim("teacher")["task"] is None  # tests precede teacher acceptance
    checks = q.claim("runner")["task"]
    q.submit(checks["id"], checks["token"], dict(**basic(checks), runner="local-subprocess", passed=True))
    verify = q.claim("teacher")["task"]
    assert verify["phase"] == "verify" and verify["target_sha"] == NEXT
    q.submit(verify["id"], verify["token"], dict(**flow(q, verify), outcomes={issue()["id"]: "improved"}))
    assert q.status()["batches"][0]["round"] == 2


def test_two_discussion_exchanges_defer_without_edit(q):
    pass_gate(q)
    finish_discovery(q)
    for discussion in (1, 2):
        task = q.claim("expert")["task"]
        assert task["phase"] == "review" and task["payload"]["discussion"] == discussion
        q.submit(task["id"], task["token"], dict(**basic(task), verdict="revise", issues=[issue()], evidence=["artifacts/flow.md"]))
        task = q.claim("teacher")["task"]
        q.submit(task["id"], task["token"], dict(**basic(task), accepted=False))
    assert q.claim("teacher")["task"]["phase"] == "discover"
    assert all(t["phase"] != "implement" for t in q.status()["tasks"])


def test_blocked_flow_with_no_issues_does_not_pass(q):
    pass_gate(q)
    task = q.claim("teacher")["task"]
    value = flow(q, task)
    value["flow_checks"]["report"] = "blocked"
    q.submit(task["id"], task["token"], dict(**value, issues=[]))
    assert q.status()["batches"][0]["status"] == "paused"


def test_three_round_limit(q):
    pass_gate(q)
    for _ in range(3):
        finish_discovery(q)
        task = q.claim("expert")["task"]
        q.submit(task["id"], task["token"], dict(**basic(task), verdict="defer", issues=[issue()], evidence=["artifacts/flow.md"]))
        task = q.claim("teacher")["task"]
        q.submit(task["id"], task["token"], dict(**basic(task), accepted=False))
    task = q.claim("expert")["task"]
    assert task["phase"] == "handoff"
    assert q.status()["batches"][0]["round"] == 3


def test_real_git_init_rejects_dirty_worktree(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    def run(*args):
        return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    run("init", "-b", "codex/test")
    run("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-m", "fixture")
    c = Coordinator(tmp_path / "runtime")
    (root / "dirty.txt").write_text("untracked")
    with pytest.raises(Conflict, match="dirty"):
        c.init(root, "http://127.0.0.1:5197", [], sys.executable, "npm")


def test_failed_checks_pause_and_keep_committed_state(q, monkeypatch):
    pass_gate(q)
    finish_discovery(q)
    agree(q)
    t = q.claim("expert")["task"]
    q.head[0] = NEXT
    q.submit(t["id"], t["token"], dict(**basic(t), new_sha=NEXT))
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: subprocess.CompletedProcess([], 1))
    q.run_checks()
    assert q.status()["batches"][0]["status"] == "paused"
    assert q.status()["batches"][0]["target_sha"] == NEXT


def test_two_unsuccessful_fixes_stop_with_reason(q):
    pass_gate(q)
    finish_discovery(q)
    for sha in (NEXT, "c" * 40):
        agree(q)
        task = q.claim("expert")["task"]
        q.head[0] = sha
        q.submit(task["id"], task["token"], dict(**basic(task), new_sha=sha))
        task = q.claim("runner")["task"]
        q.submit(task["id"], task["token"], dict(**basic(task), runner="local-subprocess", passed=True))
        task = q.claim("teacher")["task"]
        q.submit(task["id"], task["token"], dict(**flow(q, task), outcomes={issue()["id"]: "unchanged"}))
    assert q.claim("expert")["task"]["phase"] == "handoff"
    assert "Two unsuccessful" in q.status()["batches"][0]["reason"]


def test_restart_reads_existing_queue_without_duplicate(q):
    task = q.claim("teacher")["task"]
    resumed = Coordinator(q.root, clock=lambda: q.now[0])
    assert resumed.claim("teacher")["task"] is None
    result = finish_probe(resumed, task)
    assert resumed.submit(task["id"], task["token"], result)["duplicate"]
    assert q.claim("expert")["task"]["payload"]["step"] == 2


def test_http_probe_origin_and_click(tmp_path, q):
    # Actual HTTP handler tested in a subprocess; UI is deliberately not simulated here.
    import urllib.request
    import urllib.error
    import socket
    import time
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen([sys.executable, "-m", "scripts.teaching_collab", "--state", str(q.root), "serve", "--port", str(port)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for _ in range(40):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/status", timeout=1) as response:
                    assert response.status == 200
                    break
            except OSError:
                time.sleep(.1)
        else:
            pytest.fail("Server did not start")
        req = urllib.request.Request(f"http://127.0.0.1:{port}/probe-click", data=b'{}',
                                     headers={"Content-Type": "application/json", "Origin": "https://other.invalid"})
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req)
        assert exc.value.code == 403
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as response:
            assert "连接探针" in response.read().decode("utf-8")
    finally:
        process.terminate()
        process.communicate(timeout=10)


def test_preview_never_reuses_unknown_port(q, monkeypatch):
    import socket
    from scripts.teaching_collab import preview
    monkeypatch.setattr(preview, "git", module.git)
    instance = preview.Preview(q)
    batch = q.status()["batches"][0]
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        batch["config"]["preview_url"] = f"http://127.0.0.1:{listener.getsockname()[1]}"
        with pytest.raises(Conflict, match="existing service"):
            instance.ensure(batch)
        assert listener.fileno() >= 0
    assert not instance.children and not instance.manifest.exists()


def test_preview_waits_for_browser_and_does_not_restart(q):
    from scripts.teaching_collab.preview import Preview
    task = q.claim("teacher")["task"]
    q.surface(task["id"], task["token"])
    instance = Preview(q)
    instance.ensure(q.status()["batches"][0])
    assert not instance.children


def test_out_of_scope_commit_cannot_advance(q, monkeypatch):
    pass_gate(q)
    finish_discovery(q)
    agree(q)
    task = q.claim("expert")["task"]
    q.head[0] = NEXT
    original = module.git
    monkeypatch.setattr(module, "git", lambda root, *args: "backend/app/main.py" if args[:2] == ("diff", "--name-only") else original(root, *args))
    with pytest.raises(Conflict, match="ownership"):
        q.submit(task["id"], task["token"], dict(**basic(task), new_sha=NEXT))
    assert q.status()["batches"][0]["target_sha"] == SHA


def test_invalid_output_path_does_not_consume_lease(q, tmp_path):
    from scripts.teaching_collab.__main__ import main
    assert main(["--state", str(q.root), "claim", "--role", "teacher", "--wait", "0", "--out", str(tmp_path / "outside.json")]) == 2
    assert q.claim("teacher")["task"]


def test_branch_switch_rejects_submission(q, monkeypatch):
    task = q.claim("teacher")["task"]
    original = module.git
    monkeypatch.setattr(module, "git", lambda root, *args: "main" if args == ("branch", "--show-current") else original(root, *args))
    with pytest.raises(Conflict, match="branch changed"):
        q.submit(task["id"], task["token"], basic(task))
