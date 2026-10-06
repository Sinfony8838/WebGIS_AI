# S3: project-bound assistant image references

## Task baseline and scope

- Branch: `codex/stage1-image-binding`; starting main: `e7553554c8f94dfea81d62303e9bb5ee72d96f6d` (S2b, PR #64).
- Dedicated clean worktree: `C:/Users/zcyxn/.codex/worktrees/stage1-image-binding/WebGIS-AI`; branch created before source edits.
- Allowed paths: `backend/app/runtime.py`, `backend/app/services/session_engine.py`, `backend/app/services/vision.py`, new `backend/app/services/image_references.py`, new `backend/tests/test_assistant_image_binding.py`, `backend/tests/test_vision.py`, this record.
- Forbidden: frontend, public request models, Store formats, historical artifacts, real data/credentials, GIS algorithms, dependency installation and real model calls.
- Dependency: S2b merged, main CI passed, deployed and operational checks succeeded before this task's source edits. Earlier conversation/session/lesson checks remain active.

## Boundary and behavior

Image references are resolved from registered artifact IDs. Check the project, artifact owner/type and its physical project upload/output directory before opening the registered image. Client path, MIME, title and public URL fields do not choose the file. Only 32 bytes are read to validate the existing supported signature/suffix rules. Physical root resolution accepts the known production data-root Junction while retaining the project component so a file or project link cannot redirect to another project's directory. Validation does not call directory-creating configuration helpers.

The same resolver covers top-level attachments, embedded single/list references, internal engine and tool entry, historical image follow-up, legacy/frozen confirmation approval/rejection and the final vision-service call. Both overridden embedded references and the selected top-level reference are checked. Canonicalization returns new dictionaries and never rewrites stored plans or their fingerprints. Normal messages without an image retain their context. Image-derived vision fields are cleared before a fresh provider result to avoid using stale or client-supplied visual answers.

Historical follow-up is resolved before conversation grounding, compression or user-message writes. A stale/missing/foreign reference or a raw path without artifact ID is rejected before a new Job or thread. Valid same-project follow-up continues using the registered current file. Existing uploaded/generated/snapshot types, one-image-per-message limit and supported PNG/JPEG/WebP/GIF formats remain unchanged. No historical files or production records are moved.

MapVisionService's persisted-image entry also revalidates project and artifact ID immediately before provider use. Its legacy image_path argument remains accepted syntactically but does not select a file. An unbound service or call lacking IDs returns an unavailable result without resolving/statting/opening a raw path. The screenshot/map entry is unchanged. The two existing image-prompt tests now register real synthetic PNGs in a project directory; prompt assertions remain unchanged. Runtime MIME names remain available through imports of the shared definitions.

## Acceptance

31 new synthetic cases cover top/single/list paths, raw-path non-probing, canonicalization, supported types, unknown/wrong-type/missing/corrupt/outside/cross-directory references, symlink redirection, historical memory, legacy/frozen confirmations, direct knowledge/tool entry, the vision-service boundary and HTTP rejection before Job/lesson-design creation. Negative cases assert persistent state bytes and provider calls; provider clients are mocks. Original image-library follow-up/failure behavior and image-prompt tests run in the full suite. Two Windows-only cases use temporary synthetic Junctions: a data-root link is accepted and a project directory redirected into another project is rejected.

- Full local backend suite before the two additional Junction cases: 1157 passed, 7 skipped, 176 subtests passed in 388.37s.
- Final image-binding/image-library/vision focused suite including both Junction cases: 49 passed, 1 skipped in 19.07s.
- `git diff --check`: passed before the suite; repeat before commit.
- PR/main CI and publication: pending integration.
- The file-symlink test was skipped because os.symlink raised OSError on this machine. Both real Windows Junction cases passed using only fixture directories; the production Junction was not used for testing.
- Not performed: authenticated browser/classroom acceptance, real vision/LLM calls, real QGIS, Office/COM, load testing or production data restoration. Tests never run in the production Junction checkout.

## Previous step release evidence

S2b PR #64 merged as `e7553554c8f94dfea81d62303e9bb5ee72d96f6d`. PR CI: backend 1128 passed, 7 skipped, 176 subtests passed in 164.44s; frontend tests/build passed. Main CI passed. Local full suite: 1126 passed, 6 skipped, 176 subtests passed; final S1/S2 focused suite: 74 passed, including all 33 new lesson authorization cases. Branch and squashed main had identical source trees.

S2a completed more than fifteen minutes of observed healthy operation before the S2b release. Fresh stopped-service v2 backup: `C:/Users/zcyxn/Desktop/WebGIS-AI-backups/20261006-203305-367-c80522410ab3`, 478 files, 582922338 bytes. Previous managed processes were checked by exact PID/command/listener identity before stop. No data restore occurred.

S2b started at `2026-10-06T20:33:50.2195794+08:00`, exact SHA in release metadata. Python PID 40708/Caddy PID 47732 uniquely owned ports 18999/18080; verified common launcher parent 44108. The production data Junction was retained. Release checker: 12 checks, 0 failed, 1 proxy Fake-IP DNS warning; local/public health/root HTTP 200. Unchanged frontend bundle `assets/index-4D9ECoLu.js` had matching local/public SHA256 `60F3802A04B268BFBEE1CD8F5E7A6B90AA04AE1445B34FC84F461AE5E924307F`.

## Handoff and rollback

Only the seven declared paths may be staged. Runtime data, original documents and the primary checkout's existing dirty files remain outside this task. Synthetic test data is retained locally and never committed. Publication requires exact main/CI identity, fresh complete offline backup, managed-process verification, health/assets/log checks and observation. Preserve new teaching data during code rollback; never restore a confirmed arbitrary-file/cross-project image boundary as a routine fallback.
