# Reliability Intelligence Platform

A production-style software/ML engineering project for estimating whether a service will
**enter an incident within the next 10 minutes**, using its most recent **15 minutes of
available telemetry**.

**Current status: Batch B — ML and evaluation implemented and locally verified.** The
package generates validated synthetic telemetry, builds causal features, trains fixed model
candidates and evaluates frozen choices on temporal and seed/schedule holdouts. The changed
schedule regime exposes substantial performance loss; synthetic feasibility is not real-world
forecasting validity. API, PostgreSQL and deployment remain deferred.

## Why this exists

Useful incident prediction requires trustworthy temporal data, defensible targets, reliable
software and operational evaluation. The foundation and ML workflow make those assumptions inspectable
through reproducible data and controlled evaluation. The final system will support on-call investigation with calibrated
risk, durable predictions and monitoring; see [the project vision](PROJECT_VISION.md).

## Current architecture

```text
JSON configuration + seed
          │
          ▼
  normal signals + current fault effects
          ├── operational telemetry ────────────── telemetry.parquet
          └── realised incident lifecycle ──────── incidents.parquet
                         │
telemetry keys + future incident starts
                         └── offline targets ──── labels.parquet

Parquet bundle + resolved config + integrity manifest
          └── verified evidence generation → saved PNG / CSV / JSON / Markdown
```

Inference-time fields are strictly separate from incident metadata and future labels.
Starts in `(t, t+10m]` count as positives. Incomplete future coverage produces null targets,
not negatives. The separate ML workflow builds only allowlisted operational features; truth never enters predictors.

## Setup

Use **Python 3.14**. This is the only Python series currently targeted and validated.
Run from the repository root:

```bash
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-lock.txt
python -m pip install --no-deps --no-build-isolation -e '.[dev]'
```

`requirements-lock.txt` is the exact validated dependency/build-tool snapshot. The package also
has bounded dependency ranges in `pyproject.toml`; upgrading that snapshot requires revalidation
and regenerated evidence. The lock is version-pinned, not a wheel/hash lock for every platform.
No secrets or `.env` file are required.

## Generate telemetry

```bash
reliability generate --config configs/batch_a.json --output data/my_run
```

The default is 48 hours at one-minute sampling, seed 42, with api-gateway, auth-service,
catalog-service and search-service. It produces 11,520 telemetry rows, 16 incidents and
11,520 label rows. Use a new output directory for each run: existing runs are never overwritten.
`python -m reliability_intelligence` is an equivalent entry point.

Configuration, scenario equations and schedule examples: [simulation guide](docs/SIMULATION.md).
Fields, units, interval boundaries and target eligibility: [data contract](docs/DATA_CONTRACT.md).

## Reproduce evidence

```bash
reliability evidence --dataset data/my_run --output evidence/my_run
```

Open `evidence/my_run/REPORT.md`. The command verifies dataset hashes before generating plots
for normal behaviour and each available scenario, incident counts, distributions, class balance,
correlations and phase summaries. It uses the earliest event of each type, not manually selected
favourable examples. Evidence output must also be a new directory.

The delivered reference report is [Batch A evidence](evidence/batch_a/generated/REPORT.md).
Its local raw bundle is `data/batch_a/`; raw generated runs are Git-ignored and reproducible from
configuration. The small reference plots/reports are intended for version control.

## Batch B: reproduce ML and evaluation

```bash
reliability batch-b --config configs/batch_b.json --corpus data/batch_b --output data/batch_b_experiment --evidence evidence/batch_b/generated
```

This command generates or strictly verifies/reuses seven independent four-day bundles (846
incidents, 161,280 rows), fits training-only prevalence/logistic/boosting candidates, compares
calibration and selects thresholds on separate chronological stages, then scores frozen choices.
Use unused experiment/evidence paths on repeat runs. Raw corpus, model binaries and all keyed
predictions are Git-ignored; compact configuration, tables, five plots and hashes are committed.

To regenerate evidence from saved predictions without fitting:

```bash
reliability batch-b-evidence --experiment data/batch_b_experiment --output evidence/batch_b/repeated
```

Start with [the generated Batch B report](evidence/batch_b/generated/REPORT.md),
[feature contract](docs/FEATURE_CONTRACT.md), [evaluation protocol](docs/EVALUATION_PROTOCOL.md)
and [completion/checklist](docs/BATCH_B_COMPLETION.md). Raw boosting was selected. Its temporal-test
AP is 0.8800795523231142 and changed-regime AP is 0.4512755938169232. Final false-alert frequencies
exceed the validation budget, so the selected threshold is an experimental reference, not a
production operating recommendation. Always-on baselines expose an episode-budget weakness;
alert burden must accompany detection/episode precision.

## Tests and quality

```bash
pytest -q
ruff check .
ruff format --check .
python -m pip check
```

Tests cover exact target boundaries, right censoring, exact service-specific telemetry-grid
history, configuration, deterministic schedules and signals, lifecycle continuity, scenario
counterfactuals, schema/leakage guards, Parquet integrity, and an end-to-end CLI/evidence run.
GitHub Actions runs these checks on Linux/Python 3.14, then
regenerates the default dataset/evidence and uploads evidence. Remote CI has not run in this
local workspace; local results are recorded in [PROJECT_STATE.md](PROJECT_STATE.md).

## Repository structure

```text
configs/                        default simulation JSON
src/reliability_intelligence/
  config.py                     validated configuration and coefficients
  telemetry_grid.py             authoritative configured timestamp/service grid
  schemas.py                    operational telemetry contract
  simulation/                   scheduling, lifecycle pressure, temporal signals
  labels.py                     offline future-start target generation
  storage.py                    immutable Parquet bundles and hash checks
  evidence.py                   data-derived plots, statistics and report
  features.py                   exact causal feature and purge contracts
  models.py                     stage-restricted fitting and persisted inference
  evaluation.py                 row, episode, event and uncertainty scoring
  experiment.py                 corpus, partitions and immutable experiment output
  ml_evidence.py                saved ML plots, tables and report
  cli.py, __main__.py            executable interface
tests/                         unit and integration tests
data/                          ignored generated raw bundles; usage README
evidence/batch_a/, batch_b/    saved reference evidence and validation records
docs/                          data contract, mechanisms, completion report
.github/workflows/ci.yml        tests/quality/evidence CI
```

There are no empty API/monitoring packages. Later capabilities can be added alongside
these cohesive modules without relocating the simulator.

## Roadmap and limits

[A: foundation → B: ML/evaluation → C: serving/persistence → D: monitoring/external validation
→ E: hardening/deployment](ROADMAP.md).

Simulation uses smooth injected faults, dense telemetry, simple metric relationships and
structured schedules. It does not model a service dependency graph, late data or simultaneous
faults within a service. Sixteen synthetic events are a review fixture, not an adequate model
selection corpus. Onset is a controlled fault-pressure boundary, not a universal production SLO.

Review [decisions](DECISIONS.md), [current state](PROJECT_STATE.md) and the
[Batch A completion report](docs/BATCH_A_COMPLETION.md) before planning the next batch. Batch C has not started.
