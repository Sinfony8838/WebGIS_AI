# Real browser acceptance: TOP20 city focus

- Branch: `codex/real-acceptance-top20-focus`; starting main `65b357fbf5780562ba18b162515bd04442d19a54`.
- Dedicated clean worktree. Existing dependencies linked from a separate acceptance worktree with a physical node_modules directory; no installation or production data link.
- Scope: App map callback, LessonWorkflowShell chart wiring, visualization administrative-code type, city-selection helper, focused tests and this record.
- Forbidden: ranking values, geometry edits, runtime data, backend APIs, original classroom events, private assets and unrelated workspaces.

Actual published browser clicks on “定位到 西安市” selected the row but left the map at its previous extent. The shell callback only called onRefresh and discarded the selected city. The correct ranking chart therefore did not provide the advertised map navigation.

The fix selects a single feature by its administrative code, or by matching both rank and name for older rows, and passes a temporary record to the existing App focusLayerExtent adapter. Two-dimensional fit/highlight and three-dimensional flyTo remain owned by that adapter. The complete ranking layer is not replaced or modified. Missing matches or geometry produce a visible error rather than focusing an unrelated city.

Regressions cover reordered features, rank changes, missing geometry/code, same-rank wrong-name protection, no original-layer mutation, and the selected row reaching the map callback without refreshing classroom state. Focused frontend: 16 tests passed. Full frontend: 91 files / 701 tests passed in 38.88s. The first build caught a missing type-only import; that import was corrected and the final TypeScript/Vite build passed in 4.49s. Exact-head CI and actual 2D/3D city navigation must pass before published acceptance is complete.

No unrelated workspace changes or original classroom records were edited. Browser acceptance will retain before/after screenshots and independently compare the original classroom records and complete ranking layer data.
