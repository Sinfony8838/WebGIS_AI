# Stage 5a: shared vector display contract

Branch: `codex/stage5-map-style-contract`. Starting main: `06b4fe57dda35feb4a96166fef4f91495f1bc152`.

Objective: align normal 2D/3D vector style interpretation and preserve valid zero values, before changing geometry loading or caching.

Allowed files: `frontend/src/App.tsx`, `frontend/src/components/Map3DGlobe.tsx`, new `frontend/src/lib/vectorStyle.ts`, new `frontend/src/__tests__/vectorStyle.test.ts`, this record. Forbidden: backend, endpoints/IDs, GIS classification/math, persistence formats, dependency installation, production data, private assets and unrelated cleanup. Shared App edits remain with this task's integration owner.

## Behavior and preserved contracts

- Both adapters use layer overrides, then decorated feature properties, then the existing 2D defaults. Valid numeric zero and numeric strings survive; invalid/nonfinite/negative inputs fall back to valid feature/default values. Colors use the existing OpenLayers CSS parser, with invalid overrides falling back safely.
- Polygon fill alpha combines CSS alpha with fill opacity. Existing nonzero 2D point opacity boost and point outline width remain; explicit zero fill, width or radius is respected. Cesium also multiplies by layer opacity, including zero, and applies stroke color/width instead of ignoring layer overrides.
- Existing density/Shanghai display colors, radii, TOP20 ranking colors, special-layer precedence, Hu-line visibility/dashes and province label suppression are retained. No analytical attributes, coordinates, thresholds, classifications or saved style data are rewritten.
- The old 2D style factory and small 3D rendering loop are adapted through one bounded module. Layer loading/filtering, basemap, thematic manager, camera/altitude gestures, screenshot handles, map/brush controls and classroom entry points remain unchanged. Cesium geometry revision caching is a separate follow-up.

## Validation

- `npm test -- src/__tests__/vectorStyle.test.ts src/__tests__/populationVisual.test.ts src/__tests__/MapEvidenceLegend.test.tsx src/__tests__/globeGeojson.test.ts src/__tests__/choroplethReplay.test.ts --maxWorkers=2 --minWorkers=1`: 5 files / 57 tests passed in 5.42s.
- Twenty-five new cases construct real OpenLayers styles/layers and Cesium Entity/GeoJsonDataSource/graphics/material objects from synthetic values. They compare effective colors/alpha, override precedence, zero/numeric/invalid values, existing teaching rules and immutable source properties; no Viewer, network, WebGL or external service is created.
- Full `npm test -- --maxWorkers=2 --minWorkers=1`: 89 files / 663 tests passed in 64.52s. No skips or relaxed timeouts. `npm run build`: 501 modules, success in 4.95s; existing bundle-size advisory remains. `git diff --check` passed.
- Backend source is unchanged, so local backend tests were not repeated. Exact PR and merged-main quality gates must include the full backend and default frontend tests/build before publication.

These checks establish rendering-object contracts, not pixel-identical WebGL output, hardware-dependent clamped polygon outline widths, actual classroom projection, camera/screenshot device behavior or real GIS/provider acceptance. No dependency installation, real model/QGIS/COM call or production data restore occurred.

The preceding published source/build was recovered on resuming work after both origin processes were absent and public requests returned 530. Old release/log evidence was retained, a new verified offline v2 backup taken, the same source/build restarted, and only the identified tunnel restarted after error 1033 was confirmed. Startup state bytes matched the backup. Exit cause remains unknown; operational observations are recorded separately in PR 74. Recovery evidence under this task's untracked scratch directory is not source and is not staged.

Code rollback retains newly created teaching data and preceding security/recovery fixes. No primary-checkout or unrelated workspace changes were modified. Publication/backup/public checks and the preceding release's renewed fifteen-minute observation are required before this task's deployment; final evidence belongs in the PR.
