# Batch C implementation and acceptance record

Historical record: Batch C was subsequently merged in PR #2 at `450a7d6`.
Current Batch D acceptance is documented in [BATCH_D_COMPLETION.md](BATCH_D_COMPLETION.md).

Updated 2026-09-16 UTC, branch `batch-c-production-serving-persistence`, based on accepted Batch B merge
`fb7cfa8`. **Batch C is locally accepted: all 25 gates pass, including clean-volume Docker
Compose startup/smoke (Gate 14).** Hosted CI and PR review are separate workflow checks.
No merge, external deployment or Batch D work is included.

## Delivered system and review entry points

- [Serving runbook and contracts](SERVING.md): architecture, API, clocks, database, migrations,
  retry/failure semantics, model configuration, Compose and native reproduction commands.
- `src/reliability_intelligence/serving/`: `contracts.py` typed configuration/input/output;
  `artifact.py` frozen experiment validation/probe; `database.py` SQLAlchemy Core schema;
  `repository.py` transactional ingestion/scoring/history; `analytics.py` SQL summaries;
  `api.py` FastAPI factory, lifecycle, typed routes and error responses.
- `migrations/versions/c001_initial.py`: frozen PostgreSQL DDL, constraints, immutability
  triggers, four-service catalogue and latest/daily risk views; explicit Alembic entry point.
- `Dockerfile`, `compose.yaml`, `.dockerignore`: PostgreSQL + one-shot migration + non-root API.
- `tests/test_serving.py`: **72 new tests**, including **23 genuine PostgreSQL tests**.
- `scripts/batch_c_evidence.py`: reproducible real HTTP/database exercise with the saved
  reference model. [Report](../evidence/batch_c/reference/REPORT.md) and
  [machine-readable results](../evidence/batch_c/reference/results.json).
- Updated README architecture, PROJECT_STATE, ROADMAP, DECISIONS, data/feature contracts,
  dependency bounds/exact snapshot and PostgreSQL-enabled CI (hosted CI for tested source `42f4061` passed).

No existing Batch A/B implementation was changed. No fit/calibration/threshold selection
was performed during this batch. The 49-feature contract, 15-minute window, 10-minute target,
boosting_raw family and threshold **0.5700000000000001** remain frozen.

## Important decisions

C01–C12 in [DECISIONS.md](../DECISIONS.md) record the choices. Telemetry and predictions are
immutable; each model identity stores its hashes/schema/runtime/threshold once. First-success
prediction retries return the original row. Entire ingestion batches and prediction creation
have transaction boundaries; service advisory locks coordinate concurrent ingestion/scoring.

Historical requests are explicitly **retrospective event-time scoring**. Samples must lie in
`(t−15m,t]` and have arrived by a server-recorded availability cutoff. Data ingested today is
not claimed to have been known at historical t. No arrival time is accepted from clients.
Model output is advisory, with no truth/label dependency, suppression or automatic remediation.

## Exact validation results

| Check | Result |
| --- | --- |
| Full `pytest -q` with PostgreSQL configured | **205 passed, 0 failed, 0 skipped**, 14.89 s (Compose PostgreSQL repeat) |
| Existing Batch A/B tests | All **133** retained and passing |
| Batch C tests | All **72** passing, including **23** real PostgreSQL tests |
| Ruff lint | Passed |
| Ruff formatting | Passed, **59 files** |
| `python -m pip check` | No broken requirements |
| Editable package installation | Passed; Python 3.14.0 |
| Migration from empty database | Passed, revision c001; repeat upgrade, downgrade/re-upgrade and metadata drift checks passed |
| Native HTTP/PostgreSQL integration | Passed with real saved Batch B boosting model |
| Saved Batch B evidence regeneration | **26/26 files byte-identical**, no retraining |
| Docker Compose version/build/startup/smoke | **Passed**, clean build/volume, health, smoke/SQL, restart persistence and idempotency |
| Hosted GitHub Actions | Passed for `42f4061`; final evidence commit tracked in branch/PR checks |

Two upstream test-client deprecation warnings remain: Starlette's httpx adapter and its anyio
BlockingPortal alias. They do not fail tests. No test weakening or warning suppression was used.
The final numerical dependencies are unchanged from Batch B; serving dependencies were added.
The version-pinned snapshot also builds and serves in the validated Linux arm64 images;
full regression tests run on macOS against Compose PostgreSQL. Hosted CI runs Linux tests.

The test suite includes empty migrations/schema drift, SQL constraints/foreign keys/uniqueness,
ingest conflicts and batch rollback, immutable records, failed model and failed database writes,
readiness before/after dependency failures, malformed/nonfinite/unknown-service/non-UTC input,
exact window boundaries and service isolation, cutoff exclusion, artefact corruption and
incompatibility, history filters, SQL analytics, HTTP float64 round trips and concurrent retries.

## Native environment and end-to-end evidence

Python 3.14.0 on macOS 26.2 arm64. PostgreSQL **18.3**, built from upstream release source with
Apple clang 17; `configure --prefix=/tmp/rip-pg --without-icu --without-readline --without-zlib`.
The temporary UTF-8/C-locale cluster lives under `/tmp/rip-pgdata`, bound to 127.0.0.1:55432.
It is a local test fixture, not a provisioned remote database. Full source/environment hashes
and exact Python package versions are in the evidence JSON and lock.

An empty `rip_demo_final` database was migrated to c001, then served by one Uvicorn process on
loopback port 8002. The exercise ingested the first 46 minutes of Batch A telemetry for all
four services (**184 samples**). It created 120 ordinary predictions plus one contended key,
then queried **121 durable predictions** and independently recomputed their features and
probabilities offline. Model binary SHA-256:
`14dba3dcab87892e37e1a00cc6623f9d708be9f874552fcde8f35c51287350ef`.

**Parity: 121/121 windows, 49 ordered float64 columns each, exact values; maximum probability
error 0.0.** No tolerance was needed. Exact left-boundary, future exclusion, missing/duplicate/
off-grid/internal/current and wrong-service cases are also tested. A first demo attempt exposed
pandas JSON's default precision truncation; standard Python float serialization fixed the
input transport, and a dedicated HTTP/database round-trip regression guards it.

## A09 concurrency and measured latency

Eight concurrent Python urllib HTTP clients over loopback, new connection per request,
one Uvicorn worker, eight pooled database connections, unchanged native model single-thread
scope. Client elapsed times include connection, request, queueing, SQL, inference and response.
The server's startup model probe was complete; no statistical benchmark warmup or repetitions
are claimed. These figures are a modest correctness/latency exercise, **not a production SLO**.

| Workload | Requests | p50 ms | p95 ms | Outcome |
| --- | ---: | ---: | ---: | --- |
| New distinct service/time keys | 120 | 83.9970 | 116.5788 | 120 × 201 |
| Identical saved retries | 120 | 6.1184 | 7.3628 | 120 × 200 |
| One fresh key, eight concurrent clients | 32 | 5.9761 | 14.5745 | 1 × 201, 31 × 200, one UUID |

No duplicate or partial prediction records. SQL coverage/daily risk/probability summaries and
representative incomplete-history/unknown-service/conflicting-input errors are saved.
Timestamps, UUIDs and timings vary on repetition; counts and exact parity are asserted.

## Acceptance checklist (user's 25 gates)

| # | Gate | State |
| --- | --- | --- |
| 1 | PostgreSQL initialises reproducibly through migrations | Pass |
| 2 | Valid telemetry ingests/persists | Pass |
| 3 | Time/availability explicit and enforced | Pass; retrospective cutoff documented |
| 4 | No event after t participates | Pass |
| 5 | Incomplete history rejected | Pass |
| 6 | Offline/online feature parity | Pass, exact |
| 7 | Frozen model schema/integrity loading | Pass |
| 8 | Advisory API probability/decision | Pass |
| 9 | Durable traceable predictions | Pass |
| 10 | Meaningful saved history | Pass |
| 11 | SQL operational analytics | Pass |
| 12 | Controlled meaningful failures | Pass |
| 13 | Transaction/idempotency tests | Pass |
| 14 | PostgreSQL + API through Docker Compose startup | **Pass: clean-volume Compose evidence** |
| 15 | Genuine end-to-end integration | Pass, native PostgreSQL/Uvicorn |
| 16 | Concurrent local inference exercised | Pass |
| 17 | Full existing tests pass | Pass, 133 |
| 18 | New tests pass | Pass, 72 |
| 19 | Ruff lint | Pass |
| 20 | Formatting | Pass |
| 21 | Dependency integrity | Pass, native snapshot |
| 22 | Compact reproducible/reviewable evidence | Pass |
| 23 | README/state/roadmap/decisions current | Pass |
| 24 | Completion document states limitations | Pass |
| 25 | No false Batch D/E claims | Pass |

## Remaining work and limitations

[Compose report](../evidence/batch_c/COMPOSE_VALIDATION.md) and
[machine-readable evidence](../evidence/batch_c/compose_validation.json) close the independent
review’s remaining Gate 14. Docker Desktop installation was explicitly authorised. The
clean source tested was `42f40614e922384eee64d4fbe1dfcccd321df17d`; later close-out commits
record evidence/docs without changing implementation. The original native results remain intact.
Final hosted CI and PR review must be checked against the pushed evidence commit; no merge.

The synthetic model remains unsuitable for a production-performance claim: changed-regime
holdout degraded substantially, and final partitions breached the validation false-alert
budget. No external validity, delayed-label/drift monitoring, frontend, cloud infrastructure,
authentication, backup/recovery or production SLO is delivered. Fixed four-service scope,
trusted-local joblib, retrospective availability semantics and single-worker local measurement
are deliberate limits, not hidden production capabilities.

Implementation `05d987d`, native documentation/evidence `d986a83`, and acceptance runner
`42f4061` remain separate. Subsequent commits record Compose close-out evidence. See git
history and the branch/PR checks for those identifiers and hosted validation.
