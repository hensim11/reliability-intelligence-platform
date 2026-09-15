# Batch A completion report

## 1. Implemented

Installable Python 3.14 package and CLI, central validated configuration, four service profiles,
correlated temporal telemetry, four developing faults, explicit ground truth, correct future-start
labels, strict read-time semantic validation, immutable Parquet bundles, reproducible evidence,
tests, quality tooling and documentation. The requested feature branch contains the initial commit.

## 2. Final structure

```text
README.md / PROJECT_VISION.md / ROADMAP.md / PROJECT_STATE.md / DECISIONS.md
pyproject.toml / requirements-lock.txt / .gitignore
configs/batch_a.json
src/reliability_intelligence/
  config.py / telemetry_grid.py / schemas.py / labels.py / storage.py / evidence.py / cli.py
  __init__.py / __main__.py
  simulation/__init__.py / engine.py / incidents.py
tests/conftest.py / test_config.py / test_labels.py / test_simulation.py / test_integration.py
docs/DATA_CONTRACT.md / SIMULATION.md / BATCH_A_COMPLETION.md
data/README.md / batch_a/ (generated bundle ignored by Git)
evidence/batch_a/README.md / validation.txt / generated/
.github/workflows/ci.yml
```

## 3. Architectural decisions

Forecast future starts with fixed 15/10-minute windows; keep inputs/truth/targets separate;
right-censor unknown horizons; use seeded schedules and noise streams; store typed local Parquet
with resolved config, versions and hashes; avoid premature serving/storage infrastructure.
Onset marks an injected fault-pressure boundary, not a universal production SLO. Python 3.14 is
the validated target. Exact dependency pins support reproduction. Full rationale: ../DECISIONS.md.

## 4. Exact commands

From the repository root:

```bash
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-lock.txt
python -m pip install --no-deps --no-build-isolation -e '.[dev]'
reliability generate --config configs/batch_a.json --output data/my_run
reliability evidence --dataset data/my_run --output evidence/my_run
pytest -q
ruff check .
ruff format --check .
python -m pip check
```

Use new output paths for repeats. Existing `.venv` and `data/batch_a/` are ready locally.

## 5. Dataset/schema

48 hours, four services, one-minute intervals, seed 42. 11,520 rows in each of telemetry and
labels; 16 incident records. Operational columns: UTC timestamp, service ID, request rate,
p50/p95 application latency, error fraction, CPU/memory percent and dependency latency.
Truth includes type, service, precursor/onset/end/recovery boundaries and severity. Labels
contain keys, history/horizon completeness and nullable Int8 future-start target. Target interval:
`(t,t+10m]`. Three separate files preserve the inference boundary.

Label counts: 160 positive, 11,320 negative, 40 unknown; 1.3937% positive among observed labels.
11,420 rows have full observation and forecast coverage. See DATA_CONTRACT.md for exact semantics.

## 6. Scenarios

Memory leak increases memory before exhaustion effects; database degradation raises dependency
then application latency/errors; CPU saturation develops resource stress; traffic overload raises
offered load beyond capacity. All have gradual precursor and recovery phases. Every service has
one event of each type in the default run; all active durations are 30 minutes.

## 7. Evidence

[Generated report](../evidence/batch_a/generated/REPORT.md): seven PNGs (normal, four faults,
overview and correlations); four CSVs (descriptive statistics, correlations, full incident catalogue,
example phase means); JSON summary with source hashes and environment. Figures show normal
variation, differentiated precursors, secondary metric effects, recovery and label imbalance.
Examples are selected by earliest onset per type. All figures were visually inspected. Two fresh
default runs matched each other and the reference tables, configuration, manifest and hashes;
both sets of 13 evidence files matched the saved evidence byte-for-byte.

## 8. Test / CI status

71 pytest cases passed locally. Added tests alter Parquet contents and refresh their manifest hashes,
proving semantic rejection independently of integrity hashes. They cover invalid and wrong targets,
horizon/null mismatches, incident types/services/lifecycle ordering/overlap, manifest/config coverage
disagreement and missing/unexpected semantic columns. Valid round trips and typed empty incident
bundles remain supported. Grid-specific tests cover complete histories; missing internal, oldest and
current samples; equal row counts with an off-grid replacement; service isolation; configured
30-second sampling; and bundle-level rejection after hashes and row counts are refreshed. Ruff
lint/format checks and dependency consistency passed. Editable
installation, two default generations and two evidence commands succeeded. CI is configured for
Linux/Python 3.14 with the same checks plus regenerated evidence uploads. Remote CI is **unrun**;
local macOS validation is not claimed as a Linux/GitHub-hosted result.

## 9. Limitations

Synthetic, smooth faults and structured schedules may be unusually predictable. Sixteen events
are insufficient for model development. No explicit dependency propagation, same-service fault
overlap, missing/late observations, real production telemetry or external validation. Aggregate
latency/error mechanisms are assumptions, and simulated onset may differ from an operational SLO.
Cross-environment byte identity is not promised; dependency pins are not wheel-hash locks.

## 10–11. Acceptance

**Every requested Batch A criterion passes under the stated local verification scope.**
No unmet Batch A criteria. The complete checklist is in ../PROJECT_STATE.md. Remote CI remains
pending until pushed; no prediction/model, API, database or deployment functionality is claimed.

## 12. Recommended branch / commit

Branch: `feat/batch-a-foundation`.

Commit title: `feat: establish reproducible telemetry and incident simulation foundation`

Suggested description: Add validated service simulation and four incident lifecycles, separate
Parquet telemetry/truth/future labels, reproducible evidence, 71 tests, CI and architecture/state
documentation. Fix the forecasting contract at 15-minute history and 10-minute future starts.

## 13. Logical start for Batch B

Specify the allowlisted trailing feature contract and chronological split/purge rules first.
Use telemetry alone for `(t−15m,t]` features, join labels by keys and require full history/horizon.
Plan more independent incidents and held-out seeds/regimes; fit preprocessing only on training
periods. Begin evaluation with naive baselines, calibration and incident-level warning metrics.
Batch B has not been started.
