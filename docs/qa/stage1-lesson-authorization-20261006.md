# S2b: authorize assistant lesson references

## Task ownership and baseline

- Branch: `codex/stage1-lesson-authorization`; starting main: `c80522410ab3549a2ffeaadff3381d7cdefea65e` (S2a, PR #63).
- Dedicated worktree: `C:/Users/zcyxn/.codex/worktrees/stage1-lesson-authorization/WebGIS-AI`; clean and detached at creation, then switched to the task branch before edits.
- Allowed paths: `backend/app/main.py`, `backend/app/runtime.py`, `backend/app/services/session_engine.py`, `backend/app/services/classroom_binding.py`, new `backend/tests/test_assistant_lesson_authorization.py`, this record.
- Excluded: frontend, public request models, lesson/data formats, persistence, attachments, GIS algorithms, production data, secrets and dependency installation.
- Dependency: S2a merged and deployed before this task's source edits. Shared backend changes are sequential and reviewed by this task's integration owner.

## Implemented boundary

Assistant message entry validates both top-level and embedded lesson references before attachment resolution, Job creation or worker launch. For references without a classroom session, a lesson must be built-in, owned by the requesting project's teacher, or accessible to the current server-authenticated administrator. The existing HTTP project authorization establishes the teacher's identity; administrators retain access to projects and lessons belonging to other users. Unknown and unauthorized lesson references return the existing 404 convention.

Project-bound historical sessions continue using their authorized immutable lesson snapshots; a deleted or subsequently transferred global lesson does not invalidate a teacher's own class history. Starting a new class always checks the current lesson registry and ownership. Same-teacher private lessons remain reusable in multiple projects; no fictitious lesson project ID is introduced.

The lesson-design route's existing base-lesson authorization now runs before assistant submission, avoiding a late error after a Job has already been created. The final explicit lesson ID chosen by the planner is revalidated before actual tool execution. Direct tool execution pins its assessment project to the actual execute call and cannot use a supplied assessment project to change scope. Pending legacy and frozen confirmations are reauthorized against the current approver's server identity before Job creation, status resolution or memory changes.

A private ContextVar carries the server role through synchronous engine/tool callbacks, with reset on success or failure. It is isolated between worker threads. No role is taken from map context or stored plans. Confirmation entry passes the current authenticated role to its worker; a historical administrator's grant is not reused by a current teacher.

Title-based class start now iterates actual LessonRecord objects, filters unauthorized lessons before matching and revalidates the selected ID. The old code used dictionary `.get()` on these records and could fail on this input path. This is a source-confirmed correctness issue with a synthetic positive/negative acceptance case, not a claim of a production incident.

## Acceptance and limitations

New tests cover both input paths, forged client role/owner fields, same-owner reuse, built-in sharing, administrator use of another owner's lesson, deleted historical lesson references, internal memory boundaries, legacy/frozen confirmation contexts and explicit tool references, direct calls without project state, title matching, role isolation/reset and HTTP zero-side-effect rejection. All fixtures use new tmp_path data; no production Junction or real model calls.

- Full local backend suite: `python -m pytest backend/tests -q`: 1126 passed, 6 skipped, 176 subtests passed in 356.80s. This included the initial 30 new authorization cases. Three additional cases check all references before the first tool and current HTTP confirmation roles.
- Focused final regression: `python -m pytest backend/tests/test_assistant_lesson_authorization.py backend/tests/test_assistant_classroom_binding.py backend/tests/test_assistant_session_binding.py -q`: 74 passed in 27.35s, including all 33 new authorization cases. First-run synthetic data was preserved in this worktree's `scratch/s2b-first-test-data-20261006` after containment/link checks; the final regression used a fresh data root.
- `git diff --check`: passed before tests; rerun before commit.
- PR/main CI and production release: pending integration.
- Public endpoints, response shapes, tool names and task statuses remain unchanged. Internal methods add optional keyword-only server-role arguments; existing callers retain defaults.
- Not executed: authenticated browser/classroom acceptance, real PyQGIS, model service, Office/COM, load testing or data restoration.

## Previous step release evidence

S2a PR #63 merged as `c80522410ab3549a2ffeaadff3381d7cdefea65e`. PR backend CI: 1095 passed, 7 skipped, 176 subtests passed in 165.41s. Frontend tests/build and main CI succeeded. The task branch and squashed main commit had identical source trees. Local corrected focused regression: 98 passed, 39 subtests passed.

S1 completed more than fifteen minutes of observed operation before S2a deployment. The S2a offline v2 backup is `C:/Users/zcyxn/Desktop/WebGIS-AI-backups/20261006-201152-799-2dd871bf8aa8`, 478 files, 582922338 bytes. S1 managed processes were identified by PID, exact command and listener ownership before stopping. Data was not restored or replaced.

S2a started at `2026-10-06T20:12:37.1931488+08:00`; release metadata records the exact main SHA. Backend PID 44356/Caddy PID 44128 uniquely owned ports 18999/18080 with common launcher parent 36444. Publishing data remained the original production Junction. Release checker: 12 checks, 0 failed, 1 proxy Fake-IP DNS warning. Local/public health and root returned HTTP 200; unchanged frontend bundle `assets/index-4D9ECoLu.js` had matching SHA256 `60F3802A04B268BFBEE1CD8F5E7A6B90AA04AE1445B34FC84F461AE5E924307F`.

## Preservation and rollback

Only the six declared paths are eligible for staging. No primary dirty checkout change, source/resource cleanup, environment file, authentication database or test-generated data is committed. Code rollback is separate from data restoration and retains newly generated teaching state. A fallback must preserve confirmed ownership boundaries. Before publishing: exact main/CI identity, fresh complete backup, verified process ownership, then local/public health, assets, release metadata and observation.
