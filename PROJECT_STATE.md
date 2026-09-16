# Project state

Updated: 2026-09-16. **Batch D's original local acceptance and committed evidence are attributable
to implementation `92ebb54`; the current reviewed implementation is `1248c9e`.** The review fixes
were validated separately against PostgreSQL: **241 passed, 0 skipped**. Batch C merged on main at
`450a7d6`; Batch D PR review remains open and separate from local acceptance.

Target unchanged: use telemetry in `(t−15m,t]` to estimate incident starts in `(t,t+10m]`.
Advisory investigation only; Batch E and production-performance claims remain out of scope.

## Delivered

- Batch A: deterministic four-service simulation, separate truth/labels, exact telemetry grid,
  immutable Parquet bundles and reproducible evidence.
- Batch B: unchanged 49 float64 telemetry-only features, purged chronological stages,
  846-event seven-run corpus, frozen model/threshold, immutable model/evaluation evidence.
- Batch C: FastAPI ingestion/prediction/history and live/ready routes; PostgreSQL telemetry,
  model metadata and predictions; Alembic migrations; immutable records; atomic transactions
  and idempotency; SQL latest/daily/coverage/probability analytics; typed configuration.
- Shared Batch B feature/model implementation, trusted-local manifest/schema/runtime/config
  validation, explicit event-time versus server availability cutoff. Historical scores are
  retrospective; late data is never claimed to have been available at historical t.
- Local Compose files, native PostgreSQL/Uvicorn integration and measured concurrency,
  72 added tests and compact evidence. No model training or holdout tuning in Batch C.

## Frozen result and interpretation

Selected `boosting_raw`, threshold `0.5700000000000001`. Raw family selected by validation AP;
sigmoid was not selected because it failed to improve both validation Brier and log loss.

| Partition | Rows / positives | AP | Brier | Detected / scorable | Mean lead (m) | False episodes / service-day |
| --- | --- | --- | --- | --- | --- | --- |
| validation | 10068 / 597 | 0.9199532597153073 | 0.014008618734939667 | 60 / 60 | 8.199379172222221 | 0.5721096543504172 |
| temporal_test | 13524 / 720 | 0.8800795523231142 | 0.01584777333970374 | 70 / 72 | 8.29760032904762 | 1.2777284826974267 |
| heldout_seed | 45880 / 2560 | 0.9133911284430838 | 0.013834647196806493 | 249 / 256 | 8.50489691900937 | 1.0671316477768091 |
| heldout_regime | 45880 / 2060 | 0.4512755938169232 | 0.03491791750138341 | 133 / 206 | 6.760603341854637 | 2.3853530950305144 |

These are controlled synthetic feasibility results. The changed regime causes a substantial
ranking/detection loss, and all final partitions exceed the validation false-episode budget.
Always-on baselines expose a weakness in an episode-only budget: their matched long episodes
hide excessive burden unless alert minutes and row precision are considered. The rule and
choices were not revised after holdout inspection. No production operating recommendation.

## Native reference validation (2026-09-15)

- Full pytest with real PostgreSQL: **205 passed**, 0 skipped, 14.23 s (133 existing + 72 new).
- Ruff lint/format passed (58 files); pip check reports no broken requirements.
- Empty database migrations, repeated upgrade, downgrade/re-upgrade and schema drift passed.
- HTTP evidence: 184 telemetry rows, 121 persisted predictions; all 49 features and frozen
  probabilities match offline exactly across 121 windows, maximum probability error 0.0.
- Eight concurrent clients: new-prediction p50 84.00 ms / p95 116.58 ms; 32-request same-key
  race gave one created prediction and 31 identical retries. No production latency SLO.
- Saved Batch B evidence regenerated: all 26 files byte-identical, without training.
- Python 3.14.0/macOS arm64, PostgreSQL 18.3; exact snapshot in requirements-lock.txt.

## Compose close-out (2026-09-16 UTC)

- Tested clean source `42f40614e922384eee64d4fbe1dfcccd321df17d`; later evidence/docs commits
  do not change the tested implementation.
- Docker Desktop 4.91.0 / Engine 29.8.0 / Compose 5.5.1, Linux arm64 containers,
  PostgreSQL 18.3 and Python 3.14.0. Clean build, empty-volume startup, c001 and health pass.
- Ingested 16 rows, created/retrieved one prediction; SQL analytics pass. Database/API restart
  preserves 16/1 rows; retry returns the same UUID, no duplicates; migration rerun stays c001.
- **205 passed, zero skips**, 14.89 s; 23 real PostgreSQL tests. Ruff lint and format
  (59 files), dependency integrity pass. Two unchanged upstream deprecation warnings.
- Disposable containers and volume removed after checks.
- [hosted CI for tested source](https://github.com/hensim11/reliability-intelligence-platform/actions/runs/35012633105) passed. The evidence commit requires its own CI; see branch checks/PR for the final result.
- [Compose report](evidence/batch_c/COMPOSE_VALIDATION.md) records hashes, commands,
  environment deviations and log review; the earlier native reference remains unchanged.

## Review and next step

1. [Batch C acceptance record](docs/BATCH_C_COMPLETION.md) — all 25 local gates passed.
2. [Serving contract/runbook](docs/SERVING.md) — API, storage, clocks, migration and Compose steps.
3. [HTTP/PostgreSQL evidence](evidence/batch_c/reference/REPORT.md).
4. [Decisions](DECISIONS.md), especially C01–C12.
5. [Batch B completion/findings](docs/BATCH_B_COMPLETION.md).

## Batch D original acceptance evidence (`92ebb54`)

- Branch `batch-d-monitoring-reliability-external-validation` from clean updated main `450a7d6`.
- Training-only immutable monitoring reference: 34,260 rows, 49 features plus frozen probability;
  deterministic boundaries/heuristic configuration, model identity and sealed source/file hashes.
- Alembic d001: immutable monitoring snapshots and separate incident starts/coverage certificates.
  Trusted local transactional imports, certified delayed labels, bounded read-only retrieval.
- Process-local low-cardinality Prometheus metrics; liveness/readiness separation preserved.
- Clean-volume Compose evidence: **238 passed, 0 skips, 15.83 s**; lint, formatting (76 files),
  dependency integrity and migration upgrade/repeat/downgrade/re-upgrade/schema drift pass.
- Real outage: live 200, ready 503, predictions 503, metrics 200; recovery and restart verified.
  Durable counts: 12,380 telemetry, 520 predictions, 1 incident, 1 certificate, 3 snapshots.
- Reference-like monitoring: 11,460 feature samples, 400 probabilities; all 50 distributions stable,
  probability PSI 0.0482073989063377. Shift: 800 feature samples, 120 probabilities; all 50 severe,
  probability PSI 2.0296097096569135. Delayed fixture: 30 eligible, 1 positive, 0 detected.
- Original Batch C HTTP parity: 121 windows/all 49 features exact, maximum probability error 0.0;
  same-key race gives 1 created/31 reused. These remain synthetic/local diagnostics.
- All 28 SMD machines validated at pinned upstream commit. Separate step-based study: logistic
  available on 22 machines, final AP 0.005968969761866583, 1/85 starts, 424 false episodes and
  2,777 alert rows. Six machines have no development-training positive starts. Prevalence baseline
  covers all 28, detects 0/108. Differing denominators and undefined metrics are explicit.
- Reference (2 files), study (5) and compact external export (9) regenerate byte-identically in
  the recorded environment. Operational clocks, UUIDs and latencies intentionally vary.

## Batch D reviewed implementation (`1248c9e`)

Review fixes canonicalize timezone-aware snapshot cutoffs to UTC before identity, queries and
persistence; preserve sub-minute precision; and observe unexpected HTTP failures with bounded
`5xx`, duration and rejection metrics before re-raising. Monitoring documentation now accurately
describes finite underflow/overflow binning and non-finite invalid observations. This source-code
follow-up passed the full disposable-PostgreSQL suite separately: **241 passed, 0 skipped**. It did
not alter the immutable `92ebb54` evidence or its measured results.

See [Batch D completion/gates](docs/BATCH_D_COMPLETION.md), [monitoring](docs/MONITORING.md),
[external study](docs/EXTERNAL_VALIDATION.md) and [evidence index](evidence/batch_d/README.md).

## Remaining limitations and Batch E

No real incident-prediction validity, direct model transfer or ten-minute SMD warning claim.
Drift thresholds are operational heuristics; snapshots require explicit CLI scheduling. Application
counters reset on restart and cannot supply durable rejected-request history. Registry completeness
is trusted certification; false certificates need a future versioned correction policy. Historical
predictions remain retrospective. Authentication, TLS, deployment, backups/recovery policy,
production SLOs and operator response automation remain Batch E. No deployment occurred.

The Batch D PR must remain unmerged. Existing Batch B holdouts cannot be reused for tuning.

Generated datasets/models remain ignored under `data/`. Compact Batch C evidence is under
`evidence/batch_c/reference`; repeat Batch B evidence is ignored under `data/batch_c_batch_b_recheck`.

## Validation commands

```bash
source .venv/bin/activate
export RIP_TEST_DATABASE_URL='postgresql+psycopg://USER@127.0.0.1:55432/rip_test'
# Tests reset this database's public schema. Use a disposable database only.
pytest -q
ruff check .
ruff format --check .
python -m pip check
```
