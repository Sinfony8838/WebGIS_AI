# Stage 4b: project snapshot ownership

Branch: `codex/stage4-project-snapshot-gates`. Starting main: `0639de658dc37a66a1714950d48c83d0992a60e9`.

Objective: prevent obsolete reads from overwriting the current actor's selected project, layers, outputs, lesson resources and active teaching maps. Preserve project restoration and normal mutations.

Allowed scope: `frontend/src/App.tsx`, `frontend/src/api.ts`, `frontend/src/main.tsx`, new `frontend/src/hooks/useProjectSnapshotRefresh.ts`, new `frontend/src/__tests__/useProjectSnapshotRefresh.test.tsx`, new `frontend/src/__tests__/projectSnapshotApi.test.ts`, this QA record. No backend, API endpoint/schema, dependency, GIS math or persistence-format changes.

## Behavior

- The hook owns a mounted actor/project lifetime and a monotonically increasing read batch. Each cohort shares one AbortController; newer reads, project selection, actor changes and unmount invalidate earlier work. A transport ignoring cancellation still cannot commit stale results. A wrong-project caller neither reads nor cancels valid current work.
- All five existing GET results commit together only if the cohort still owns its scope and the returned project identity matches. A failed current read preserves the last committed state and selection; it does not create a project or rewrite its saved pointer. Explicit bootstrap selection remains separate from ordinary refresh.
- Partial lesson/map/basemap responses check their original project lifetime before UI writes, invalidate earlier aggregate reads, and request a fresh reconciliation. Background reconciliation failure is reported separately from a successful mutation. This does not serialize concurrent server mutations or provide a server transaction spanning the five GETs.
- Workflow output lookup no longer writes output UI state independently. Its original artifact auto-load remains available even when another same-project refresh supersedes a cohort; project-lifetime checks precede the follow-up POST and camera focus. Completed existing artifacts are not replayed as workflows.
- Root App is keyed by actor identity. A cancelled request's late 401 and a prior CSRF generation's 401 cannot clear a newer session. A current generation's 401 still invokes normal centralized sign-out. Optional signals preserve existing no-signal helper callers and cookie/CSRF conventions.
- Map shell, 3D globe, lesson/session/report entry points, workflow and TOP20 components remain present. Existing basemap selection, active lesson resources and teaching overlays keep their response/ID contracts.

## Validation

- First focused run: 42 passed / 7 failed; all seven failures used a matcher unavailable in installed Vitest 2. Replaced that matcher with exact mock-call-array assertions; no behavior requirement removed.
- Focused final pre-build run: 5 files / 49 tests passed in 2.83s (snapshot hook/API, auth, project recovery, read retry). One additional last-good-snapshot case was then added.
- Initial build found the existing `onRefresh: Promise<void>` consumer incompatible with the new snapshot-returning function. Adapted the callback to await without returning its DTO.
- Final full frontend: `npm test -- --maxWorkers=2 --minWorkers=1`: 88 files / 638 tests passed in 59.34s. No tests skipped or timeouts relaxed; concurrency is bounded for this Windows host.
- Final `npm run build`: 500 modules transformed, success in 3.77s; existing bundle-size advisory remains. `git diff --check` passed.
- Backend source is unchanged; local backend tests were not repeated. Exact PR and merged-main quality gates must pass before publication, including the unchanged full backend suite and default frontend test/build commands.

Dependencies were copied into a dedicated physical directory from a matching task lockfile; no installation or production Junction was used for tests. No real backend/model/QGIS/COM call, authenticated browser/classroom, camera/screenshot or device acceptance is claimed. Production publication and its observation are recorded in the PR after execution.

Code rollback retains new teaching data and preceding resource-binding, Store and task-recovery fixes. No production data restoration, authentication-content inspection, primary-checkout modification or unrelated workspace change occurred.
