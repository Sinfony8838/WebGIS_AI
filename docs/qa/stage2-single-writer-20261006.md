# Stage 2c: one writer per physical state root

## Ownership and scope

- Branch: codex/stage2-single-writer. Starting main: 7c24b792073eca7947933018ecd36bb232eee844 (PR #67).
- Dedicated managed worktree; actual AGENTS.md, clean status, branch and HEAD checked before edits. No production data Junction.
- Allowed: backend/app/store.py, new backend/app/state_writer.py, new backend/tests/test_store_writer.py, deploy/public-windows/MAINTENANCE.md and this record.
- Readback/restart test adaptations only: test_store.py, test_store_recovery.py, test_layer_persistence.py, test_classroom_repeated_operations.py, test_interaction_regressions.py, test_lessons.py, test_lesson_design.py, test_lesson_rehearsal.py, test_practice_export.py under backend/tests.
- Forbidden: frontend, public APIs, persisted formats, GIS mathematics, dependency installation, actual data/auth databases, secrets, unrelated primary-workspace changes and runtime configuration.
- Dependency: PR #67 tested main and successful publication. Its continued observation must finish before this task is deployed. Each task is committed, pushed, reviewed, merged, checked on exact main, backed up and published separately.

## Resulting behavior

Default RuntimeStore resolves the state-file path and acquires a nonblocking OS lease on its physical parent directory before reading JSON. The second Store, another process and alternate snapshot filenames in that directory fail explicitly before loading, quarantining or saving. Junction/symlink aliases share the same lease. No automatic fallback to another data directory or read-only runtime exists.

Windows keeps a non-inheritable Global named kernel-object handle. Object creation/opening detects an existing holder; the handle can be closed by a different thread. POSIX holds flock on a fixed sidecar inode, retained after close. Fork callbacks close inherited descriptors without unlocking the parent's open-file description; inherited stores cannot write or wait on an inherited store lock when closed. This coordinates cooperating local processes, not remote hosts sharing a network filesystem.

All mutation and persistence entry points reject read-only, closed or inherited writers before modifying records or files. Explicit close, object collection and process death release the lease. Constructor load errors also release it. Existing successful business responses and disk serialization stay unchanged.

The internal read_only=True option reads a one-time snapshot without acquiring a writer lease, creating directories, quarantining malformed JSON or saving migrations. Legacy migration still affects only the decoded in-memory snapshot. Record getters retain their existing object semantics; persistence/mutation methods reject writes. It is not a replacement for a live business store or a transactionally consistent cross-file audit while external layers change.

Existing readback tests use read-only snapshots. Tests that really restart and then mutate release the previous writer first. Existing assertions are retained; fault tests still exercise real load/migration failures rather than merely encountering a busy lease.

## Evidence and limits

- First related regression run: 155 passed, 2 skipped, 21 subtests passed in 50.94s. Subsequent review added guards around private persistence paths and close handling for an inherited lock.
- Final focused writer/store/recovery/layer run: 47 passed, 1 skipped in 2.35s.
- New tests exercise real local Windows kernel leases across separate hidden child processes, two-process races, process death, thread-independent close, finalizer release, constructor errors, read-only zero-effect refusal and a real synthetic Junction. POSIX fork acceptance is separate CI evidence.
- Full local backend regression: 1196 passed, 8 skipped, 176 subtests passed in 364.21s. Exact PR/main CI results are recorded before publication.
- PR #67 publication completed more than fifteen minutes of repeated healthy operational checks before this task's integration; no authenticated business acceptance claimed.
- No real model/vision calls, production duplicate-start experiment, actual QGIS/COM, authenticated browser or teaching-flow field acceptance. Health and static source checks do not prove these.

Deployment requires verified previous process exit, fresh offline backup, exact tested main and normal startup. No data restore, data-root move or additional API workers. Code rollback keeps current teaching data and the previously confirmed resource-binding fixes.

Unrelated workspace changes, original documents and production data were not modified by implementation/tests. Operational paths, process IDs and production hashes stay in local release evidence.

## API references

The implementation follows the documented named-object lifetime, existing-object error and non-inheritable handle rules in [CreateMutexW](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-createmutexw), the cross-session [Windows kernel-object namespace](https://learn.microsoft.com/en-us/windows/win32/termserv/kernel-object-namespaces), and Python 3.12's nonblocking [flock](https://docs.python.org/3.12/library/fcntl.html) contract.
