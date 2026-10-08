# Real browser acceptance: lesson title and class duration

- Branch: `codex/real-acceptance-lesson-metadata`.
- Starting main: `25560014117fb5f902ffce591d994440686ebf84`.
- Scope: lesson design service, its regression tests, and this record.
- No frontend, endpoint, persistence-format, lesson-publication gate, or original classroom data migration.

## Verified behavior and cause

In the authenticated public Demo UI, a blank synthetic design was created, manually renamed to an acceptance title, and given a three-minute class duration.
The next requirements turn reverted its title to the old topic and treated “每环节1分钟” as a one-minute class duration.
The direct title-edit path updated title but left topic unchanged; requirements normalization preferred the stale topic.
Duration parsing took the first numeric minute phrase without distinguishing per-stage instructions from total class time.

## Changes

- Direct title edits synchronize the topic used by follow-up generation.
- Requirements follow-ups prefer the saved title; explicit new title requests still work.
- Support explicit “标题必须为” and give explicit title declarations precedence over generic course phrasing.
- Prefer declared total class time and skip per-stage minute instructions in total-duration parsing.
- Preserve model duration suggestions when no per-stage instruction or exact total was supplied.
- Keep existing data formats and confirmation / publication / rehearsal gates.

## Validation

- Two new regression cases failed before the fix, matching the browser observations.
- Intermediate focused lesson service / API checks: 55 tests and 21 subtests passed.
- Final full backend: 1300 tests passed, 8 skipped, 178 subtests passed in 402.18 seconds.
- Tests use synthetic temporary storage and mocked model responses; no real model call during unit validation.
- A separate real UI teaching draft used clearly labeled synthetic content. Published-browser regression for this patch is required after deployment.
- Test-generated data from prior runs was retained in the task's scratch directory before using a clean test data root; no production Junction or authentication database contents were read.
- The primary dirty checkout and unrelated files were preserved.

## Boundaries

This fix handles explicit integer-minute class duration and per-stage phrases such as “每环节1分钟”; it does not claim unrestricted natural-language schedule understanding.
Published rehearsal / classroom / report acceptance and external-service behavior remain separate from the unit evidence.
Runtime data must be preserved on code rollback. No production restore or failure injection was performed.
