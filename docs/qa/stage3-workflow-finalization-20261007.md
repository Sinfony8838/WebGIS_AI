# Stage 3a: workflow execution has one terminal cleanup boundary

## Ownership and scope

- Branch codex/stage3-workflow-finalization; starting main 821b18fe7f3bf8454498271f9453c9cf9581885e (PR #68).
- Dedicated managed worktree; actual AGENTS.md, clean status, branch and HEAD recorded before editing. No production data Junction, dependency installation or real worker launch.
- Allowed: backend/app/services/workflow_executor.py, new backend/tests/test_workflow_finalization.py and this record.
- Forbidden: public routes/status enums/event schemas, worker protocol, GIS algorithms, frontend, persistence formats, actual data/auth contents, credentials and unrelated dirty workspace changes.
- Dependency: single-writer fix merged with exact main CI and successful publication before edits. Continued operational observation remains a deployment gate; elapsed wall time alone is not acceptance.

## Behavior

Preparation after validation and the complete execution have exception/cleanup boundaries. Unexpected exceptions during initial persistence, files, events, thread construction/start, lookup, ordering, dispatch, artifact registration and terminal persistence produce the existing error state and workflow_error event, carrying the full record when available. Already-established processing and cancellation errors are retained if terminal persistence subsequently fails. Active running steps receive their error and finished_at. Normal success, handled failure, cancellation, optional summary behavior and event names are unchanged.

Worker-side workspace release runs in finally and keeps generated files on disk. The executor removes only the matching execution thread from its registry, including missing-record and release-failure paths. A thread-start failure returns the persisted terminal record and releases the unstarted thread reference instead of leaving a pending workflow with no worker.

For active steps, failure reporting emits the existing step_error event before workflow_error. The current SSE consumer merges step_error into its step list; a workflow_error alone updates only the overall status. Tests verify this event contract so an unexpected failure does not leave a running badge after termination. No frontend or event-enum change.

Failure reporting attempts state persistence, workflow-file persistence and event publication independently. An unwritable disk cannot promise a persisted terminal state; synthetic tests explicitly retain the old bytes while checking the in-memory error, event and cleanup. Original exception details remain in local logs, not the public error response.

This task does not fix whole-lifecycle cancellation, restart reconciliation, SSE interruption recovery, event-history retention or synchronous PPT work. Those remain separate dependent tasks. No replay or automatic resubmission was added.

## Evidence

- Added 22 deterministic synthetic failure cases: preparation saves/files/events/thread construction, worker exceptions and malformed returns, start/step/terminal saves, ordering, artifact registration, execution events, terminal-file writes, known errors and cancellation, persistent I/O failure, release failure, missing/failed lookup, thread start and one real local execution thread using a stub worker. A single-slot gate makes the no-leaked-slot assertion meaningful.
- Focused command: Python 3.12 -m pytest backend/tests/test_workflow_finalization.py backend/tests/test_workflow_executor.py backend/tests/test_workflow_population_templates.py backend/tests/test_workflow_cancel_api.py -q.
- First candidate: 46 passed, 4 skipped, 7 subtests passed in 10.53s. Expanded preparation coverage: 51 passed, 4 skipped, 7 subtests passed in 14.37s. Skipped real QGIS cases are not counted as validated.
- Final 22 fault cases after source/SSE review: 22 passed in 1.82s.
- Final exact-candidate full backend command: Python 3.12 -m pytest backend/tests -q; 1218 passed, 8 skipped, 176 subtests passed in 503.46s. Skips remain unvalidated real-environment cases.
- The first focused run's synthetic default data was retained inside this worktree before running the standard full-test isolation preflight again. It is not staged or published.
- Incomplete full runs were deliberately stopped after review found preparation/SSE gaps; neither is counted as passed. Final focused/full results follow the final code.
- Full backend regression and exact PR/main CI results are recorded before integration/publication.
- No real QGIS, model/vision provider, Windows COM, device or authenticated browser acceptance. Existing 3D shell and lesson/session/report behavior are preserved in source; operational health does not prove teaching-flow acceptance.

## Release and rollback

Only the three explicit paths may be staged. Production publication requires the exact tested main, verified old process identity/exit, fresh offline backup, fixed publishing scripts, unchanged data routing and renewed fifteen-minute observation of the previous release. No data restore, dependency installation or configuration changes.

Code rollback retains generated teaching data and the earlier resource-binding/Store fixes. Full per-machine runtime evidence stays local. Original documents and unrelated workspace changes were not modified.
