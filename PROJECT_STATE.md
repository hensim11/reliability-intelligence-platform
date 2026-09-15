# Project state

Updated: 2026-09-15. **Current milestone: Batch A complete locally; ready for review.**
Batch B has not started. Objective: use the latest 15 minutes of service telemetry to
estimate the probability of an incident start within the next 10 minutes.

## Completed

- Installable Python 3.14 src-layout package with CLI and structured JSON application logs.
- Validated central configuration, four service profiles, cyclic load and persistent noise.
- Memory leak, database degradation, CPU saturation and traffic overload with explicit
  precursor → active → recovery lifecycles and seeded/explicit schedules.
- Separate operational telemetry, ground truth and nullable future labels; UTC contract,
  exact open-left/closed-right horizon, history eligibility and conservative end censoring.
- Immutable Parquet runs, atomic dataset publication, resolved config and integrity manifest.
- Data-derived evidence command, seven saved figures, four CSV tables, JSON summary and report.
- Strict read-time validation for configuration/coverage, incident truth and recomputed labels.
- 58 deterministic pytest cases, Ruff quality configuration, exact dependency snapshot and CI.
- Vision, roadmap, decisions, setup, data contract, simulation assumptions and completion report.

## Current commands

From the repository root, once Python 3.14 is available:

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

Choose unused output paths on subsequent runs. The existing `.venv` is installed and ready.

## Dataset / evidence status

The local raw reference is `data/batch_a/`, intentionally ignored by Git. Its coverage is
2026-01-05 00:00 UTC to 2026-01-07 00:00 UTC (exclusive), sampled every minute, seed 42.
There are 11,520 telemetry rows and matching labels across four services, with 16 incidents
(four per service, four per type), each with a 30-minute active duration. Generated precursor
and recovery durations are 25 and 20 minutes respectively.

Labels: **160 positive, 11,320 negative, 40 unknown**. Positive fraction among observed labels:
**1.3937%**. There are 60 rows lacking full history; **11,420** have both full history and horizon
(positive fraction **1.4011%**). No incomplete horizon is labelled negative.

[evidence/batch_a/generated/REPORT.md](evidence/batch_a/generated/REPORT.md) is the saved review
entry point. All seven PNGs were visually inspected for legibility and expected mechanics.
Two fresh CLI simulations produced exactly equal tables, configuration, manifest and all four
hashed files against each other and the saved reference. All 13 files from each fresh evidence
run matched the saved evidence byte-for-byte. Generated evidence includes source hashes and
environment versions; no visual reinspection was necessary because no output differed.

## Validation / repository status

- `pytest -q --tb=short`: **58 passed** (2.73 seconds on the final local test run).
- `ruff check .`: passed; `ruff format --check .`: passed.
- `python -m pip check`: no broken requirements.
- Editable package installation and both default CLI commands succeeded.
- Local environment: macOS arm64, Python 3.14.0; dependencies in requirements-lock.txt.
- CI: `.github/workflows/ci.yml` targets Linux/Python 3.14, runs checks and generates/upload evidence.
  Equivalent application/check commands passed locally. GitHub-hosted execution has **not** run.
- Git was initialised for the requested `feat/batch-a-foundation` initial commit. No remote, PR
  or deployment was created during implementation. Only intentional project files are visible
  to Git; virtualenv, caches, packaging output, audit outputs and raw data are ignored.

## Known limitations / intentionally deferred

Synthetic equations, schedule structure and small event count do not establish real forecasting
ability. Onset is a controlled fault-pressure definition rather than a measured SLO. No service
failure propagation, within-service overlapping faults, late/missing telemetry or real data.
Normal aggregate metrics and latency tails are assumptions. Reproduction across library/platform
changes is not byte-guaranteed. Only Python 3.14 and the recorded local environment were tested;
Linux results await remote CI. The dependency snapshot pins versions without wheel hashes.

Features/models, time-split policy details, calibration/decision thresholds, API, PostgreSQL,
Docker, deployment, monitoring and external validation are intentionally deferred. No empty
packages imply these features exist.

## Batch A acceptance gate

### Foundation

- [x] Professional Python repository and executable package.
- [x] Cohesive package boundaries support later stages without empty boilerplate.
- [x] Central configuration and accurate implementation documentation.

### Simulation

- [x] Multiple service profiles and normal time-dependent telemetry.
- [x] Four differentiated developing incident scenarios.
- [x] Precursors and recovery, explicit lifecycle and separate ground truth.

### Data validity

- [x] Documented schema, units, timestamps and coverage semantics.
- [x] Operational fields separated from simulation metadata and future targets.
- [x] Correct future labels, exact boundary tests and unknown incomplete horizons.
- [x] Read-time truth/label semantics, configuration coverage and service membership enforced.
- [x] Fixed-seed reproducibility, including full reference bundle comparison.
- [x] Operational allowlist and counterfactual tests guard obvious leakage.

### Evidence

- [x] Reproducible command operating on verified saved data.
- [x] Normal and all scenario plots; statistics, incident durations/counts, class balance and correlations.
- [x] Saved and visually reviewed artefacts, with explicit synthetic-data limitations.

### Engineering quality

- [x] Meaningful unit tests and small end-to-end CLI/Parquet/evidence tests.
- [x] All tests and quality checks pass locally.
- [x] CI configured; its executable application/check steps pass locally to the extent possible.
- [x] Documented installation and execution commands were exercised.

### State management

- [x] State reflects the delivered implementation and actual validation.
- [x] Roadmap identifies Batch B as next; Batch B has not begun.
- [x] Decision log records initial choices and their trade-offs.

**Unmet Batch A criteria: none under the requested local validation scope.** Remote CI is an
explicit verification still pending after a repository push, not a claimed successful run.

## Exact next starting point: Batch B

Read docs/DATA_CONTRACT.md and docs/SIMULATION.md, then design an allowlisted, per-service
feature contract over `(t−15m,t]` using only telemetry. Specify chronological partitions and
boundary purging before computing features or fitting preprocessing. Join labels by service/time,
exclude incomplete histories/horizons, and plan held-out seeds/schedule regimes with substantially
more events. Establish a naive forecast baseline and incident-level metrics before stronger models.
