# Stage 3b: cancellation covers the workflow lifecycle

## Ownership and scope

- Branch codex/stage3-workflow-cancellation; starting main eb7ccc48e1622677557a04f26265b76556d987a8 (PR #69).
- Dedicated managed worktree, clean branch/HEAD and actual AGENTS.md recorded before editing. Preparation/read-only review preceded publication; source edits began only after the preceding exact main CI and verified deployment.
- Allowed: workflow_executor.py, request_limits.py, pyqgis_worker/worker_manager.py; new test_workflow_lifecycle_cancel.py; cancellation-parameter adaptation only in test_workflow_executor.py, test_workflow_population_templates.py and test_workflow_finalization.py; this record.
- Forbidden: other routes, runtime/main, frontend, status enums/event schemas, worker wire protocol, GIS mathematics, persistence formats, production data/auth contents, credentials and unrelated dirty checkout changes. No dependency installation.
- Acceptance: preparation/pre-admission cancellation, prompt gate/startup-wait cancellation, slot ownership, cancellation between steps or during summary, late results/crash retry, committed terminal race, workflow isolation and full backend regression. Mock evidence is distinguished from actual QGIS/provider/device acceptance.

## Behavior and boundaries

Each active orchestration owns a cancellation event registered before initial persistence and retained until terminal commit/cleanup. Cancellation can be accepted before any worker request exists. Existing response fields are preserved: cancelled_requests is the manager count, or one when orchestration accepted cancellation without a registered request; repeated cancellation and already-committed terminals return zero. No new public states or events.

The event is checked before running/admission/dispatch, after dispatch and between steps, before and after optional summary, and under the lock that protects result/artifact and terminal commits. Accepted cancellation uses existing cancelled/STEP_CANCELLED and full workflow_error; active steps use existing step_error. Existing completed artifacts and generated files remain. A late result is not newly registered, a later step does not start, and a late summary is not saved. The summary callback still receives a successful-record view, while the shared record remains running without finished_at until terminal commit; queries cannot mistake an unfinished summary for committed success.

AdmissionGate has an optional cancellation event, bounded 0.2-second waits and one monotonic timeout budget. Waiting counters span the entire wait; a cancellation race after slot acquisition returns that slot. It never releases another workflow's occupied slot. Callers without a cancellation event retain the original semaphore behavior.

Worker manager checks cancellation before startup, while awaiting its lifecycle lock/readiness, after startup, and immediately before enqueue. Enqueue and manager cancellation share the pending-request lock. Cancellation leaves a shared worker's startup intact for other workflows. A cancelled crash result does not auto-retry. Existing request-id isolation still drops orphaned late replies.

Cancellation does not promise to forcibly interrupt already-running native QGIS or an already-started summary/provider request. Their late results are discarded; files already generated remain. No real provider calls or QGIS processes are used for these tests. Restart reconciliation and SSE interruption recovery remain separate tasks.

## Evidence

- Initial focused regression: 84 passed, 4 skipped, 7 subtests passed in 14.00s. The later startup-wait changes require the expanded/final results below and are not covered by this initial count.
- New synthetic cases use temporary data, stub workers and barriers. They cover pre-execution/creation, occupied-gate and post-admission races, skip/abort with late success or exception, step/summary boundaries, provisional and committed success races, separate workflows, gate capacity, worker startup/lifecycle waits, pre-enqueue cancellation, crash retry and orphaned reply routing.
- Expanded related command: Python 3.12 -m pytest backend/tests/test_workflow_lifecycle_cancel.py backend/tests/test_workflow_finalization.py backend/tests/test_workflow_executor.py backend/tests/test_workflow_population_templates.py backend/tests/test_workflow_cancel_api.py backend/tests/test_phase1_request_limits.py backend/tests/qgis_reliability -q.
- Expanded pre-summary-boundary result: 117 passed, 4 skipped, 7 subtests passed in 118.19s. The manager reliability tests use the existing fake subprocess worker, not QGIS.
- An incomplete full run was deliberately stopped when source review found the provisional-success query gap. It is not counted as passed; final results must include the summary-boundary change and its new barrier test.
- Final related regression including the summary boundary: 88 passed, 4 skipped, 7 subtests passed in 10.09s. Command: the expanded command above without backend/tests/qgis_reliability; the final full regression also covers that suite.
- Final exact-candidate standard command: Python 3.12 -m pytest backend/tests -q; 1241 passed, 8 skipped, 176 subtests passed in 501.54s. The new lifecycle-cancellation file contributes 23 synthetic cases.
- Full standard backend regression and exact PR/main CI must pass before integration/publication. Real QGIS skips and model/vision, Windows COM, authenticated classroom/browser and device behavior are not represented as accepted.

## Release and rollback

Stage only the eight explicit paths. Publish only the exact tested main after the preceding release's fifteen-minute observation, freshly verified process/port identity and exit, offline backup and unchanged data Junction. Fixed publishing scripts retain data and the frontend build because this task changes no frontend source.

Code rollback preserves new teaching data and all preceding resource-binding, Store and workflow-finalization fixes. No data restore, dependency installation, direct secret/authentication-record reading or unrelated workspace modification. Detailed machine runtime metadata remains local; public release notes contain only sanitized results.
