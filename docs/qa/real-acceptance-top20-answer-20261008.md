# Real browser acceptance: authoritative TOP20 answers

## Baseline and scope

- Branch: `codex/real-acceptance-top20-answer`.
- Starting main: `a70783fc533fa7d3ceb44220623729b53f0b9ca8`.
- Dedicated clean worktree; no production data or dependency Junction.
- Allowed: assistant parameter schema, runtime query response, session answer composition, assistant regression tests, this record.
- Forbidden: population data, GIS calculations, API/state formats, original classroom records, private files, credentials, unrelated dirty checkout changes.

## Observed defect

Real authenticated Demo browser acceptance of a marked synthetic classroom returned a correct 2020 population TOP20 chart and generated layer. The assistant text instead placed Wuhan before Xi'an, included cities absent from the returned top twenty, and gave a different Hangzhou population. This was a real contradiction between two outputs of the same completed request, not a population dataset defect.

The session engine displayed the model's planning text after execution. Teaching/hybrid modes could additionally ask the knowledge engine for a separate explanation without providing the executed ranking rows. An earlier request also supplied the unsupported model-chosen dataset `census` and failed; no mapping to a different dataset is authorized.

## Change and preserved behavior

- Render every returned rank, name, exact integer value and unit from the visual query's executed items.
- Query requests, including confirmation execution, use executed tool outcomes and omit the independent ungrounded explanation. Other teaching answers and explanations remain unchanged. Mixed actions retain their actual outcome text.
- Advertise and validate the existing canonical dataset and supported `population` alias; omission retains the existing default. Unsupported datasets remain rejected before tool execution.
- Preserve query rows, geometry, chart, layer IDs, year/scope checks, task states and persistence formats.

## Acceptance

Regression tests exercise deliberately false planning text in tool and teaching modes, confirmed query execution, persistent conversation text, and rejection of unsupported datasets without query execution. Existing assistant and visual query tests remain part of the focused suite. Full backend checks and exact-head CI gate integration; published browser verification must independently compare all twenty displayed facts with the returned chart rows after deployment.

No unrelated workspace changes or original classroom records were modified by this source change. Offline backup and verified deployment preserve existing teaching data. Browser findings from other scenarios and release-specific outcomes are recorded separately in the local acceptance evidence and PR.
