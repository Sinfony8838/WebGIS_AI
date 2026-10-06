# Stage 2b: preserve the classroom project pointer on failed reads

## Scope

- Branch codex/stage2-project-recovery, starting main 04286a9f129a2e7f0cc8a58c4f81c1f8466f17c8 (PR #66).
- Dedicated clean worktree C:/Users/zcyxn/.codex/worktrees/stage2-project-recovery/WebGIS-AI. AGENTS.md, HEAD, branch and clean status checked before edits.
- Allowed: frontend/src/App.tsx initialization/error controls, new frontend/src/lib/projectRecovery.ts, new frontend/src/__tests__/projectRecovery.test.ts, this record.
- Forbidden: backend, API/auth/storage-key formats, GIS/map/lesson behavior, unrelated App code, real runtime/auth data and dependency installation.
- Existing frontend dependencies are linked from the primary checkout only after matching package-lock.json SHA256 E27A582D30E447C52B580F00488A743DA598CFFC820CD72F8EBC9495411EEB83. No data Junction in this task worktree; no dependencies installed/updated.
- Dependency: Store fix merged, main CI successful and operational deployment checks completed before source edits. Aggregate snapshot request-order protection and single-writer enforcement remain separate tasks.

## Behavior and checks

The saved-project GET either restores the original project or reports its error. No HTTP status, network failure or JSON failure automatically initiates POST /projects or replaces the saved pointer. Retry continues using the old pointer. First visits still create a project. If the teacher wants a replacement after initialization failure, the visible New classroom project button records a one-shot choice for the current user; data in the old project is retained. Creation replaces the pointer only on a successful, still-current response. Failed/cancelled creation retains the old pointer. Cancelled initialization also stops stale error/toast commits.

The helper preserves the existing API/auth client and storage keys, and accepts the effect cancellation guard. It does not add request retries, replay tasks or change the aggregate map/project state contract.

- 16 new synthetic tests: original restoration; HTTP 400/401/403/404/429/500/503, network and JSON failures; retry with the original ID; first/explicit creation success and failure; cancelled initial/in-flight reads and creation.
- Focused restoration suite: 16 passed (6.77s). Full frontend: 86 files / 606 tests passed (30.86s). Production build passed: TypeScript plus Vite, 499 modules, build 3.69s. Existing chunk-size advisory remains; no performance defect is inferred from it. git diff --check passed. PR/main CI and deployment pending.
- Real authenticated browser/classroom, model, QGIS, Office/COM and production restore acceptance not claimed.

## Previous release and handoff

Store PR #66 merged as 04286a9f129a2e7f0cc8a58c4f81c1f8466f17c8; source tree identical to tested a44001c. Local focused 32 passed; full 1181 passed, 7 skipped, 176 subtests passed. PR CI backend 1179 passed, 9 skipped, 176 subtests passed (168.93s); frontend and main CI successful.

Offline complete backup C:/Users/zcyxn/Desktop/WebGIS-AI-backups/20261006-212623-656-c476bf2f211a: 478 files, 582922338 bytes; no restore. S3 observed healthy beyond fifteen minutes. Store release timestamp 2026-10-06T21:27:06.2712892+08:00; backend 33408/Caddy 29852, verified launcher parent 6384 and fixed publishing paths/listeners. Checker 12 checks/0 failures/1 proxy DNS warning, local/public HTTP 200. runtime.json opaque SHA256 after startup matched the stopped-service backup exactly: 5C0D3F569971EA1A4335A9471DDA18439EA7AD7A673C1673F45224869C01865D; no snapshot/auth database contents read. Frontend local/public SHA256 60F3802A04B268BFBEE1CD8F5E7A6B90AA04AE1445B34FC84F461AE5E924307F.

Only four explicit paths may be staged. Primary dirty files, original documents and production data remain untouched by implementation/tests. Integration requires exact CI/main identity, fresh offline backup and retained previous frontend build before publication. Code rollback retains new teaching data; no automatic data restore.
