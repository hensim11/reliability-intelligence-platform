# Batch D monitoring and delayed outcomes

The production model, threshold, 49 features and `(t−15m,t] → (t,t+10m]` task are unchanged.
Monitoring is a local diagnostic capability, not a guarantee of calibration, incident detection
or production reliability. The application remains single-worker and loopback-only.

## Reference provenance and drift

`monitoring.reference.generate_reference` verifies the complete immutable Batch B experiment
manifest, loads its frozen model, verifies each development corpus against saved corpus manifests,
and checks training assignment keys against the original chronological training boundary. It
rebuilds the original feature builder and selects only training keys. Calibration, validation,
temporal test and heldout rows never define bins, reference probabilities or thresholds. No fitting
occurs. The reference includes the 49 ordered feature distributions and model-output probabilities,
feature/model identity, source hashes, configuration, training count and canonical SHA-256; the
atomic immutable output directory has a separately sealed file manifest.

Default operational heuristics, fixed before reference evidence: 10 quantile intervals augmented
with extrema, minimum 100 observations, additive proportion smoothing 0.0001, PSI warning ≥0.1
and severe ≥0.25. Exact equality enters the higher severity. Duplicate quantiles collapse. A
representable boundary immediately above the maximum separates equal constants from upward shifts;
underflow/overflow bins remain explicit. Expected and observed proportions are both smoothed and
renormalized. These thresholds are configurable when generating a **new** reference and are not
p-values, confidence limits or tuned holdout guarantees. Any severe feature/probability gives the
aggregate severe status; inspect all details because correlated features are not independent tests.
Nonfinite observations are invalid; empty or fewer-than-minimum samples are insufficient, with
null PSI. No-data never means stable. A value beyond the finite reference boundary is rejected.

## Durable snapshots

Alembic `d001` follows `c001` and adds `monitoring_snapshots`, `incident_starts` and
`outcome_coverage`. UPDATE/DELETE triggers protect all three; FKs, time/range constraints and unique
identities are checked by PostgreSQL. Incident starts are unique by service/time as well as source
ID, preventing duplicate event counting. These tables never participate in production inference.

Snapshots cover `[start,end)`, at most 31 days; bounds use UTC whole minutes. A server-validated
cutoff must be at or after end and no later than database time. Telemetry and predictions are
filtered by both event time and server availability/production time. Features are rebuilt through
the shared builder with an extra 15 minutes of history, without filling missing minutes. Queries
are bounded by the fixed four services, minute grid and interval; outcome queries additionally
cap at 100,000 records and fail rather than truncate. Snapshot retrieval is limited to 1–1000 rows.

Each snapshot stores kind, interval, cutoff, computation time, model/reference identity, status,
counts, thresholds and sealed detailed results. Its identity hashes kind/interval/cutoff/model/
reference; retries return the original result. Use the **same explicit cutoff** for an idempotent
retry; omitting it deliberately requests a fresh snapshot. GET never recomputes or writes.
Results include per-service volume, expected/missing minutes, completeness, latest-event freshness
relative to cutoff, ingestion-lag min/median/max, feature PSI, probability PSI, prediction count and
elevated-risk fraction. Rejected requests are explicitly unavailable in durable snapshots: their
process-local metrics cannot reconstruct historical interval counts.

```bash
python -m reliability_intelligence.monitoring.cli reference \
  --experiment data/batch_b_experiment --corpus data/batch_b --output data/new_reference
export RIP_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@127.0.0.1:PORT/DISPOSABLE_DB'
export RIP_MODEL_DIR="$PWD/data/batch_b_experiment"
alembic upgrade head
python -m reliability_intelligence.monitoring.cli snapshot --kind drift \
  --start 2026-01-05T00:15:00Z --end 2026-01-07T00:00:00Z \
  --reference data/new_reference
curl 'http://127.0.0.1:8000/monitoring/drift?limit=1'
```

`reliability-monitor` is the installed equivalent entry point. Optionally set
`RIP_MONITORING_REFERENCE` for startup compatibility/hash validation; invalid references leave
liveness and metrics available with readiness at 503. A drift CLI command always requires a
validated reference even if the serving app has no configured reference.

## Process-local application metrics

`GET /metrics` is Prometheus text with an application-specific registry. No hosted collector is
required. HTTP counts/duration use method, normalized route template and status class; unknown
routes collapse to `unmatched`, unknown methods to `OTHER`. No raw URL, query, UUID, service timestamp,
exception message, payload or database credentials become labels. Metrics include telemetry
inserted/unchanged/rejected rows, prediction created/reused/incomplete-history outcomes, prediction
operation duration (including persistence), bounded dependency failures, rejected requests and the
last readiness-check state. Invalid unparseable payloads count as requests; row counts are available
only when a submitted sample list can be identified. Startup dependency failures are also counted.

All counters reset on process restart, are single-worker observations and are not historical
storage. `rip_ready` is the last readiness check, initially zero, rather than a background probe.
`/health/live` and `/metrics` do not query the database or model. `/health/ready` still verifies the
current schema, service catalogue and required table privileges. Errors expose controlled messages;
server logs contain diagnostics. No production failure-injection endpoints were added.

## Trusted local delayed outcomes

Import an allowlisted JSON document with `incidents` and `coverage` arrays via:

```bash
python -m reliability_intelligence.monitoring.cli import-outcomes --input outcomes.json
python -m reliability_intelligence.monitoring.cli snapshot --kind delayed \
  --start 2026-01-05T00:15:00Z --end 2026-01-07T00:00:00Z
curl 'http://127.0.0.1:8000/monitoring/delayed?limit=1'
```

Incident fields: `source_id`, `service_id`, `start`. Coverage adds `end` and certifies the registry
complete on `(start,end]`. Explicit UTC is required; incident times can be subminute. Source IDs
are bounded to 200 characters. No client `recorded_at` is accepted; PostgreSQL assigns it. Future
incidents/certificates fail. Import the incidents and their certificates in the same atomic batch;
incidents are processed first. Identical source retries are no-ops; conflicting retries fail and
roll back the batch. A new incident inside previously certified coverage is rejected: correction
of a false certificate needs a future explicit administrative versioning policy, not silent edits.

Eligibility requires a persisted prediction available by evaluation cutoff, elapsed full ten-minute
horizon, and complete union coverage available by cutoff. Adjacent certificates join; any gap leaves
the horizon unknown. Starts exactly at t are excluded; starts exactly at t+10m are included. No record
without certification is not a negative. Outcome availability does not backdate original knowledge.
Historical predictions remain retrospective under Batch C's availability semantics, so these
metrics cannot establish real-time predictive performance merely because labels are delayed.

Existing row/episode scoring is reused: AP, Brier, log loss, frozen-threshold precision/recall,
scorable/detected starts, lead minutes, false episodes, alert minutes and row fraction, plus service
breakdowns. Undefined metrics are null. Only eligible rows contribute exposure; gaps break alert
episodes. No threshold selection or recalibration occurs. Coverage certifies an external registry's
completeness but software cannot prove that the human/source certification was truthful.
