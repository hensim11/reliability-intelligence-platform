# Dataset contract v1.0

All data is synthetic. Each run consists of three Parquet files plus resolved `config.json`
and `manifest.json`. Coverage is `[coverage_start, coverage_end_exclusive)` in UTC. Each
service has one row per configured sampling interval with no missing records. Output order
is `(timestamp, service_id)`; keys are unique. Timestamps denote the instant an aggregate
is available; metrics represent the interval ending at that instant, never a following interval.
The initial sample is a seeded initial state, not reconstructed pre-run history.

## Operational telemetry — `telemetry.parquet`

| Field | Type / unit | Meaning |
|---|---|---|
| timestamp | timezone-aware timestamp, UTC | Sample availability time |
| service_id | string | Service identity |
| request_rate_rps | float64, requests/second | Offered request rate; not integer event counts |
| latency_p50_ms | float64, milliseconds | Synthetic median application latency |
| latency_p95_ms | float64, milliseconds | Synthetic high-percentile application latency, ≥ p50 |
| error_rate | float64, fraction [0,1] | Aggregate failed-request fraction |
| cpu_utilisation_pct | float64, percent [0,100] | CPU utilisation |
| memory_utilisation_pct | float64, percent [0,100] | Memory utilisation |
| dependency_latency_ms | float64, milliseconds | Database/dependency response latency |

All numeric metrics are finite and nonnegative. No nulls, incident types, pressure values,
states, seeds, schedules, target labels or future fields are permitted here. Timestamp and
service identity are available operationally, but calendar encodings can memorise synthetic
schedules; Batch B must assess that risk. These are generated aggregates, not quantiles or
fractions computed from individual requests. The p95 relationship is a simplifying assumption.

## Simulation truth — `incidents.parquet`

One row per incident. Fields: `incident_id` (run-local string), `service_id` (string),
`incident_type` (memory_leak/database_degradation/cpu_saturation/traffic_overload),
`precursor_start`, `incident_start`, `incident_end`, `recovery_end` (UTC timestamps),
`severity` (float64 multiplier, 0.5–1.5 for explicit events; generated values 0.85–1.15).
An empty incident table preserves these types.

Intervals are half-open: precursor `[precursor_start, incident_start)`, active
`[incident_start, incident_end)`, recovery `[incident_end, recovery_end)`. Elsewhere the
service is normal. Within-service lifecycles cannot overlap; different services may overlap.
Event boundaries may fall between telemetry samples. IDs are metadata and must not become features.
The manifest and resolved configuration are also simulation metadata, not inference inputs.

## Offline labels — `labels.parquet`

Exactly one row per operational key, with the same order:

| Field | Type | Meaning |
|---|---|---|
| timestamp, service_id | same as telemetry | Join key |
| history_complete | boolean | Every configured service-specific grid point in `(t−15m,t]` exists, and the full window is within coverage |
| horizon_complete | boolean | t + 10m < coverage_end_exclusive |
| incident_within_horizon | nullable Int8 | 1 if any same-service start lies in `(t,t+10m]`; otherwise 0, or null if horizon incomplete |

At a start timestamp, that incident does not count toward its own future target. Active
or recovering rows remain in the table; their target concerns a subsequent start. Precursor
state alone does not define the label. The current timestamp is part of the required history;
the open-left boundary is excluded. For one-minute sampling, a complete history at 00:15
requires 00:01 through 00:15. Missing internal or boundary samples make the flag false, even
when elapsed coverage and row count appear sufficient. An off-grid timestamp or another
service's row cannot replace an expected point. Expectations come from
`SimulationConfig.interval_seconds`, and only timestamps at or before t are examined.
Incomplete histories may have targets but must not enter the initial 15-minute feature dataset.
Future eligibility is offline information; never use `horizon_complete` as a feature or online input.

For example, an incident starting at 00:20 produces positive labels at minute samples
00:10 through 00:19. 00:20 itself is negative unless another start occurs by 00:30.
For coverage ending at 01:00 (exclusive), samples 00:50 onward have unknown targets.

Batch B should select complete history/horizon rows and construct trailing features only
from telemetry. Exact grid membership does not establish arrival-time availability in a real
stream; ingestion must separately validate late data and event/processing-time semantics.
No interpolation, imputation or features are implemented in Batch A.

## Reproduction and integrity

`manifest.json` records schema/package versions, dependency/Python versions, row counts,
coverage and SHA-256 of the three tables and resolved config. `read_dataset` verifies every hash
before parsing the configuration, then requires manifest coverage and configured services to
agree with the resolved configuration. It validates exact table schemas and supported dtypes,
operational invariants, incident identifiers/types/services/severity/lifecycle bounds and
same-service non-overlap. It also recomputes history/horizon flags and every future-start target
from telemetry keys, configured windows, coverage and incident truth. Nullable targets must be
exactly null for incomplete horizons and binary otherwise. Typed empty incident tables remain valid.

Telemetry keys are independently checked against the exact Cartesian product of timestamps and
services defined by the resolved configuration. Timestamps begin at `start_time`, advance by
`interval_seconds`, and stop before `start_time + duration_minutes`; every configured service is
required at every timestamp. The comparison detects missing, unexpected and duplicate keys, then
requires the canonical ascending `(timestamp, service_id)` row order. Validation does not sort,
fill, drop or otherwise repair malformed telemetry. This bundle-level guarantee is distinct from
the per-prediction `history_complete` calculation.

These checks detect internally inconsistent or edited bundles even when an affected file's hash is
refreshed. They do not provide authenticity: a party able to alter every file can construct a new,
internally consistent bundle. Truth is used only to verify offline targets and is never added to
operational telemetry. This is a local generated-bundle reader, not a general untrusted-data
ingestion validator. Parquet timestamp precision is chosen by pandas/PyArrow; readers must compare
timezone-aware instants, not assume nanoseconds.

Same configuration and seed under the recorded code/dependency environment reproduce table
values. No runtime clock or random UUID enters generated data. Binary hashes are reproducible
locally, but not guaranteed across platforms or writer versions. Preserve the original raw
bundle; regeneration into a new directory allows comparison without destructive replacement.
