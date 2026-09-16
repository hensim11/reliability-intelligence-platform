# Monitoring and reliability reference report

Source: implementation `92ebb54d8a71a326dca52bbf22133c8dfd623808`, based on merged Batch C
`450a7d6`. Full generated results: [reliability.json](reliability/reliability.json),
[Compose/environment/source manifest](reliability/compose_validation.json).

| Measurement | Reference-like interval | Deterministic shift |
| --- | ---: | ---: |
| Rebuilt feature rows | 11,460 | 800 |
| Persisted probability rows | 400 | 120 |
| Stable distributions | 50 | 0 |
| Severe distributions | 0 | 50 |
| Probability PSI | 0.0482073989063377 | 2.0296097096569135 |

Reference distributions use only 34,260 verified Batch B training rows. These are controlled
synthetic demonstrations with fixed PSI heuristics, not statistical guarantees or holdout tuning.
Per-feature values and service volume/completeness/freshness/ingestion-lag summaries are in the
sealed snapshots. The shifted data remain valid operational telemetry but do not imply that the
unchanged model should perform well. Certified delayed fixture: 30 eligible rows, one positive,
zero detections, AP 0.034482758620689655, Brier 0.03332881427368089, no alert rows. No retuning.

Actual PostgreSQL outage returned live **200**, ready **503**, predictions **503**, metrics **200**;
database failure samples were observable. Recovery restored readiness. Restart retained **12,380
telemetry**, **520 predictions**, **1 incident**, **1 certificate**, **3 snapshots**. Process-local
counter samples reset. Repeated imports and same-identity snapshots were identical. Incomplete
history stored no prediction; injected model call returned controlled 503 with unchanged prediction
count. Invalid reference startup left liveness/metrics available and readiness unavailable.

Clean build/empty volume, c001→d001, repeated upgrade, downgrade/re-upgrade and metadata drift
checks passed. Full suite: **238 passed, zero skipped, 15.83 s**, including genuine PostgreSQL.
Ruff check/format (76 files) and pip check passed. Disposable Compose containers/volume removed.
Expected failure diagnostics remained local; no raw logs or secrets are committed.

The unchanged Batch C parity runner repeated **121 windows**, exact 49-feature and probability
agreement (maximum probability error **0.0**). Eight-client new-prediction latency was p50
**110.24675006046891 ms**, p95 **164.8372909170575 ms**; same-key race: one created, 31 reused.
These loopback measurements are not a production SLO. [Detailed parity evidence](parity/results.json).

Reference generation and the full SMD study/export repeated byte-identically for 16 files in the
recorded environment. Operational computation timestamps, UUIDs, process counters and latency
vary intentionally; their semantic assertions, counts and deterministic drift values must reproduce.
