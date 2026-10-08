# Real browser acceptance: zero-width vector outline

- Branch: `codex/real-acceptance-zero-stroke`.
- Starting main: `32b6b213d97fa4416be73c04d2e70e7512bea82e`.
- Scope: OpenLayers rendering adapter, its regression tests, and this record.
- No backend, GIS analytical attributes, persistence format, or original classroom records changed by this patch.

## Verified defect

A synthetic three-point GeoJSON was imported through the authenticated Demo UI.
Point B had `__fillOpacity: 0`, `__strokeWidth: 0`, `__radius: 12`, and `__hideLabel: true`.
The actual 2D map still showed a white outline while red point A and green point C remained visible.
This was a browser rendering observation, not only a style-property assertion.

OpenLayers RegularShape calls Canvas stroke when a Stroke object exists.
Canvas ignores an invalid zero lineWidth assignment, so storing width zero does not guarantee invisible strokes.
The adapter now omits the Stroke object when the resolved width is zero for points, lines, and polygons.
Positive outlines, transparent fills with positive outlines, population styling, and labels retain their existing behavior.
Cesium and the shared style resolver are unchanged.

## Validation before integration

- Focused `vectorStyle.test.ts`: 28 tests passed.
- Full frontend: 90 files / 695 tests passed.
- `npm run build`: passed; existing chunk-size advisory remains.
- `git diff --check`: passed.
- Added nonzero-radius transparent-point cases for both layer overrides and feature decorations.
- Added positive-outline / zero-fill coverage to prevent removing legitimate outlines.

## Acceptance boundary

Published browser verification of the changed asset is required after deployment.
The original class must retain its lesson and stage, and point B must disappear while A and C remain visible.
Actual 3D pixel behavior and complete classroom/GIS/PPT acceptance are tracked separately; this unit suite does not prove them.
No production fault injection, restore, dependency installation, or authentication-data inspection was performed.
The primary dirty workspace and unrelated files were preserved.
