# Batch C: local serving and persistence

## Architecture and scope

FastAPI validates operational requests; SQLAlchemy Core + psycopg persist them in PostgreSQL.
Alembic owns schema changes. Startup reads a trusted-local Batch B experiment, validates its
manifest/sidecars/runtime/configuration, loads the frozen `boosting_raw` model and probes
inference. There is no training in this lifecycle. PostgreSQL history is passed to the original
`features.build_features`; no formulas were copied and no Batch A/B equations changed.

The API is an unauthenticated **loopback-only local service**. Compose binds host ports to
127.0.0.1. Authentication, retention/recovery operations and distributed scaling remain later work.
Batch D adds monitoring and a separate external study; see the current d001 extension below.
No production deployment/performance claim.

## Time and availability: two clocks, explicitly retrospective

- `timestamp` is event time. API inputs require a whole-minute ISO-8601 string ending in
  `Z` or `+00:00`, in years 2000–2100. Naive/nonzero-offset, off-grid and submicrosecond
  nonzero timestamps fail. PostgreSQL uses `timestamptz`; connections set timezone UTC.
- `ingested_at` is server database time, assigned on insert and never supplied by a client.
  Event timestamps after current database time fail; old samples are accepted unchanged.
- A prediction request names event time **t**. Its target remains an incident start in
  `(t,t+10m]`, and its observation window remains `(t−15m,t]` (15 points, t−14m through t).
- The server acquires the service transaction lock, then records `available_as_of` using
  the database clock. Only committed samples with `ingested_at <= available_as_of` and
  event time in the requested window can participate. Same-service ingestion uses the same
  lock, so a concurrent ingestion cannot slip into the selected snapshot.
- **“Available by t” is not claimed for historical requests.** Ingesting old telemetry today
  cannot establish what was known at historical t. The API performs event-time scoring using
  data available at the recorded scoring cutoff. A historical result is retrospective,
  including when its forecast horizon has already elapsed. Even near-live scoring waits for
  the sample at t to arrive; ingestion latency is visible in the returned timestamps.
- No user-supplied/backdated availability timestamps, historical-as-of query, truth-based
  suppression, future samples or imputation. A missing internal/current minute returns
  `incomplete_history` with the number of missing minutes. Failed requests create no prediction.

This makes late arrival explicit without silently claiming historical online performance.
A strict original-availability forecasting study needs independently recorded arrival history;
Batch A/B simulated event times cannot provide it.

## Database contract (Alembic revision `c001`)

| Object | Key / purpose |
| --- | --- |
| `services` | Fixed four-service allowlist, seeded by migration; no ML encoding |
| `telemetry` | Primary key `(service_id,timestamp)`, seven non-null float8 metrics, `ingested_at` |
| `models` | SHA-256 identity over required artefact hashes; name, binary hash, feature version, frozen threshold, hashes and runtime metadata stored once |
| `predictions` | UUID; service/event time/model FK, probability, scoring cutoff, produced time; unique `(service_id,timestamp,model_id)` |
| `latest_risk` | Latest event-time result per service, deterministic ties by production time and UUID |
| `daily_risk` | Service/UTC-day/model counts, elevated counts, mean/min/max/median probability |

Foreign keys, non-null constraints, finite/nonnegative metric checks, error/resource ranges,
p95≥p50, whole-minute supported times, probability/threshold [0,1], and chronological
constraints are enforced in SQL. UPDATE/DELETE triggers protect telemetry, models and
predictions. Administrative schema changes/TRUNCATE remain trusted maintenance operations.
No incidents or labels are stored here. No duplicate feature vectors or decision booleans:
window bounds are derived from t, and `probability >= models.threshold` derives the decision.
Stored models are immutable, so the derivation is stable.

Telemetry's primary key serves window retrieval. Prediction indexes support per-service and
global reverse-time history. `serving.analytics.coverage` counts expected/observed/missing
minutes in `[start,end)` for all four services, including absent services (maximum 31 days).
`risk_summary` aggregates probabilities/volume over `[start,end)`, grouped by model and service.
Neither function uses incident truth. Pass aware whole-minute UTC datetimes, as for API inputs.

```sql
SELECT * FROM latest_risk ORDER BY service_id;
SELECT * FROM daily_risk ORDER BY day, service_id;
```

Migrations contain a frozen SQL snapshot, not imports of evolving application table definitions.
The integration suite upgrades from an empty schema, checks SQLAlchemy metadata drift,
repeats upgrade, downgrades to base and upgrades again. Startup verifies revision, columns,
service catalogue and SELECT/INSERT permissions; it never creates schema objects.

## API contract

OpenAPI: `/openapi.json`; interactive local documentation: `/docs`.

| Method/path | Behaviour |
| --- | --- |
| `GET /health/live` | 200 when the application can answer, independent of dependencies |
| `GET /health/ready` | 200 after artefact validation/probe and usable current database; otherwise 503 |
| `POST /telemetry` | `{ "samples": [...] }`, 1–1000 records; 200 with inserted/unchanged counts |
| `POST /predictions` | `{ "service_id": "api-gateway", "timestamp": "2026-01-05T00:15:00Z" }`; 201 on creation, 200 on identical retry |
| `GET /predictions` | Optional service_id, inclusive start, exclusive end, limit 1–1000 (default 100); newest event time first, UUID tie-break |

Use `service_id=...&limit=1` for the latest saved result. Empty history returns `[]`.
History includes all model identities; each response carries its model metadata.
There is bounded result retrieval, not unbounded export or cursor pagination.

Telemetry fields are exactly `schemas.TELEMETRY_COLUMNS`: timestamp, service_id,
request_rate_rps, latency_p50_ms, latency_p95_ms, error_rate, cpu_utilisation_pct,
memory_utilisation_pct, dependency_latency_ms. JSON numbers are required (bool/string/null
and nonfinite metrics fail). The authoritative Batch A metric validator enforces ranges.
Extra keys including labels/truth fail. Batch ordering is normalised explicitly; duplicate
keys *within* a batch fail, even if identical. An existing identical sample is a no-op;
changed values at the same key return 409. Existing ingestion timestamps are preserved.

Prediction responses include UUID, service_id, timestamp, produced_at, available_as_of,
model_id, model_name, model_sha256, feature_version, threshold, probability,
`elevated-risk`/`not-elevated-risk`, window_start (exclusive) and window_end (inclusive).
The decision is an **advisory investigation signal**, never an automatic remediation command.

Errors have `{ "error": { "code": ..., "message": ... } }` plus bounded field/context details.
422 covers malformed/invalid requests, incomplete history and future timestamps; 409 covers
conflicting immutable telemetry; 503 covers model/dependency failure. Client errors do not
expose exception traces or database details. Diagnostics stay in server logs.

## Transactions, retries and concurrency

Ingestion validates the entire batch before writing. All its writes run in one transaction;
a conflict/future row rolls back preceding writes. Service locks are acquired in sorted order.
Scoring acquires the same PostgreSQL transaction advisory lock for its service, checks the
unique prediction key, retrieves history, computes features, predicts and inserts atomically.
A failed feature/model/database operation rolls back. No successful-looking partial prediction.

The first successful `(service,t,model)` result is permanent. Retries return the original UUID,
probability and cutoff. They do not recompute after late data. An incomplete attempt leaves
no row and may be retried after the missing input arrives. Immutable complete windows make
results reproducible; direct administrative changes are outside this API contract.

Each process uses a bounded eight-connection pool, no overflow, five-second pool/lock wait
and ten-second SQL timeout. FastAPI sync handlers run in its worker thread pool. A process
lock serialises native model calls because Batch B's threadpoolctl scope changes process-wide
thread limits. PostgreSQL locks also work across API processes; tested deployment/benchmark
uses **one Uvicorn worker**. Overload may return 503; no SLO or multiworker benchmark claim.

## Frozen model configuration

`RIP_MODEL_DIR` names the **experiment directory**, not a single binary. Required files:
`manifest.json`, `boosting_raw.joblib`, `boosting_raw.json`, `selection.json`,
`feature_schema.json`, `environment.json`, `config.json`.
The manifest hashes all six serving inputs. The loader requires Batch B manifest v1.0,
feature v1.0/49 names/order/float64, the fixed four services and 15/10/60-second configuration,
`boosting_raw`, and threshold **0.5700000000000001**. Python major/minor must match; NumPy,
pandas, sklearn, SciPy, joblib and threadpoolctl versions must match exactly. Platform and
Python patch need not match; the exact tested environments are recorded separately.

Only load **trusted local** artefacts. joblib executes Python during loading; hashes establish
integrity, not authenticity. No model upload route exists. Readiness probes the already-fitted
model with a 49-column frame. Missing/corrupt/incompatible inputs leave liveness available and
readiness at 503. Repair initialisation failures and restart; no automatic model reload.
Post-start database outages are checked on readiness and return controlled 503s on operations.

## Local Docker Compose workflow

Docker Engine/Desktop with the `docker compose` plugin is required. The clean-volume
workflow passed with Desktop 4.91.0, Engine 29.8.0 and Compose 5.5.1 on macOS arm64,
using PostgreSQL 18.3/Python 3.14.0 Linux arm64 images. This bundled Compose release
supersedes the original v2 prerequisite. See the
[acceptance report](../evidence/batch_c/COMPOSE_VALIDATION.md) for exact evidence and deviations.

From a fresh checkout, follow the root README Python setup and regenerate Batch B artefacts
if the ignored local experiment is absent. Do not modify or retune the saved reference.
Create an ignored `.env` file (choose a URL-safe local password; example is a placeholder):

```dotenv
RIP_DB_PASSWORD=replace-with-a-local-alphanumeric-password
RIP_MODEL_DIR=/absolute/path/to/reliability-intelligence-platform/data/batch_b_experiment
```

```bash
docker compose config --quiet
docker compose build
docker compose up -d --wait
# The migrate one-shot service runs alembic upgrade head before API startup.
# Explicit migration procedure, e.g. after changing schema:
docker compose run --rm migrate
curl --fail http://127.0.0.1:8000/health/live
curl --fail http://127.0.0.1:8000/health/ready
```

If the ignored Batch A telemetry fixture is absent, generate it first:

```bash
reliability generate --config configs/batch_a.json --output data/batch_a
```

Generate an operational-only sample request locally, preserving JSON float64 round trips:

```bash
python - <<'PY'
import json
from pathlib import Path
import pandas as pd
frame = pd.read_parquet('data/batch_a/telemetry.parquet')
frame = frame.loc[(frame.service_id == 'api-gateway')].head(16)
rows = frame.to_dict(orient='records')
for row in rows:
    row['timestamp'] = row['timestamp'].isoformat()
Path('data/ingest-example.json').write_text(json.dumps({'samples': rows}))
Path('data/predict-example.json').write_text(json.dumps({
    'service_id': 'api-gateway', 'timestamp': rows[-1]['timestamp']}))
PY
curl --fail -H 'Content-Type: application/json' --data-binary @data/ingest-example.json http://127.0.0.1:8000/telemetry
curl --fail -H 'Content-Type: application/json' --data-binary @data/predict-example.json http://127.0.0.1:8000/predictions
curl --fail 'http://127.0.0.1:8000/predictions?service_id=api-gateway&limit=1'
docker compose exec db psql -U reliability -d reliability -c 'SELECT * FROM daily_risk'
docker compose down
# Explicit destructive reset of this local stack, only when data is disposable:
docker compose down --volumes
```

PostgreSQL 18 stores its named volume at `/var/lib/postgresql`. The image runs the API as a
non-root user and mounts the model read-only. No binaries/data/secrets enter the build context.
This local stack uses the database owner for migrations and API; least-privilege deployment
roles, TLS and authentication are deferred, so do not expose it outside loopback.

### Automated acceptance repeat

With the existing frozen model, telemetry fixture, ignored `.env` and `.venv` available, use
a new project/work/output name for every attempt. Host ports 5432/8000 must be free.
Ensure Docker and its credential helper are on PATH (on this Mac:
`export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"`).

```bash
.venv/bin/python scripts/validate_compose.py \
  --project rip-batchc-repeat \
  --work data/batch_c_compose_repeat \
  --output data/batch_c_compose_repeat_evidence
```

The runner refuses an existing project/volume, builds with `--pull --no-cache`, checks
health/ingestion/prediction/history/SQL, restarts both services, verifies idempotency and
reruns c001. It creates a separate disposable `reliability_test` database for all 205 tests,
then runs lint/format/dependency checks and removes its containers and volume on success.
Failures leave local logs and the stack for diagnosis; inspect them before cleaning up.
The smoke database is never used as the schema-resetting test database. No training occurs.

## Native setup, tests and evidence

With PostgreSQL 18 and empty databases `rip_test` and `rip_demo` already created:

```bash
export RIP_DATABASE_URL='postgresql+psycopg://USER@127.0.0.1:55432/rip_demo'
export RIP_MODEL_DIR="$PWD/data/batch_b_experiment"
alembic upgrade head
uvicorn reliability_intelligence.serving.api:create_app --factory --host 127.0.0.1 --port 8000
# In another terminal with the same variables:
python scripts/batch_c_evidence.py --telemetry data/batch_a/telemetry.parquet --output data/batch_c_next_evidence
```

The evidence workflow requires an empty telemetry/prediction database and a **new** output
directory. It performs 184-sample ingestion, 120 new predictions, 120 retries and a 32-request
same-key race, then compares all 121 stored windows/probabilities with offline Batch B and
queries SQL analytics. It records source/input/model hashes, environment, latency percentiles
and representative errors. Dynamic times, UUIDs and timings vary; schema/counts/feature and
probability parity must reproduce. No training occurs. Use unused database/output names for
reruns; failed attempts can remain local for diagnosis.

```bash
export RIP_TEST_DATABASE_URL='postgresql+psycopg://USER@127.0.0.1:55432/rip_test'
pytest -q
ruff check .
ruff format --check .
python -m pip check
```

**Tests reset the public schema of RIP_TEST_DATABASE_URL. Only use a disposable database.**
Without this variable PostgreSQL tests explicitly skip; that is not full validation. CI now
provisions PostgreSQL and sets the variable. Hosted CI passed for tested source `42f4061`;
consult final branch/PR checks for later evidence commits.
Test models are small temporary Batch B-compatible artefacts, not committed binaries. The
HTTP evidence uses the actual saved Batch B boosting reference.

Dependency compatibility references: [FastAPI release notes](https://fastapi.tiangolo.com/release-notes/),
[psycopg support](https://www.psycopg.org/). See `requirements-lock.txt` for the validated snapshot;
no unrelated pre-existing dependencies were upgraded.

## Batch D extension (current schema d001)

Batch C is merged at `450a7d6`; historical Batch C evidence above remains unchanged. The current
application requires `d001`, which adds immutable monitoring snapshots and separately stored incident
starts/completeness certificates. Run `alembic upgrade head` before restarting the new application.
A c001 application and d001 database intentionally fail readiness rather than silently accepting
schema drift. Roll back application/schema together; downgrade drops only Batch D tables and is
destructive to their contents. Use it only in the documented disposable validation exercises.

New read-only routes: `/metrics`, `/monitoring/drift`, `/monitoring/delayed`. Snapshot routes accept
start/end/limit and never compute or write. See [MONITORING.md](MONITORING.md) for CLI imports,
certification, monitoring-reference validation and metrics reset behaviour. Outcome tables cannot
influence inference. Authentication, TLS, backup/restore and production SLOs remain Batch E.

The current acceptance runner is `scripts/validate_batch_d.py`; it uses ports 55435/58001, a new
Compose project and separate smoke/test/exercise databases. The historical Batch C runner remains
an archived c001-specific path; Batch D's runner incorporates those serving/regression checks and
adds the failure exercises. The HTTP parity script can still run against an empty current database.
