# Project presentation library acceptance — 2026-10-21

## Ownership

- Branch: `codex/project-ppt-library`; starting commit: `163c25c565745b60d0aa8c44d2adb73beb3ab514` (live `origin/main` rechecked before creation).
- One implementation owner. Scope: project presentation service/routes, static renderer integration, App/PPT controls and viewer, persistence/cache helpers, corresponding tests, this note.
- Forbidden: primary checkout changes, production/runtime state, private original Office files, other tasks' branches/caches. No production migration or deployment was performed.

## Behavior

- A single header icon opens the current project's presentation list with covers, titles and page counts. Registered lesson exports and accessible linked project materials are included; orphan preview directories are not scanned.
- Selection preloads the target page before replacing the active deck. Stale selections are cancelled. Per-deck page, width, fullscreen and ink are saved in IndexedDB with actor/project/source/version keys; live undo history survives deck switches. Undo history itself is not persisted across browser reloads.
- Private image responses retain `no-store`. A bounded, actor/project-scoped object-URL cache preloads adjacent pages and releases URLs when the project changes. This does not introduce a public/CDN or persistent slide-image cache.
- Imports are registered by project/source SHA-256. Upload request IDs and render jobs are idempotent; lost POST responses are recovered by GET, not replayed. A restart marks interrupted work as failed and requires explicit retry.
- New project imports require native PowerPoint export in the existing Windows conversion environment. No silent LibreOffice/HTML fallback. Full page count, ordering indices, image decode and dimensions are checked before ready; authored font dependencies are recorded for review, not certified as installed or visually correct.
- Existing `/ppt/render` and desktop connector code remain compatible. The new App entry does not invoke the desktop connector. Static slides only; no animation/media acceptance is claimed.

## Automated results

- `npm test -- --maxWorkers=1 --minWorkers=1`: **95 files / 724 tests passed**, before the two final cache lifecycle tests were added. The default parallel invocation exhausted local memory (exit 134); this is not a test pass.
- Final affected frontend tests: **25 passed** across ProjectPptLibrary, pptSession, PptViewer and BrushHistory, including the restored file, actor/project cache controls, superseded page loads and failed-page retry.
- `npm run build`: passed; existing large-chunk advisory remains. Final verification is recorded in the PR/CI.
- First full backend invocation: **1463 passed, 8 skipped, 190 subtests passed, 2 failed**, 379.95 s. One failure exposed upload-ID alias reuse and was fixed. The other inherited `WEBGIS_AI_ALLOW_EXISTING_DATA=1` into a negative guard probe.
- Final affected backend render/library/bounded suites: **34 passed, 2 subtests passed**, including font dependencies, lost cached-page retry and disk-write failure cleanup. The isolation guard was rechecked without the inherited exemption: **4 passed** (one import-order warning). Clean full-suite results are recorded in the PR/CI.
- Full backend run includes classroom/session/report, visual query and startup/health regressions. Local isolated `/health` returned 200. This does not establish real browser acceptance of those flows.
- `git diff --check`: passed before staging; repeated before commit.

## Device and visual evidence

- Read-only production asset check: existing population deck **31/31 pages**, all **1920×1080**, page hashes and source hash match the import manifest. This establishes completeness/integrity, not visual fidelity.
- A loopback-only disposable instance was created from copied, hash-checked assets; no production auth/runtime store was reused. The real App displayed the project list/cover and opened the first slide beside the globe. DOM showed the native image at 1920×1080 with the original aspect ratio. Page 2 and fullscreen were reflected in DOM.
- **PARTIAL**: the in-app browser reported a Cesium fragment-shader compilation failure; screenshots stopped reflecting updated UI. This was not treated as a successful globe/fullscreen regression.
- Windows Computer Use then stopped because it could not determine the current browser URL confidently enough to enforce policy. No browser/native UI workaround was attempted after that stop.
- **UNRUN**: all-31-page visual comparison, real multi-deck/ink/refresh walkthrough, native new-import conversion smoke test, the 1920/1366/1280 × 100/125/150% matrix, and measured ≤1 s deck/≤100 ms page targets. Automated cases cover the corresponding state/error paths, not device rendering or timing.
- **RELEASE HELD**: keep the PR draft and production unchanged until those device gates pass. Existing connector availability is no longer a client prerequisite, but the server-side renderer still needs an operational Windows/PowerPoint import environment.

## Split-view header follow-up

- The user confirmed that the displayed PPT looks correct and supplied a split-view screenshot showing the global header overlapping the narrow map/PPT layout. This is human confirmation of that displayed slide, not completion of the full visual matrix above.
- Split playback now hides the global header and removes the viewer's reserved header offset at desktop and narrow widths. Collapsing the viewer restores the header through the existing split-mode state. The PPT's own controls remain available.
- Follow-up checks: the four affected frontend suites passed (25 tests); the QA frontend build and `git diff --check` passed. The first test invocation used nonexistent test paths and found no tests; the corrected invocation exercised all four suites.
- The local acceptance page was rebuilt. Browser automation could not initialize (`failed to write kernel assets`, OS error 3), so device verification of this layout change remains pending. No fresh screenshot or visual pass is claimed.

## Compact player follow-up

- Continued from `507de5c7d22b1056fee408f0aa03727a252af068` in the same dedicated branch/worktree. Scope is limited to `PptViewer.tsx`, `PptViewer.css`, its existing test file and this note; original assets, runtime state and the primary checkout remain untouched.
- Static playback replaces the full-width light header/footer with floating controls on a consistent dark canvas. A compact previous/page-select/next pager replaces the scrolling number strip. Fullscreen, collapse, brush controls and native aspect ratio remain available; the legacy HTML viewer keeps its existing controls.
- Scale calculation now reads the stage's actual padding so the entire page fits between the floating controls. New tests cover direct page jumps, focused select keyboard ownership, page-boundary buttons and aspect-ratio/safe-area fitting. Existing pending-load cancellation and failed-page retry tests exercise the new pager.
- `npm test -- --maxWorkers=1 --minWorkers=1 src/__tests__/PptViewer.test.tsx src/__tests__/ProjectPptLibrary.test.tsx src/__tests__/pptSession.test.ts src/__tests__/brushHistory.test.ts src/__tests__/PptBrushFloat.test.tsx`: **5 files / 32 tests passed**. QA `npm run build` passed (existing chunk-size advisory); `git diff --check` passed.
- The loopback acceptance frontend was rebuilt. The browser tool again failed to initialize (`failed to write kernel assets`, OS error 3), so fresh screenshots and the device layout matrix remain pending; automated geometry tests do not replace visual acceptance.

## Local recovery and handoff

- Disk exhaustion interrupted one new test-file write; the zero-length file was restored and retested. No incomplete test file is intended for commit.
- Only this task's freshly generated dependencies/build outputs were relocated to its D-drive QA area. An attempted preservation move of this run's `pytest-89` scratch tree encountered synthetic junction/readonly fixtures; residual files were retained and no further cleanup was attempted.
- Private decks, copied QA data, logs and any credentials are excluded from the PR. Only the declared source/tests/note are staged. No unrelated primary-workspace changes were modified, staged or committed.
