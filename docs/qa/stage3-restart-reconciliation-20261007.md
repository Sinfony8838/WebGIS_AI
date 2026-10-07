# Stage 3c: reconcile interrupted tasks at server startup

## Ownership and scope

- Branch codex/stage3-restart-reconciliation; starting main 24f322ee59b9647f69dd351c0f3414300629a2b7 (PR #70).
- Dedicated managed worktree; clean branch/HEAD and actual AGENTS.md recorded before editing. Source edits followed verified publication of the preceding exact main.
- Allowed: backend/app/store.py, backend/app/runtime.py, backend/tests/test_startup_reconciliation.py and this record.
- Forbidden: frontend, public APIs/status enums, worker protocol, GIS mathematics, provider/COM execution, production snapshot inspection or restoration, authentication contents, credentials, external plugin source/configuration and unrelated checkout changes. No dependency installation.
- Acceptance: fresh-store startup ordering, no task replay, terminal/human/classroom preservation, idempotence across calls/restarts, atomic failure/lease release, read-only rejection, injected active-store preservation, workflow status mirror and full backend regression.

## Behavior and recovery boundary

Only a freshly constructed writer in WebGISRuntime performs startup reconciliation, before any service construction or worker/voice initialization. Injected stores and standalone/read-only RuntimeStore snapshots do not automatically reconcile. A successful call runs once per writer; it cannot run inside a deferred persistence batch.

Jobs left queued/running become existing failed. Generic pending, waiting_for_approval and terminal jobs remain unchanged. Existing in_process practice-export pending jobs retain the preceding restart-failure behavior and Chinese error message. Workflow pending/running becomes existing error/INTERNAL_ERROR with a service_restart reason in the compatible details field, a completion time, and error for active running steps. Completed and future pending steps retain their data.

Changed records are copied and persisted together in one atomic snapshot write. If writing fails, original collections/objects and valid disk bytes remain, startup aborts before service construction, and the new writer lease is closed. No request is resubmitted and no QGIS/provider execution is initiated. Terminal tasks, resource IDs, results, artifact references, project/confirmation/classroom records and student responses remain. The separate durable teaching collaboration coordinator queue is outside this scope.

After the authoritative snapshot commits, existing workflow-file persistence updates status.json and retains generated outputs. That existing mirror writer remains best effort: I/O errors are logged, and they do not erase or roll back the authoritative snapshot. Persisted terminal SSE delivery and disconnected-client reconciliation remain the next independent task.

## Evidence

- New synthetic startup cases plus Store recovery: Python 3.12 -m pytest backend/tests/test_startup_reconciliation.py backend/tests/test_store_recovery.py -q; 43 passed in 2.86s (21 new startup cases).
- Exact-candidate standard full backend command: Python 3.12 -m pytest backend/tests -q; 1262 passed, 8 skipped, 176 subtests passed in 421.16s. Test data belongs to the isolated task worktree; no production Junction or existing-data opt-out was used.
- Cases cover atomic temporary-write/replace failure, old object/byte preservation and clean retry, human waits, three existing workflow terminals, queued/current-process boundaries, legacy practice statuses, running classroom responses, existing artifacts/files, sequential restarts, read-only and batch guards, fresh versus injected constructor ordering, startup failure lease release and status-file synchronization with stub services/worker.
- Full standard backend regression and exact PR/main CI must pass before integration/publication. Native QGIS, model/vision, Windows COM, authenticated classroom/browser and device behavior are not represented as accepted.

## Release and rollback

Stage only the four explicit paths. Publish exact tested main after the preceding release's fifteen-minute observation, fresh process/port verification and exit, complete offline recovery backup and unchanged production data Junction. Retain the frontend build.

Unlike previous backend-only fixes, the intended startup behavior may legitimately change interrupted task statuses in the runtime snapshot; an unchanged whole-file hash is not an acceptance requirement for this task. Preserve the complete pre-startup backup and generated files. Code rollback preserves newer teaching data and preceding security/recovery fixes; it does not restore an old data snapshot or replay interrupted work. Public notes contain sanitized results, while machine runtime metadata remains local.
