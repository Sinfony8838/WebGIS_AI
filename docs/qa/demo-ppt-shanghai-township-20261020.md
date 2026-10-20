# Demo population lesson migration acceptance (2026-10-20)

## Ownership and scope

- Branch: `codex/demo-ppt-shanghai-township`.
- Starting commit: `c9136df205d58372bfd07ef9aa38aaea7932799f` (current `origin/main` when this worktree was created).
- Objective: import a private 31-slide population lesson and Shanghai township population counts into an existing demo classroom.
- Allowed source paths: the two import/migration scripts, their backend tests, and this acceptance note.
- Forbidden: the primary checkout's dirty files, shared integration modules, original Office documents, other accounts, existing lesson contents, credentials, and historical artifacts.
- Dependencies: Python 3.12, openpyxl, Shapely, the existing RuntimeStore and lesson normalizer. Slide previews were exported separately by local PowerPoint from a read-only copy.

## Changes

- `scripts/import_shanghai_township_population.py` validates the Shanghai worksheet, keeps special statistical units and null counts, reconciles city/district age totals, and joins polygons by district/name with explicit historical aliases. It rejects missing/duplicate keys, invalid counts, wrong units and lossy geometry repairs.
- `scripts/migrate_demo_population_lesson.py` performs a read-only preflight unless `--apply` is supplied. Writes require an exclusive runtime writer lease, existing account/project ownership, state/auth backups and unchanged-record checks. It appends an owned lesson, a classified population layer and owner-specific file grants. Existing migrations and layer IDs are never overwritten.
- Imported slides use the existing full-frame classroom presentation surface. Original text and slide order remain available. Stages 7/8 include the Shanghai reference scene and a six-class count legend through existing rendering contracts.
- `backend/tests/test_demo_population_import.py` covers count reconciliation, malformed input, cross-district duplicate names, special units, nulls, boundary conflicts, historical aliases, unsafe geometry repairs, page order and scene intent.

Private PPTX/XLSX inputs, extracted values, boundary archives, screenshots, backups and runtime records are not included in Git or this PR.

## Operational results

- 31/31 native PowerPoint PNG previews generated. All authenticated image responses matched their export hashes; anonymous file access returned 401. Original PPTX and XLSX hashes were unchanged.
- 226 Shanghai statistical units across 16 districts; total 24,870,895 people. All six numeric fields were independently read back against the original source rows, preserving missing values. All district/city population and age subtotals reconciled.
- Four boundary-name aliases and two topology repairs are explicitly recorded in the private receipt. Three boundary-only development-zone records without separate source-table rows were not counted again.
- Existing lesson records, other projects, user records, auth settings and existing file grants were preserved. Browser checks used temporary operator validation sessions; all were revoked without revoking existing sessions. Test classrooms were ended and retained as evidence.
- Deployed application code remained on its existing mainline build. No source deployment or replacement of runtime data was performed.

## Validation

- Full backend gate: `python -m pytest backend/tests -q` — **1414 passed, 8 skipped, 190 subtests passed**, 436.91 seconds.
- After the final scene-intent edit: affected import/presentation/Shanghai suites — **32 passed**, 1.80 seconds. The allow-existing-data override referred only to test-generated data inside the task worktree, never production data.
- `git diff --check` — passed.
- Local browser checks against the real deployed Caddy/FastAPI origin: demo lesson selection; real class start; pages 1, 2, 8, 17, 26, 31; next/keyboard-previous navigation; browser reload recovery; settled plane-mode map and count legend; class end; teacher-only rules report generation and authenticated report download. No page JavaScript errors. The report did not call an external model.
- The existing 3D globe and UI shell were visually present before the Shanghai scene. Existing TOP20 visual-query and startup/health/classroom regression paths passed in the backend gate. Both local health endpoints returned 200.
- No frontend source was changed; no new frontend build was required for this operational import.

## Limits and follow-up

- These are population **counts**, not density. The workbook contains no township areas. Third-party historical boundaries are reference geometry: the 2019 Changhai/Wujiaochang boundary adjustment is not reconstructed. This limitation is stored on every mapped feature and in the layer metadata; the short legend title is `2020街镇人口总量`. Do not use the polygons for precise boundary/area analysis.
- Web preview uses native static page exports. PowerPoint animations, transitions and live handwriting were not verified by this browser check; the original deck is retained.
- During the initial verification, the external public domain returned HTTP 403. Local browser requests used an explicit domain-to-local-origin routing adapter. This is local authenticated browser evidence, not public-network acceptance or a password-login test.
- At 1600 px width, the existing account dock overlaps the pointer target of the bottom previous-stage button. Keyboard previous navigation and the left stage list worked. No unrelated UI redesign was made.
- The population layer is installed in the selected existing demo population classroom. A different/new classroom project needs its own layer import; lesson-image ownership remains account scoped.
- Source-only PR remains for integration-owner review. Runtime data and backup locations are retained privately rather than published.

No unrelated workspace changes were modified, staged or committed.


## Review corrections before integration (2026-10-20)

Integration was held after the three review findings; the migration was not rerun on real teaching data.

- Loading and backup ordering: the migration no longer constructs RuntimeStore (even its read-only loader filters legacy layers in memory). It acquires StateWriterLease directly, verifies a backup of the original JSON, referenced external layer files and SQLite auth database, and writes `backup_manifest.json` with `complete=true` before creating assets, grants or replacing state. It appends to the raw snapshot with atomic JSON replacement, retaining existing legacy layers, query results, templates and external references. It does not change normal application startup behavior.
- Slide order: ordered references in `ppt/presentation.xml` are resolved through `ppt/_rels/presentation.xml.rels`. Missing, external, duplicate or invalid slide relationships fail; reordered-slide text is paired with the native page-number preview.
- Preflight: all stages and new records are built and serialized, and all required package files are checked, before dry-run success or any apply-side writes. Bad counts, lists, ordering, missing assets/CSV and missing relationships fail with state, auth, grants and outputs unchanged.
- The requested legend title is exactly `2020街镇人口总量`; historical-boundary and count/density qualifications remain in feature/layer metadata.

Validation after these corrections:

- Import, lesson-presentation and Shanghai-data suites: **51 passed**, 4.13 seconds. New isolation tests include target/unrelated legacy rectangle and visual-query layers, external files, a held writer lease, failed/corrupt backups, preflight state changes, dry-run/apply rejection controls and actual reordered slides.
- A new isolated instance was reconstructed from the retained pre-import state/auth backup and 11 referenced external layer files. The corrected script completed dry-run and apply against this copy using the private real package: **31 slides, 226 units, 24,870,895 people**. Removing only the added lesson/layer and the target timestamp reproduced every original record exactly. Original backup and external layer hashes were unchanged; the new backup manifest and all copied hashes passed. Real runtime JSON hashes before and after the rehearsal were identical.
- The supplied real PPTX currently has matching filename and presentation order; all 31 existing lesson text fields agree with relationship-ordered extraction. No real lesson rewrite is required.

These corrections are source changes plus isolated rehearsal evidence. They do not establish distributed transactionality across JSON, SQLite and file copies: a later disk/permission failure can still leave partial new assets/grants, and must be recovered deliberately using the verified backup. Do not retry into an existing migration output directory. No real-data migration was run during this review repair, and unrelated workspaces remain untouched.
