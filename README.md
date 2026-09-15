# Reliability Intelligence Platform

A production-style software/ML engineering project for estimating whether a service will
**enter an incident within the next 10 minutes**, using its most recent **15 minutes of
available telemetry**.

**Current status: Batch A — foundation and synthetic telemetry system.** The package generates
time-dependent signals for four fictional SaaS services, controlled incident lifecycles,
future-start labels and reproducible evidence. It does not yet train models, serve predictions,
connect to PostgreSQL or deploy infrastructure. Synthetic results are not evidence of real-world
outage prediction.

## Why this exists

Useful incident prediction requires trustworthy temporal data, defensible targets, reliable
software and operational evaluation. This first milestone makes those assumptions inspectable
before modelling begins. The final system will support on-call investigation with calibrated
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
not negatives. No feature engineering or ground-truth-derived predictor is exported.

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

## Tests and quality

```bash
pytest -q
ruff check .
ruff format --check .
python -m pip check
```

Tests cover exact target boundaries, right censoring, configuration, deterministic schedules and
signals, lifecycle continuity, scenario counterfactuals, schema/leakage guards, Parquet integrity,
and an end-to-end CLI/evidence run. GitHub Actions runs these checks on Linux/Python 3.14, then
regenerates the default dataset/evidence and uploads evidence. Remote CI has not run in this
local workspace; local results are recorded in [PROJECT_STATE.md](PROJECT_STATE.md).

## Repository structure

```text
configs/                        default simulation JSON
src/reliability_intelligence/
  config.py                     validated configuration and coefficients
  schemas.py                    operational telemetry contract
  simulation/                   scheduling, lifecycle pressure, temporal signals
  labels.py                     offline future-start target generation
  storage.py                    immutable Parquet bundles and hash checks
  evidence.py                   data-derived plots, statistics and report
  cli.py, __main__.py            executable interface
tests/                         unit and integration tests
data/                          ignored generated raw bundles; usage README
evidence/batch_a/              saved reference evidence and validation record
docs/                          data contract, mechanisms, completion report
.github/workflows/ci.yml        tests/quality/evidence CI
```

There are no empty API/model/monitoring packages. Later capabilities can be added alongside
these cohesive modules without relocating the simulator.

## Roadmap and limits

[A: foundation → B: ML/evaluation → C: serving/persistence → D: monitoring/external validation
→ E: hardening/deployment](ROADMAP.md).

Simulation uses smooth injected faults, dense telemetry, simple metric relationships and
structured schedules. It does not model a service dependency graph, late data or simultaneous
faults within a service. Sixteen synthetic events are a review fixture, not an adequate model
selection corpus. Onset is a controlled fault-pressure boundary, not a universal production SLO.

Review [decisions](DECISIONS.md), [current state](PROJECT_STATE.md) and the
[Batch A completion report](docs/BATCH_A_COMPLETION.md) before starting Batch B.
