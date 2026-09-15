# Project vision

## Problem and users

Service teams receive large volumes of telemetry but need timely, actionable estimates of
near-term incident risk. This project will connect telemetry quality, temporal modelling,
reliable serving, persistence and evaluation into an auditable software system. Primary
users are on-call engineers, SREs and service owners; ML/data engineers operate and improve it.

## Locked prediction task

For a service at time **t**, use the preceding **15 minutes** of telemetry available by t
to estimate the probability that a defined incident **starts in (t, t + 10 minutes]**.
An incident starting exactly at t is already present and is not a future start.
The final interval of a dataset needs future coverage; unobserved outcomes are unknown.
An eventual rolling feature window will be `(t − 15 minutes, t]`.

The operational decision is whether to investigate or escalate elevated service risk,
with thresholds selected against false-alarm cost, lead time and missed incidents.
Predictions are advisory; automatic remediation is outside initial scope.

## Intended final system

Telemetry generation/ingestion → validation → persistent storage → temporal features →
ML inference → calibrated probability → operational risk decision → prediction persistence
→ monitoring and delayed-label evaluation → API and reproducible evidence.

Python modules should support both offline analysis and online integration. PostgreSQL
will store operational/prediction records; FastAPI will expose inference. These are later
milestones, not capabilities of Batch A.

## Principles

- Use only observations available at prediction time; preserve raw telemetry for audit.
- Separate operational signals, simulation truth and future targets by schema and file.
- Evaluate chronologically, with leakage-safe windows, preprocessing and calibration.
- Treat reproducibility, contracts, failure behaviour and documentation as deliverables.
- Distinguish synthetic feasibility from external validity and production performance.
- Prefer understandable mechanisms over infrastructure or modelling complexity for its own sake.

## Success criteria

A reviewer can reproduce data, models and evaluation; trace predictions to input and model
versions; inspect calibration, lead time and false-alarm trade-offs; exercise API/storage
failure cases; and understand monitoring and deployment limitations. External telemetry
validation must challenge assumptions made in simulation before real-world claims are made.
Batch gates in ROADMAP.md define incremental evidence required toward these criteria.

## Scope and non-goals

The initial domain is four fictional SaaS services. Batch A establishes local simulation,
labels and evidence. Later work adds temporal ML, serving, storage, operational monitoring,
external validation and deployment. No claims about real production outages, universal
incident definitions, autonomous repair, hyperscale processing or LLM functionality are made.
