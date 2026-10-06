# Stage 2a: preserve runtime snapshots on load and migration failure

## Scope and baseline

- Branch `codex/stage2-store-recovery`, starting main `c476bf2f211ac592a9665ef5a026b5700d9afd86` (S3, PR #65).
- Dedicated clean worktree `C:/Users/zcyxn/.codex/worktrees/stage2-store-recovery/WebGIS-AI`; AGENTS.md read and branch/HEAD/status recorded before editing.
- Allowed: backend/app/store.py, new backend/tests/test_store_recovery.py, this record.
- Forbidden: public APIs/persistence formats, frontend, dependencies, real runtime/auth data, credentials, GIS math, providers and original documents.
- Dependency: S3 merged, main CI successful and exact release started with operational checks before editing. Single-writer enforcement and frontend restoration are separate tasks.

## Behavior and acceptance

Separate file reading, JSON decoding, record validation, external-layer hydration, legacy migration and persistence. No broad exception handler labels I/O or programming failures as corrupt schema. Decode all record collections into temporary dictionaries before publishing a snapshot; old memory survives failed decoding or hydration. Existing legacy conversation defaults and null lesson plans remain compatible.

Permission/other I/O failures, unsupported encoding/schema and migration errors propagate while retaining the original snapshot bytes. Unsupported fields may come from a later format, so schema incompatibility stops startup without automatically moving the file or enabling empty-store writes. A failed migration save retains decoded records; the existing atomic writer retains old disk bytes. External-layer transient I/O now aborts loading instead of hiding the failure behind an incomplete layer. Historical missing/corrupt external JSON placeholders and path containment behavior remain unchanged.

Confirmed bad JSON retains the existing quarantine/recovery contract. Quarantine rename failure now aborts instead of allowing startup against an empty store beside an unpreserved bad file. No automatic production restore is added.

- 22 new synthetic cases cover state read denial, unsupported encoding and seven schema cases, decoder bugs, failed quarantine, migration/write/replace failures, external-layer I/O and legacy defaults. Assert exact retained bytes, no false corruption archive and no partial collection publication.
- Positive checks: existing store/layer persistence tests, legacy demo migration, conversation defaults and lesson plan compatibility.
- Focused store recovery/store/layer persistence suite: 32 passed in 1.26s. Full local backend suite: 1181 passed, 7 skipped, 176 subtests passed in 420.45s. git diff --check passed; repeat after staging. PR/main CI and publication remain pending.
- No real data fault injection, authenticated browser, QGIS/COM/model calls or production restoration acceptance.

## Previous release evidence and handoff

S3 PR #65 merged as c476bf2f211ac592a9665ef5a026b5700d9afd86; tested branch da33b6e had the same source tree. PR backend CI: 1157 passed, 9 skipped, 176 subtests passed (154.27s); frontend tests/build and main CI succeeded. Local full suite: 1157 passed, 7 skipped, 176 subtests; final image suite: 49 passed, 1 skipped including two passing synthetic Windows Junction checks.

Fresh offline complete backup: C:/Users/zcyxn/Desktop/WebGIS-AI-backups/20261006-210152-531-e7553554c8f9, 480 files / 582955106 bytes. No data restore. Final corrected startup uses scripts/configuration in the fixed publishing checkout; backend 45312 and Caddy 18196, launcher parent 38956, ports 18999/18080. Exact release timestamp 2026-10-06T21:03:55.0640508+08:00. Checker: 12 checks, zero failures, one proxy DNS warning, local/public HTTP 200. Unchanged frontend bundle local/public SHA256 60F3802A04B268BFBEE1CD8F5E7A6B90AA04AE1445B34FC84F461AE5E924307F.

Stage only the three allowed paths; leave primary dirty checkout and unrelated changes untouched. Record exact CI/main SHA, fresh offline backup and operational checks before publishing. Code rollback preserves new teaching data; data recovery is a separate decision. Do not restore the broad exception-to-empty behavior as routine recovery.
