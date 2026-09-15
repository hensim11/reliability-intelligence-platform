# Feature contract v1.0

## Prediction and input boundary

For one service at t, estimate whether an incident starts in `(t,t+10m]` using only
operational telemetry in `(t−15m,t]`. Batch B supports **60-second sampling only**;
Batch A's other valid sampling intervals remain supported by its own workflow.
The inference function `build_features(telemetry, coverage_start=...)` never accepts
truth, targets, simulation configuration, or eligibility flags. `coverage_start` establishes
the grid origin and coverage, and is not a predictor. Batch C can reuse this function.

Input columns must match `schemas.TELEMETRY_COLUMNS` exactly. Unknown columns, invalid
metrics, duplicate keys, unordered per-service observations and off-grid timestamps fail.
No sorting or repair of malformed input occurs. Output is canonically sorted by keys.
A missing grid observation makes every affected service window ineligible; another service
cannot fill it. Coverage must have started at least 15 minutes before t. At t=00:15,
required samples are 00:01 through 00:15, **excluding 00:00**. A 15-point window must span
exactly 14 minutes on the unique ordered one-minute grid. This proves exact membership,
not merely row count. There is no interpolation, backfill, imputation or future lookup.
The full corpus additionally passes Batch A's stronger exact-bundle validation.

## Allowlist and deterministic output

Exactly 49 float64 predictors, metric-major order. Seven metrics in this order:

1. `request_rate_rps`
2. `latency_p50_ms`
3. `latency_p95_ms`
4. `error_rate`
5. `cpu_utilisation_pct`
6. `memory_utilisation_pct`
7. `dependency_latency_ms`

Each metric emits these seven statistics in order, named `<metric>__<statistic>`:

| Statistic | Definition |
| --- | --- |
| current | Value at t |
| mean | Arithmetic mean of the 15 samples |
| std | Population standard deviation, ddof=0 |
| min / max | Extrema across the same samples |
| change | Current minus oldest (t−14m) value |
| slope | Least-squares time slope per minute; centred time coordinates −7,…,7 |

No cross-metric ratios or automated feature library. Some statistics are correlated;
regularisation and restricted tree size limit complexity, but coefficients are not causal.
Windows are formed within each service before concatenation. No pooled pandas rolling occurs.
Repeated identical telemetry gives identical ordered features in the locked environment.
`feature_matrix` rejects extra/reordered columns, non-float64 dtypes and nonfinite values.

`timestamp` and `service_id` are retained **only as row keys**. No service encoding, absolute
clock, calendar, load-cycle phase or simulation metadata enters any candidate. This avoids
explicit service/schedule memorisation. Telemetry baselines can still reveal service identity:
`service_metrics.csv` diagnoses per-service behaviour, and schedule holdout challenges timing
regularity. Neither is an unseen-service test. No categorical service candidate is fitted.

## Offline target join

The orchestration first loads bundles through `read_dataset`, verifying hashes, grid, truth
and recomputed labels. `attach_targets` enforces exact label columns, unique keys, binary nullable
Int8 targets and boolean flags, then joins one-to-one by `(timestamp, service_id)`, never position.
All feature keys must have labels. Only complete history, complete horizon and observed-target
rows remain. Flags are dropped and are never predictors. Rows during active/recovery phases
remain eligible under the original next-start target; truth does not suppress them.

The low-level join does not independently reconstruct targets from truth; that is the verified
bundle reader's responsibility. Callers must preserve this separation and validated provenance.
Inference does not require future labels or horizon flags. Empty/unready streams yield no feature
rows; this batch does not implement a network-facing readiness/error response.

Tests: `tests/test_features.py`, the grid/label tests inherited from Batch A, and the experiment
integration audit. The saved `feature_schema.json` and model JSON sidecars enforce version/order.
