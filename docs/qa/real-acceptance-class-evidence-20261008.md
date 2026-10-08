# Real browser acceptance: classroom screenshot primary save

- Branch: `codex/real-acceptance-class-evidence`.
- Starting main: `c2e457911f81786e9e729323326e55668498161f`.
- Scope: App screenshot callback, ScreenshotSelector, its tests, and this record.
- No backend, public API, storage format, original lesson migration, or GIS changes.

## Verified problem

In the real public Demo browser, a clearly labeled synthetic lesson was published, rehearsed, taught through three stages, and ended.
The teacher clicked classroom "截图存证", selected the whole page, and clicked "保存 PNG".
The resulting report correctly counted three questions and three observations but contained zero classroom screenshots.
The primary save callback only downloaded the PNG and cleared the draft, bypassing the existing database export and snapshot event path.

## Change

The frozen screenshot document already records the originating session and stage.
When that document carries classroom evidence, the selector exposes "保存课堂存证" and invokes the existing database persistence callback, which exports the artifact and logs its snapshot event.
Ordinary toolbar screenshots retain "保存 PNG" and local-only download behavior.
The existing crop, cancellation, busy guard, destination dragging, project binding, and frozen capture metadata remain in use.

## Validation and boundaries

- Focused ScreenshotSelector / classroom scene orchestration: 13 tests passed.
- Full frontend: 90 files / 697 tests passed in 20.22 seconds; production build passed in 4.29 seconds; diff check passed.
- Regression tests verify that classroom primary save bypasses local-only download and is disabled during an in-flight save; existing local download tests remain.
- Published-browser validation must confirm both the screenshot artifact and the correct session's snapshot event, then generate a report containing that screenshot.
- A separate browser test is required for ordinary local-only screenshot saving.
- No production fault injection or data restore is authorized by this fix; code rollback preserves teaching data.
- Original dirty workspace and original classroom records were preserved.
