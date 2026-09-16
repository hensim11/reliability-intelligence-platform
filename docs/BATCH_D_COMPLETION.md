# Batch D implementation and acceptance

2026-09-16. **All 23 local gates pass** on implementation `92ebb54`. Batch C was verified merged
on clean, fast-forwarded main `450a7d6` before work. Branch:
`batch-d-monitoring-reliability-external-validation`. Hosted CI and PR review are separate; do not
merge the Batch D PR. No external deployment or production-validity claim.

## Implementation and decisions

The unchanged 49-feature builder and frozen `boosting_raw` model now have a verified training-only,
versioned monitoring reference, fixed heuristic PSI distributions and bounded persistent snapshots.
Alembic `d001` adds immutable monitoring snapshots plus separate confirmed incident-start and
complete-coverage tables. Trusted local CLI imports are transactional/idempotent; delayed labels
require fully matured, certified horizons and cutoff-available records. GET routes only retrieve.
Low-cardinality Prometheus metrics remain process-local; durable statistical history is PostgreSQL.

The independent SMD experiment uses all 28 machines, pinned MIT-licensed source, anonymous inputs,
ordinal 15/10-step windows, chronological purging and training-fitted logistic/prevalence baselines.
Six machines have no training positives, explicitly yielding unavailable logistic results. No
production-schema remapping, model transfer, production retraining or threshold change occurred.
Decisions D01–D12 in [DECISIONS.md](../DECISIONS.md) record the rationale and trade-offs.

## Exact measured results

- Full real-PostgreSQL pytest: **238 passed, 0 failed, 0 skipped, 15.83 s**; existing 205 retained.
- `ruff check .`: passed; `ruff format --check .`: **76 files already formatted**.
- `python -m pip check`: **No broken requirements found**. Editable installation also passed.
- Empty schema, repeated head upgrade, explicit c001→d001, d001→c001→d001, base downgrade/re-upgrade
  and SQLAlchemy metadata/schema-drift checks: passed.
- Clean-volume Docker Compose build/startup, HTTP/SQL smoke, real PostgreSQL outage/recovery,
  restart durability, metrics reset and disposable resource cleanup: passed.
- Frozen HTTP regression: **121 exact windows**, all 49 float64 features, probability maximum error
  **0.0**; 32-request race: one creation/31 retries. Local p50/p95 new prediction latency
  110.24675006046891/164.8372909170575 ms; no production latency claim.
- Reference: **34,260 training rows**. Stable interval: 11,460 feature rows/400 predictions,
  all 50 distributions stable, probability PSI 0.0482073989063377. Shift: 800/120, all 50 severe,
  probability PSI 2.0296097096569135. Thresholds were not revised from these observations.
- Durable exercise: 12,380 telemetry rows, 520 predictions, one incident, one certificate and three
  snapshots survived database/API restart. Delayed fixture: 30 eligible rows, one positive, zero
  detections; missing certificates excluded the other services, not negative-labelled them.
- All 28 SMD machines validated. Final logistic: 22 available machines, 163,383 rows, 850 positives,
  AP 0.005968969761866583, 1/85 scorable starts, 424 false episodes, 2,777 alert rows. Prevalence:
  all 28 machines, 211,836 rows, 1,080 positives, 0/108 starts, zero alert rows at fixed 0.5.
  Different denominators and null metrics are explicit; weak findings do not authorize retuning.
- Reference/study/export regeneration: **16/16 files byte-identical** in the recorded environment.
  Operational UUIDs/clocks/latencies intentionally vary; exact source/model hashes are preserved.

Two upstream Starlette/anyio deprecation warnings remain; none were suppressed. Reference generation
inside the host sandbox also reported inability to discover physical cores and used logical cores;
repeat output was still byte-identical. Failed development runs are disclosed in the evidence index.

## Acceptance gate table

| # | Gate | Result | Evidence |
| --- | --- | --- | --- |
| 1 | Merged Batch C remains intact | Pass | [121-window parity](../evidence/batch_d/parity/results.json), 205 retained tests |
| 2 | Reproducible immutable training-only reference | Pass | [Reference](../evidence/batch_d/monitoring_reference/reference.json), provenance tests |
| 3 | Completeness, freshness, ingestion lag | Pass | [Per-service snapshot details](../evidence/batch_d/reliability/reliability.json) |
| 4 | Bounded feature/probability drift | Pass | [Snapshots](../evidence/batch_d/reliability/reliability.json), 31-day/query-limit contract |
| 5 | Low-cardinality application monitoring | Pass | [Metrics tests](../tests/test_monitoring.py), [contract](MONITORING.md) |
| 6 | Monitoring failures do not corrupt inference records | Pass | [Rollback/retry exercises](../evidence/batch_d/reliability/reliability.json) |
| 7 | Matured certified delayed evaluation | Pass | [Delayed results](../evidence/batch_d/reliability/reliability.json), exclusion/union tests |
| 8 | Exact `(t,t+10m]` boundaries | Pass | [Parameterized boundary tests](../tests/test_monitoring.py) |
| 9 | Outcomes cannot influence inference | Pass | [Prediction unchanged after import test](../tests/test_monitoring.py), separate tables/modules |
| 10 | Fixed heuristic drift thresholds | Pass | [Persisted config](../evidence/batch_d/monitoring_reference/reference.json), exact-boundary tests |
| 11 | Controlled observable DB/model failures | Pass | [Actual outage/injected model results](../evidence/batch_d/reliability/reliability.json) |
| 12 | Recovery and restart exercised | Pass | [Durable counts and recovery](../evidence/batch_d/reliability/reliability.json) |
| 13 | Constrained immutable idempotent records | Pass | [d001](../migrations/versions/d001_monitoring.py), real PostgreSQL tests |
| 14 | SMD source/licence/version/hashes | Pass | [Source manifest](../evidence/batch_d/smd/source.json) |
| 15 | Leakage-safe preprocessing/splits | Pass | [Fixed protocol](../evidence/batch_d/smd/protocol.json), [code](../src/reliability_intelligence/external.py), fixture tests |
| 16 | All 28 machines included | Pass | [Per-machine table](../evidence/batch_d/smd/per_machine.csv); six logistic unavailable, no dataset exclusion |
| 17 | Row, episode and burden metrics | Pass | [Full results](../evidence/batch_d/smd/results.json) |
| 18 | Domain mismatch/transfer limits prominent | Pass | [External report](../evidence/batch_d/smd/REPORT.md), [contract](EXTERNAL_VALIDATION.md) |
| 19 | Complete tests, zero PostgreSQL skips | Pass | [238-test output](../evidence/batch_d/reliability/compose_validation.json) |
| 20 | Lint, format, dependencies, migrations | Pass | [Command records](../evidence/batch_d/reliability/compose_validation.json) |
| 21 | Compose/evidence reproduce | Pass | [Clean-volume run](../evidence/batch_d/reliability/compose_validation.json), [byte comparisons](../evidence/batch_d/reproducibility/results.json) |
| 22 | Documentation/decisions match behaviour | Pass | [Monitoring](MONITORING.md), [state](../PROJECT_STATE.md), D01–D12 |
| 23 | No Batch E or production-validity claim | Pass | Limitations below and in all evidence reports |

## Reproduction entry points

Use locked dependencies, the saved frozen Batch B experiment/corpus and a configured ignored `.env`
with local Compose credentials/model directory. Never run schema-resetting tests on a shared database.
Choose new project/work/output names. The runner uses loopback 55435/58001 and distinct smoke,
test and exercise databases; it refuses an existing project/volume/output and cleans on success.
Failures retain resources and diagnostics for inspection.

```bash
source .venv/bin/activate
python -m reliability_intelligence.monitoring.cli reference \
  --experiment data/batch_b_experiment --corpus data/batch_b --output data/new_d_reference
python scripts/validate_batch_d.py --project rip-batchd-repeat \
  --work data/new_d_work --output data/new_d_evidence --reference data/new_d_reference
# Independent SMD download/pin and study/export commands:
# See docs/EXTERNAL_VALIDATION.md; external downloads never run in CI.
# Full tests against a separate disposable PostgreSQL database:
export RIP_TEST_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@127.0.0.1:PORT/TEST_DB'
pytest -q
ruff check .
ruff format --check .
python -m pip check
```

Current frozen parity path: `scripts/batch_c_evidence.py --url http://127.0.0.1:PORT
--telemetry data/batch_a/telemetry.parquet --output data/new_parity`, with RIP_DATABASE_URL and
RIP_MODEL_DIR set and a separately running current-schema API backed by an empty disposable database.
[Evidence index](../evidence/batch_d/README.md) links source/environment/artefact manifests and plots.

## Limitations and Batch E

PSI thresholds are heuristics, not significance guarantees. Process counters reset on restart;
rejected-request histories are not durable. Snapshot scheduling/operator response is manual.
Certification is a trusted completeness assertion, not proof about the real world; certificate
correction/versioning remains future work. Historical predictions are retrospective, not proof of
original arrival-time availability. SMD lacks compatible metric semantics, incident definitions
and sufficiently documented cadence. Its weak results do not validate real ten-minute warning.
Authentication, TLS, production deployment, least-privilege roles, backup/restore, production SLOs,
retention and operational hardening remain Batch E. The production `boosting_raw` model and
threshold **0.5700000000000001** are unchanged. The PR must remain unmerged.
