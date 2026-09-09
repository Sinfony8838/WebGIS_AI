"""Real-QGIS reliability soak for the PyQGIS worker subsystem.

Runs against a REAL QGIS installation (no mocks) and produces a JSON +
Markdown evidence report:

* Phase A  — cold start (spawn → worker_ready) timing;
* Phase B  — 30 sequential real QGIS operations across alternating
  workflows with unique step names;
* Phase C  — 10 interleaved groups: two workflows with IDENTICAL step ids
  running concurrently on distinct datasets; every response must belong to
  the requesting workflow and land in that workflow's own directory;
* Phase D  — reliability scenarios: exec-timeout with late-result
  isolation, mid-flight crash recovery (manager terminates only its own
  child process), cancellation and rerun, and a legal empty result;
* Phase E  — process hygiene: python process count per phase, worker pid
  liveness, and a final assertion that the worker is gone after shutdown.

The script generates its own synthetic datasets under a throwaway
WEBGIS_AI_DATA_DIR — teacher data and the running app's state are never
touched.

Usage (from the repository worktree root):

    python scripts/qa/qgis_reliability/run_soak.py \
        --qgis-root "D:/QGIS 3.40.10" \
        --qgis-python "D:/QGIS 3.40.10/apps/Python312/python.exe" \
        --out report.json            # optional; default: temp dir
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from backend.app.services.pyqgis_worker import PyQgisWorkerManager  # noqa: E402


# ----------------------------------------------------------------------
# Synthetic test data (own project; never teacher data)
# ----------------------------------------------------------------------

def make_dataset(path: Path, count: int, value_max: int, seed: int) -> None:
    import random

    rng = random.Random(seed)
    features = []
    for i in range(count):
        lat = 30.0 + rng.random() * 2.0
        lon = 114.0 + rng.random() * 2.0
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
            "properties": {"name": f"pt_{seed}_{i}", "value": rng.randint(1, value_max)},
        })
    fc = {"type": "FeatureCollection", "features": features}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fc), encoding="utf-8")


def count_python_processes() -> int:
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_Process -Filter \"Name like 'python%'\").Count"],
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
        return int(out or 0)
    except Exception:
        return -1


def pid_alive(pid: Optional[int]) -> bool:
    if not pid:
        return False
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-Process -Id {pid} -ErrorAction SilentlyContinue) -ne $null"],
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
        return out.lower() == "true"
    except Exception:
        return False


# ----------------------------------------------------------------------
# Soak runner
# ----------------------------------------------------------------------

class Soak:
    def __init__(self, qgis_root: str, qgis_python: str) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="qgis_soak_"))
        self.data_dir = self.tmp / "data"
        os.environ["WEBGIS_AI_DATA_DIR"] = str(self.data_dir)
        self.workflows_root = self.data_dir / "workflows"
        self.dataset_a = self.data_dir / "uploads" / "soak_proj" / "soak_a.geojson"
        self.dataset_b = self.data_dir / "uploads" / "soak_proj" / "soak_b.geojson"
        make_dataset(self.dataset_a, count=12, value_max=100, seed=1)
        make_dataset(self.dataset_b, count=30, value_max=100, seed=2)
        self.dataset_big = self.data_dir / "uploads" / "soak_proj" / "soak_big.geojson"
        make_dataset(self.dataset_big, count=150000, value_max=100, seed=3)

        self.manager = PyQgisWorkerManager(
            workflows_root=self.workflows_root,
            qgis_root=qgis_root,
            qgis_python=qgis_python,
            startup_timeout=180.0,
            step_timeout=300.0,
            queue_timeout=300.0,
        )
        self.report: Dict[str, Any] = {
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "qgis_root": qgis_root,
            "qgis_python": qgis_python,
            "data_dir": str(self.data_dir),
            "cold_start": {},
            "sequential": {},
            "interleave": {},
            "reliability": {},
            "process_hygiene": {},
            "verdicts": {},
        }

    # -- helpers -------------------------------------------------------

    def timed_step(self, workflow_id: str, step: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        t0 = time.time()
        result = self.manager.run_step(workflow_id, step, **kwargs)
        wall_ms = round((time.time() - t0) * 1000, 1)
        result.setdefault("timings", {})["wall_ms"] = wall_ms
        return result

    def expect_success(self, result: Dict[str, Any], workflow_id: str, step_id: str) -> None:
        assert result.get("status") == "success", (
            f"{workflow_id}/{step_id} expected success, got: {json.dumps(result, ensure_ascii=False)[:500]}"
        )
        assert result.get("workflow_id") == workflow_id, "workflow_id mismatch — crossed result!"
        assert result.get("step_id") == step_id, "step_id mismatch — crossed result!"

    def record(self, section: str, entry: Dict[str, Any]) -> None:
        self.report.setdefault(section, {}).setdefault("records", []).append(entry)

    # -- phases --------------------------------------------------------

    def phase_a_cold_start(self) -> None:
        t0 = time.time()
        self.manager.ensure_started()
        ready_ms = round((time.time() - t0) * 1000, 1)
        first = self.timed_step("wf_boot", {"id": "boot_load", "op": "load_layer",
                                            "params": {"source": str(self.dataset_a)}})
        self.expect_success(first, "wf_boot", "boot_load")
        self.report["cold_start"] = {
            "worker_ready_ms": ready_ms,
            "first_real_op_ms": first["timings"]["wall_ms"],
            "first_op_feature_count": first["outputs"].get("feature_count"),
            "worker_pid": self.manager._process.pid,
        }

    def phase_b_sequential(self, total: int = 30) -> None:
        records: List[Dict[str, Any]] = []
        ops = 0
        round_no = 0
        empty_result_seen = False
        while ops < total:
            wf = "wf_seq_a" if round_no % 2 == 0 else "wf_seq_b"
            dataset = self.dataset_a if wf.endswith("a") else self.dataset_b
            load_id = f"load_{round_no}"
            buffer_id = f"buffer_{round_no}"
            plan = [
                ("load", "load_layer", {"source": str(dataset)}, None),
                ("buffer", "buffer",
                 {"input": "${%s.layer}" % load_id, "distance": 500},
                 12 if wf.endswith("a") else 30),
                ("export", "export_geojson",
                 {"input": "${%s.layer}" % buffer_id, "name": f"buf_{wf}"}, None),
                ("filter", "filter_features",
                 {"input": "${%s.layer}" % load_id, "expression": "value > 100"}, None),
            ]
            outputs_by_id: Dict[str, Dict[str, Any]] = {}
            for tag, op, params, expect_count in plan:
                if ops >= total:
                    break
                step_id = f"{tag}_{round_no}"
                t0 = time.time()
                result = self.manager.run_step(wf, {"id": step_id, "op": op, "params": params})
                wall_ms = round((time.time() - t0) * 1000, 1)
                self.expect_success(result, wf, step_id)
                out = result.get("outputs") or {}
                if expect_count is not None:
                    assert out.get("feature_count") == expect_count, (
                        f"feature_count mismatch: {out.get('feature_count')} != {expect_count}"
                    )
                if op == "export_geojson":
                    p = Path(out["geojson"])
                    assert p.exists() and p.stat().st_size > 0, "export missing/empty"
                    assert str(p).startswith(str(self.workflows_root / wf)), "artifact outside own workflow dir"
                if op == "filter_features" and out.get("feature_count") == 0:
                    empty_result_seen = True  # legal empty result, still success
                records.append({
                    "workflow": wf, "step_id": step_id, "op": op, "wall_ms": wall_ms,
                    "queued_ms": (result.get("timings") or {}).get("queued_ms"),
                    "exec_ms": (result.get("timings") or {}).get("exec_ms"),
                    "feature_count": out.get("feature_count"),
                })
                ops += 1
            round_no += 1
        walls = [r["wall_ms"] for r in records]
        self.report["sequential"] = {
            "operations": ops,
            "wall_ms_total": round(sum(walls), 1),
            "wall_ms_avg": round(sum(walls) / len(walls), 1),
            "wall_ms_min": min(walls),
            "wall_ms_max": max(walls),
            "legal_empty_result_ok": empty_result_seen,
            "records": records,
        }

    def phase_c_interleave(self, groups: int = 10) -> None:
        failures: List[str] = []
        group_times: List[float] = []
        first = time.time()

        def run_workflow(workflow_id: str, dataset: Path, expect_count: int, group: int) -> None:
            try:
                t0 = time.time()
                load = self.manager.run_step(workflow_id, {
                    "id": "shared_load", "op": "load_layer", "params": {"source": str(dataset)},
                })
                self.expect_success(load, workflow_id, "shared_load")
                assert load["outputs"]["feature_count"] == expect_count, (
                    f"{workflow_id}: crossed dataset! count={load['outputs']['feature_count']}"
                )
                buf = self.manager.run_step(workflow_id, {
                    "id": "shared_buffer", "op": "buffer",
                    "params": {"input": "${shared_load.layer}", "distance": 300},
                })
                self.expect_success(buf, workflow_id, "shared_buffer")
                assert buf["outputs"]["feature_count"] == expect_count
                exp = self.manager.run_step(workflow_id, {
                    "id": "shared_export", "op": "export_geojson",
                    "params": {"input": "${shared_buffer.layer}", "name": f"x_{workflow_id}"},
                })
                self.expect_success(exp, workflow_id, "shared_export")
                p = Path(exp["outputs"]["geojson"])
                assert str(p).startswith(str(self.workflows_root / workflow_id)), (
                    f"crossed directory: {p}"
                )
                group_times.append(round((time.time() - t0) * 1000, 1))
            except AssertionError as exc:
                failures.append(f"group {group} {workflow_id}: {exc}")
            except Exception as exc:  # noqa: BLE001
                failures.append(f"group {group} {workflow_id}: {exc!r}")

        for g in range(groups):
            threads = [
                threading.Thread(target=run_workflow,
                                 args=(f"ix_a_{g}", self.dataset_a, 12, g)),
                threading.Thread(target=run_workflow,
                                 args=(f"ix_b_{g}", self.dataset_b, 30, g)),
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(120)
        self.report["interleave"] = {
            "groups": groups,
            "total_ms": round((time.time() - first) * 1000, 1),
            "group_ms_avg": round(sum(group_times) / max(1, len(group_times)), 1),
            "crossed_results": len(failures),
            "failures": failures,
            "late_messages_dropped": self.manager.stats["late_messages_dropped"],
        }

    def phase_d_reliability(self) -> None:
        rel: Dict[str, Any] = {}

        # D1: exec timeout + late result isolation ------------------------
        # Load first (fast), then request a buffer with a 50ms exec budget —
        # the real QGIS buffer takes far longer, so the caller times out and
        # the late result must be isolated.
        load = self.manager.run_step("wf_to", {"id": "to_load", "op": "load_layer",
                                               "params": {"source": str(self.dataset_big)}})
        self.expect_success(load, "wf_to", "to_load")
        t0 = time.time()
        timed_out = self.manager.run_step(
            "wf_to",
            {"id": "late_buffer", "op": "buffer",
             "params": {"input": load["outputs"]["layer"], "distance": 30}},
            timeout=0.05,
        )
        elapsed_ms = round((time.time() - t0) * 1000, 1)
        assert timed_out["status"] == "error", "expected exec timeout"
        assert timed_out["error"]["code"] == "STEP_EXEC_TIMEOUT", timed_out["error"]
        rel["exec_timeout"] = {
            "code": "STEP_EXEC_TIMEOUT",
            "returned_after_ms": elapsed_ms,
            "exec_ms_reported": timed_out["timings"]["exec_ms"],
        }
        deadline = time.time() + 180
        while time.time() < deadline and self.manager.stats["late_messages_dropped"] < 1:
            time.sleep(0.1)
        rel["late_result_dropped"] = self.manager.stats["late_messages_dropped"] >= 1
        # Same step id again must get its own fresh result.
        rerun = self.manager.run_step(
            "wf_to", {"id": "late_buffer", "op": "buffer",
                      "params": {"input": load["outputs"]["layer"], "distance": 30}},
        )
        self.expect_success(rerun, "wf_to", "late_buffer")
        rel["rerun_after_timeout_ok"] = True
        self.report["reliability"] = rel

    def phase_d2_crash_and_cancel(self) -> None:
        rel = self.report["reliability"]

        # D2: mid-flight crash (terminate ONLY our own child) + recovery ---
        load = self.manager.run_step("wf_crash", {"id": "c_load", "op": "load_layer",
                                                  "params": {"source": str(self.dataset_big)}})
        self.expect_success(load, "wf_crash", "c_load")
        outcomes: Dict[str, Any] = {}

        def run_buffer() -> None:
            outcomes["buf"] = self.manager.run_step(
                "wf_crash", {"id": "c_buffer", "op": "buffer",
                             "params": {"input": load["outputs"]["layer"], "distance": 10}})

        thread = threading.Thread(target=run_buffer)
        thread.start()
        time.sleep(0.4)  # buffer executing in the worker
        victim_pid = self.manager._process.pid
        # Simulated hard crash: kill ONLY the manager's own child handle.
        self.manager._process.terminate()
        thread.join(60)
        crash_result = outcomes["buf"]
        rel["crash"] = {
            "victim_pid": victim_pid,
            "code": crash_result.get("error", {}).get("code"),
            "attempt": crash_result.get("attempt"),
            "status": crash_result.get("status"),
        }
        # The buffer references an in-memory layer that died with the worker:
        # no unsafe auto-retry → accurate WORKER_CRASHED.
        assert crash_result["status"] == "error"
        assert crash_result["error"]["code"] == "WORKER_CRASHED"
        # Recovery: a reference-free step respawns the worker and succeeds.
        t0 = time.time()
        recovered = self.manager.run_step("wf_crash2", {"id": "r_load", "op": "load_layer",
                                                        "params": {"source": str(self.dataset_a)}})
        recovery_ms = round((time.time() - t0) * 1000, 1)
        self.expect_success(recovered, "wf_crash2", "r_load")
        rel["crash_recovery"] = {
            "fresh_op_ms": recovery_ms,
            "new_generation": self.manager.generation(),
            "worker_recovered": True,
        }

        # D3: cancel mid-execution, late result isolated, rerun works ------
        load3 = self.manager.run_step("wf_cancel", {"id": "x_load", "op": "load_layer",
                                                    "params": {"source": str(self.dataset_big)}})
        self.expect_success(load3, "wf_cancel", "x_load")
        cancel_event = threading.Event()
        outcomes2: Dict[str, Any] = {}

        def run_big_buffer() -> None:
            outcomes2["buf"] = self.manager.run_step(
                "wf_cancel", {"id": "x_buffer", "op": "buffer",
                              "params": {"input": load3["outputs"]["layer"], "distance": 50}},
                cancel_event=cancel_event)

        thread = threading.Thread(target=run_big_buffer)
        thread.start()
        time.sleep(0.5)
        cancel_event.set()
        thread.join(30)
        cancelled = outcomes2["buf"]
        assert cancelled["status"] == "error"
        assert cancelled["error"]["code"] == "STEP_CANCELLED", cancelled["error"]
        rel["cancel"] = {
            "code": "STEP_CANCELLED",
            "returned_after_ms": cancelled["timings"]["total_ms"],
        }
        rerun = self.manager.run_step(
            "wf_cancel", {"id": "x_buffer", "op": "buffer",
                          "params": {"input": load3["outputs"]["layer"], "distance": 50}})
        self.expect_success(rerun, "wf_cancel", "x_buffer")
        rel["rerun_after_cancel_ok"] = True

    def phase_e_process_hygiene(self) -> None:
        worker_pid = self.report["cold_start"]["worker_pid"]
        # NOTE: the crash scenario replaced the worker; report the CURRENT pid.
        current_pid = self.manager._process.pid if self.manager.is_alive() else None
        self.report["process_hygiene"] = {
            "python_processes_before": self.report.get("python_processes_before"),
            "python_processes_after_work": count_python_processes(),
            "worker_pid_first": worker_pid,
            "worker_pid_final": current_pid,
        }

    def finalize(self) -> None:
        worker_pid = self.manager._process.pid if self.manager.is_alive() else None
        self.manager.shutdown()
        time.sleep(0.5)
        self.report["process_hygiene"]["worker_alive_after_shutdown"] = pid_alive(worker_pid)
        self.report["process_hygiene"]["python_processes_after_shutdown"] = count_python_processes()
        self.report["manager_stats"] = dict(self.manager.stats)
        self.report["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

        verdicts = {
            "sequential_30_ops": self.report.get("sequential", {}).get("operations", 0) >= 30,
            "interleave_10_groups": self.report.get("interleave", {}).get("groups", 0) >= 10,
            "zero_crossed_results": self.report.get("interleave", {}).get("crossed_results", -1) == 0,
            "exec_timeout_isolated": bool(self.report.get("reliability", {}).get("late_result_dropped")),
            "rerun_after_timeout_ok": bool(self.report.get("reliability", {}).get("rerun_after_timeout_ok")),
            "crash_reported_accurately": self.report.get("reliability", {}).get("crash", {}).get("code") == "WORKER_CRASHED",
            "worker_recovered_after_crash": bool(self.report.get("reliability", {}).get("crash_recovery", {}).get("worker_recovered")),
            "cancel_reported_accurately": self.report.get("reliability", {}).get("cancel", {}).get("code") == "STEP_CANCELLED",
            "rerun_after_cancel_ok": bool(self.report.get("reliability", {}).get("rerun_after_cancel_ok")),
            "worker_gone_after_shutdown": not self.report.get("process_hygiene", {}).get("worker_alive_after_shutdown", True),
        }
        self.report["verdicts"] = verdicts
        self.report["all_passed"] = all(verdicts.values())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qgis-root", default=os.environ.get("QGIS_ROOT", "D:/QGIS 3.40.10"))
    parser.add_argument("--qgis-python",
                        default=os.environ.get("WEBGIS_AI_QGIS_PYTHON",
                                               "D:/QGIS 3.40.10/apps/Python312/python.exe"))
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    soak = Soak(args.qgis_root, args.qgis_python)
    soak.report["process_hygiene"]["python_processes_before"] = count_python_processes()
    try:
        soak.phase_a_cold_start()
        print("[soak] Phase A cold start OK:", soak.report["cold_start"])
        soak.phase_b_sequential(30)
        print("[soak] Phase B 30 sequential ops OK:", {
            k: v for k, v in soak.report["sequential"].items() if k != "records"})
        soak.phase_c_interleave(10)
        print("[soak] Phase C 10 interleave groups OK:", {
            k: v for k, v in soak.report["interleave"].items()})
        soak.phase_d_reliability()
        soak.phase_d2_crash_and_cancel()
        print("[soak] Phase D reliability OK:", soak.report["reliability"])
        soak.phase_e_process_hygiene()
    finally:
        soak.finalize()

    out_path = Path(args.out) if args.out else Path(tempfile.gettempdir()) / "qgis_soak_report.json"
    out_path.write_text(json.dumps(soak.report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[soak] report:", out_path)
    print("[soak] verdicts:", json.dumps(soak.report["verdicts"], indent=2))
    print("[soak] ALL PASSED:", soak.report["all_passed"])
    return 0 if soak.report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
