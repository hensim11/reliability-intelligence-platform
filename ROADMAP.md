# Roadmap

## Batch A — Foundation + Telemetry System

**Goal:** reproducible, inspectable operational signals and forecasting labels.

**Outputs:** Python package/CLI, strict configuration, four service profiles, normal temporal
behaviour, four incident lifecycles, separate Parquet tables, evidence, tests and CI.

**Gate:** valid deterministic data; causal scenario effects; exact future-start labels and
censoring; saved data-derived evidence; passing local checks; accurate state and decisions.
Current gate results are in PROJECT_STATE.md.

## Batch B — ML + Evaluation (complete locally)

**Goal:** assess whether preceding telemetry supports calibrated near-term incident forecasting.

**Outputs:** causal rolling features; coverage checks; temporal train/validation/test design;
naive and statistical baselines; stronger model if justified; calibration; threshold analysis;
incident-level recall, warning lead time, false alarms and precision/recall evidence.

**Gate:** no target/truth leakage or random temporal splits; purge boundaries wherever observation
or label windows overlap partitions; preprocessing fitted only on training data; untouched test
period and held-out seeds/schedule regimes; reproducible comparisons and honest limits.

Delivered: 49 telemetry-only features, 846-event corpus, purged four-stage split, fixed prevalence /
logistic / boosting candidates, measured calibration, frozen operating points, five reviewed plots,
row/incident metrics and reproducible immutable outputs. See docs/BATCH_B_COMPLETION.md.
The schedule holdout exposes substantial degradation and the alert budget does not transfer;
the gate establishes controlled evaluation capability, not production-performance suitability.

## Batch C — Production Serving + Persistence (merged and locally accepted)

**Goal:** reusable inference with durable inputs and outputs.

**Outputs:** FastAPI, PostgreSQL schema/migrations, ingestion validation, model/feature versioning,
prediction persistence, SQL analytics, integration and failure tests, local Docker Compose.

**Gate:** offline/online feature consistency, explicit time/availability semantics, tested API and
storage behaviour, reproducible service startup and meaningful error responses.

Delivered: Alembic schema, immutable PostgreSQL telemetry/model/predictions, typed FastAPI,
explicit retrospective availability cutoff, shared Batch B inference, SQL operational analytics,
real PostgreSQL integration and HTTP evidence, concurrency exercise, and local Compose files.
Native and **clean-volume Docker Compose acceptance pass**, including restart durability,
idempotency, SQL analytics and 205 tests with zero skips. Gate 14 is closed; hosted CI and
PR review completed in PR #2, merged at `450a7d6`. See docs/BATCH_C_COMPLETION.md for historical evidence.

## Batch D — Monitoring + Reliability + External Validation (locally accepted)

**Goal:** test operational and statistical behaviour beyond controlled scenarios.

**Outputs:** data/model/application monitoring; drift signals; delayed-label evaluation; reliability
failure exercises; external telemetry study with an explicit mapping of metrics and incident definitions.

**Gate:** observable failures, verifiable delayed outcomes, documented domain mismatch, no unsupported
transfer claims, reproducible evidence of limitations and monitoring behaviour.

Delivered: immutable training reference and PostgreSQL snapshots, bounded Prometheus metrics,
certified delayed outcomes, actual database/model failure exercises and pinned all-machine SMD
ordinal study. 238 tests with zero skips, clean-volume Compose, migration and reproducibility gates
pass. External results are weak and domain mismatch is explicit; no production validity or direct
transfer claim. See docs/BATCH_D_COMPLETION.md. Batch D PR remains unmerged for review.

## Batch E — Hardening + Deployment + Portfolio Release

**Goal:** deliver an operable, reviewable end-to-end system.

**Outputs:** deployment configuration, release CI/CD, security/reliability hardening, runbooks,
final architecture and evidence, reproducible demonstration.

**Gate:** tested deployment/recovery path, bounded secrets/access, traceable artefacts, current
operating instructions, and claims supported by measured results.
