# Backend concurrency budgets

This batch preserves the legacy metadata backend and all HTTP resource IDs.
No production data migration or deployment is performed by these changes.

| Work | Running | Waiting | Deadline |
| --- | ---: | ---: | --- |
| Password hashing/verification, process-wide | 2 | 8 | Existing Argon2 work completes before releasing capacity |
| Session lookup | 4 | 32 | Existing SQLite timeout |
| Blocking async HTTP/voice work | 4 | 8 | Existing operation-specific timeout |
| Document parsing, process-wide | 2 | 8 | 120 seconds including queue wait |
| Runtime assistant/template/image/statistics jobs | 2 | 8 | Queue wait: 120 seconds |
| Classroom import/report/practice jobs | 2 | 8 | Queue wait: 120 seconds |
| Question-bank imports | 1 | 2 | Queue wait: 120 seconds |
| Workflow jobs | 2 | 8 | Queue wait: 120 seconds; QGIS keeps its native deadlines |
| Population lesson preparation | 2 | 8 | Queue wait: 120 seconds |
| Model outbound calls | 4 | 8 | Queue wait: 30 seconds |

Authentication snapshots are checked again in the write transaction after expensive
password work. Password resets, identity/status changes and all-session revocation
advance an internal authentication version, preventing old verification results from
creating a session. The existing five-failure, fifteen-minute lock remains. Login
frequency limits cover normalized account (10/5 min), source IP (1200/5 min) and
process (2400/5 min); proxy IP headers require the existing explicit trust setting.
Busy authentication returns 429; background/document/request admission returns 503
with Retry-After. Health does not use these execution queues.

Document workers use bounded JSON IPC and inherit only a small OS environment
allowlist, excluding model keys and database credentials. Windows uses a Job object
and waits for process handles; Linux uses RLIMIT_AS per process and a dedicated
subreaper. The default memory budget is 1 GiB per process. This is a trusted-parser
resource boundary, not a sandbox for arbitrary executable code. Input/output IPC
limits are 100/300 MiB; existing upload and Office archive budgets remain in force.
Cancelled or timed-out parsing kills and reaps the process tree before releasing
admission, and late results are discarded.

Workflow histories, cached workflows, subscribers and each subscriber queue are
bounded at 128; cached history retention is 600 seconds. Truncation provides a fresh
snapshot; slow subscribers receive stream_idle_timeout with an explicit reconnect
instruction. Workflow admission occurs before record/file/event creation. Queue
expiry runs independently of busy workers. Shutdown closes admissions and drains
accepted tasks; it retains the QGIS cancellation and worker shutdown protocol.

Local verification uses synthetic documents, accounts, model responses and QGIS
fixtures. Real external model/ASR/QGIS acceptance and capacity targets belong to the
later isolated load-test batch. Linux-specific process-tree tests run in Linux CI;
Windows results alone do not establish them.

Rollback: revert the batch commit and restart during an appropriate window. The
SQLite auth_version column is additive and can remain when rolling back; business
IDs, password/session hashes and files are not rewritten by this batch.
