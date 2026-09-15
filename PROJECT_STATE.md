# Project state

Updated: 2026-09-15. **Batch C serving/persistence implemented and native local validation
passes. Full acceptance is pending Docker Compose runtime validation: Docker is absent.**

Target unchanged: use telemetry in `(t−15m,t]` to estimate incident starts in `(t,t+10m]`.
Advisory investigation only; Batch D/E and production-performance claims remain out of scope.

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

## Latest validation

- Full pytest with real PostgreSQL: **205 passed**, 0 skipped, 14.23 s (133 existing + 72 new).
- Ruff lint/format passed (58 files); pip check reports no broken requirements.
- Empty database migrations, repeated upgrade, downgrade/re-upgrade and schema drift passed.
- HTTP evidence: 184 telemetry rows, 121 persisted predictions; all 49 features and frozen
  probabilities match offline exactly across 121 windows, maximum probability error 0.0.
- Eight concurrent clients: new-prediction p50 84.00 ms / p95 116.58 ms; 32-request same-key
  race gave one created prediction and 31 identical retries. No production latency SLO.
- Saved Batch B evidence regenerated: all 26 files byte-identical, without training.
- Python 3.14.0/macOS arm64, PostgreSQL 18.3; exact snapshot in requirements-lock.txt.
- Docker command unavailable; Compose build/startup/smoke **not run**. Hosted CI unrun.

## Review and next step

1. [Batch C acceptance record](docs/BATCH_C_COMPLETION.md) — all 25 gates and the open Docker gate.
2. [Serving contract/runbook](docs/SERVING.md) — API, storage, clocks, migration and Compose steps.
3. [HTTP/PostgreSQL evidence](evidence/batch_c/reference/REPORT.md).
4. [Decisions](DECISIONS.md), especially C01–C12.
5. [Batch B completion/findings](docs/BATCH_B_COMPLETION.md).

Branch `batch-c-production-serving-persistence`, starting at accepted Batch B merge `fb7cfa8`.
Two coherent local commits cover implementation and documentation/evidence; no push, PR, merge
or external deployment. Use `git log -2 --oneline` for their identifiers.

**Next required acceptance action:** run documented Docker Compose build/startup/smoke on a
Docker-capable host and record evidence. Do not mark full Batch C accepted before this passes.
Monitoring, external validation and deployment remain deferred. Any statistical revision needs
fresh holdouts; existing Batch B holdouts cannot be reused for tuning.

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
