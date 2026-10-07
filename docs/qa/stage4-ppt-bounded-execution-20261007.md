# Stage 4a: bounded PPT execution outside the async request loop

## Ownership and baseline

- Branch codex/stage4-ppt-bounded-execution; starting main 8f3bbbed50d1b15dfc581cc6f7db0fd0b595bec5 (PR #72).
- Dedicated clean managed worktree; AGENTS.md, branch, starting SHA and absence of production data/dependency links recorded before editing. Business edits began after verified publication of the preceding exact main.
- Four allowed files: backend/app/main.py, backend/app/services/bounded_executor.py, backend/tests/test_ppt_bounded_execution.py and this record.
- Forbidden: converter/COM internals, frontend, public endpoints or normal result/error structures, PPT content/page order/brush handling, GIS mathematics, persistence formats, production data or authentication contents, dependency installation, real model/QGIS/Office calls and unrelated workspace changes.
- Acceptance: real async HTTP health remains responsive during a synthetic slow conversion; explicit overload; capacity ownership through cancellation; skipped queued cancellation; shutdown/drain/thread cleanup; existing error/upload/file authorization behavior; complete backend regression and exact PR/main CI before publication.

## Behavior and limits

The async PPT route reads the existing byte-limited upload, then awaits a dedicated lazy worker. The facility admits at most two conversions: one executing and one queued. A full or closing facility returns HTTP 503 with the existing structured PPT error shape and code PPT_RENDERER_BUSY. Rejection occurs before entering the converter or creating preview files. This bounds conversion work and retained admitted buffers; it does not add a new multipart transport or global upload admission policy.

Cancellation of a waiting HTTP request does not release capacity while its conversion still runs. A cancelled queued future is skipped by the worker and retains its slot until consumed, preventing repeated queued cancellation from accumulating an unbounded backlog. Capacity is returned only after actual completion or skipping. Result/error delivery cannot retain request buffers while the worker waits for its next job. Worker-start failure consumes no slot.

The application lifespan owns a fresh facility. Shutdown atomically rejects new work, cancels queued futures and joins an existing worker outside the event loop. An unused facility closes directly without creating a default-pool thread. Existing converter subprocess deadlines and cleanup continue to own running native work; this change does not forcibly abort an active Office process. A default lazy facility also supports existing direct route/TestClient use without lifecycle startup, without creating a thread at import time.

Only the synchronous converter runs on the worker. File grants occur after successful await on the original request context and event-loop thread. Cancelled, rejected or failed requests receive no late grants. Existing converter implementation, original uploads, rendering copies, page-count checks, output ordering and response structures are untouched.

## Evidence

- Initial related run: PPT bounded execution, existing renderer and request limits; 30 passed, 2 subtests passed in 14.61s. Twelve new cases cover the above execution/lifecycle boundaries with synthetic functions and temporary files. No Office, model or production files are opened.
- The queued-admission fixture was subsequently made deterministic by submitting directly to the facility before its first await. The first full run was interrupted after prolonged inactivity; a verbose retry with a 120-second thread dump confirmed blocking in an existing confirmation test's TestClient shutdown. That test patches the shared threading.Thread attribute, and unconditional idle-lifecycle asyncio.to_thread submission waited on the mocked default-pool thread. Both incomplete runs are not counted as passed. Cleanup now avoids default-pool submission when no worker exists, with a thirteenth new regression case; existing tests are untouched.
- Test-created physical backend/data was checked for containment and links, then retained in a new task-local scratch directory before the standard full run. No existing-data override, production Junction or restoration is used.
- Final related regression after the cleanup fix: the thirteen PPT cases, existing renderer/request budgets and existing assistant lesson authorization/confirmation cases; 64 passed, 2 subtests passed in 14.94s. The original confirmation tests and their thread mocks are unchanged.
- Final-candidate complete backend: Python 3.12 -m pytest backend/tests -q -o faulthandler_timeout=120; 1286 passed, 8 skipped, 178 subtests passed in 376.95s. The diagnostic setting prints stacks for long tests; it neither skips cases nor relaxes assertions. No source changes occurred during this accepted run. git diff --check passed.
- Exact PR/main CI and release observation are pending. Frontend is unchanged.

## Publication and rollback

Publish only exact tested main after the preceding release's fifteen-minute public observation and a fresh complete offline data/resource backup. Use the fixed publishing scripts; retain the current frontend build because this backend-only task does not require rebuilding it. Verify live version, local/public health, root/static asset, logs and subsequent observation. Source rollback preserves new teaching data and all preceding binding, Store, cancellation, restart and stream recovery fixes; data recovery is a separate action.

Synthetic concurrency and lifecycle checks do not establish real Windows COM, rendering fidelity, browser/classroom, external service or device acceptance. No unrelated workspace changes were modified.
