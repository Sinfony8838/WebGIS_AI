# QGIS Worker Reliability Soak

Real-QGIS (no mocks) reliability harness for the PyQGIS worker subsystem.
Produces a JSON evidence report with per-step timings, crash/timeout/cancel
scenarios, and process-hygiene checks. Generates its own synthetic datasets
in a throwaway `WEBGIS_AI_DATA_DIR`; teacher data and running app state are
never touched.

## Usage

From a repository worktree root, with the backend Python 3.12:

```powershell
python scripts/qa/qgis_reliability/run_soak.py `
    --qgis-root "D:\QGIS 3.40.10" `
    --qgis-python "D:\QGIS 3.40.10\apps\Python312\python.exe" `
    --out "%TEMP%\qgis_soak_report.json"
```

`--qgis-root` / `--qgis-python` default to `QGIS_ROOT` /
`WEBGIS_AI_QGIS_PYTHON` environment variables, then to the paths above.

Exit code is 0 only when every verdict in the report is true:

* Phase A — cold start (spawn → `worker_ready` → first real op);
* Phase B — 30 sequential real operations across two alternating workflows
  (load → buffer → export → filter, including a legal empty result);
* Phase C — 10 interleaved groups of two workflows with IDENTICAL step ids
  on distinct datasets; crossed results/directories must be zero;
* Phase D — exec timeout with late-result isolation, mid-flight crash
  recovery (terminates only the manager's own child), cancel + rerun;
* Phase E — process hygiene: worker pid gone after shutdown.

The soak exercises the same code path as production
(`PyQgisWorkerManager` spawning a real worker under the QGIS-bundled
Python); it does not require the FastAPI server or any ports.
