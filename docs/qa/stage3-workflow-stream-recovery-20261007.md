# Stage 3d: observe the original workflow after stream interruption

## Ownership and scope

- Branch codex/stage3-workflow-stream-recovery; starting main 777d77f1122df71b79c89d18c014c25f3cdbbc16 (PR #71).
- Clean managed worktree and AGENTS.md recorded before editing; business edits began only after verified publication of the preceding exact main.
- Allowed: backend/app/runtime.py, backend/app/services/workflow_executor.py, backend/tests/test_workflow_stream_recovery.py; frontend/src/App.tsx, api.ts, components/WorkflowDock.tsx, hooks/useWorkflowStream.ts, __tests__/WorkflowDock.test.tsx and __tests__/useWorkflowStream.test.ts; this record. Ten explicit files.
- Forbidden: endpoints/status/event enums, persistence formats, GIS mathematics, worker wire protocol, providers/COM execution, production data/auth contents or restoration, external plugin source/configuration, dependency installation and unrelated workspace changes.
- Acceptance: persisted terminal without history, subscription/commit races, idle versus terminal semantics, callback/timer/request cleanup, original-ID-only recovery, project/account lifetime, late HTTP/SSE rejection and relevant full backend/frontend checks/build.

## Behavior and boundaries

Workflow queries and terminal-snapshot SSE recovery share the executor's terminal-commit lock. The active lifecycle latch masks transient terminal assignment as existing running with no completion timestamp, including the interval between failed persistence and outer failure cleanup. No new task status is introduced, and the shared/persisted record is not rewritten by a read.

SSE subscribes before checking the current terminal snapshot again, so lookup/subscription races cannot lose completion. Existing success/error events include the full record and retained artifacts/steps when an in-memory history is absent after restart, or when terminal publication was missed. Idle accounting uses monotonic time. Transport inactivity retains the existing stream_idle_timeout event and does not fail, cancel or re-execute the task. Subscription cleanup remains in finally.

The frontend still hydrates HTTP and SSE concurrently and replays buffered events. A terminal snapshot cannot be regressed by historical start/step events. Full terminal failures/cancellation restore steps and retained artifacts. A closed/error stream queries the original workflow ID; a nonterminal snapshot reconnects only that ID, while success/error/cancelled stops observing. There is no submission/replay path. Retries are spaced by three seconds and serialized, with a fifteen-second abortable snapshot deadline and stale-request rejection.

Unmount/workflow/project change cancels timers, requests and event sources. HTTP and nested workflow event identity/project are checked before state commit. The application's dock key includes user and project, making account/project transitions destroy the old observer and preview/replay state; collapsing the dock retains state. No global state library changes.

Existing matching dependencies were copied read-only into a task-local physical node_modules directory after lockfile and reparse checks. No installation or production dependency Junction was used for these tests. Test-generated data/results/build remain untracked and are not source.

## Evidence and limitations

- Frontend focused: three files, 28 passed, including ten new hook recovery cases; 4.90s. Existing API/dock cases remain.
- Backend final related regression: new stream recovery, workflow finalization, cancellation and executor; 63 passed in 5.63s, including eleven new stream/commit cases. An initial fixture method-name mistake was corrected before acceptance. Failure injection also exposed the provisional-success interval; the lifecycle-latch read mask is included in this final result.
- First default local full frontend attempt failed: 12 files failed/74 passed; 5 tests failed/554 passed with collection failures and five-second timeouts. It is not counted as passed. The task-local results were preserved.
- Same frontend source, complete bounded command: npm test -- --maxWorkers 2 --minWorkers 1 --reporter default --reporter json --outputFile.json <task-local-report>; 86 files/616 tests passed in 60.09s; zero failed suites/tests. No skipped cases, relaxed timeouts or configuration change. Default-run failure cause is not conclusively established by this retry.
- npm run build succeeded: 499 modules; 3.31s. Existing chunk-size warning is not treated as a demonstrated functional/performance defect.
- Exact-candidate full backend: Python 3.12 -m pytest backend/tests -q; 1273 passed, 8 skipped, 176 subtests passed in 416.10s. No existing-data override or production Junction was used.
- Full backend and exact PR/main CI are required before integration/publication. Synthetic tests are not real QGIS/model/vision/Windows COM, authenticated classroom/browser or device acceptance.

## Release and rollback

Publish exact tested main only after the preceding release's renewed fifteen-minute public observation, fresh verified process/port exit, complete offline data/resource backup, retained frontend-build backup and unchanged production data Junction. Use fixed publishing scripts; build the changed frontend after the backup gate. Verify served frontend bytes against the resulting build and repeat public/local health observation.

Retain generated outputs and new teaching data on code rollback, along with preceding security, Store, cancellation and restart fixes. Do not restore an old runtime snapshot, automatically replay workflows, alter dependency/configuration files or modify unrelated dirty workspaces. Detailed machine metadata stays local; public release evidence is sanitized.
