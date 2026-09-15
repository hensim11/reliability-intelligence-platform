# Project state

Updated: 2026-09-15. **Current milestone: Batch B complete locally; ready for review.**
Batch A remains intact. Batch C has not started. Objective: use telemetry in `(t−15m,t]`
to estimate whether a service incident starts in `(t,t+10m]`.

## Completed

- Batch A: validated four-service telemetry, separate truth/nullable labels, exact configured
  grid, deterministic simulation, immutable Parquet bundles and 71 original tests.
- Batch B: 49 telemetry-only float64 features, exact causal per-service one-minute windows,
  strict inference schema, key-aligned target eligibility and chronological boundary purges.
- Separate seven-run, 846-event corpus: three development seeds, two held-out seeds, two
  changed schedule/duration/severity regime seeds, four days each, 161280 telemetry rows.
- Training/calibration/validation/temporal-test stages, fixed prevalence/logistic/boosting
  candidates, measured sigmoid calibration and validation-frozen thresholds.
- Immutable model/config/schema/version/hash artefacts and keyed prediction outputs.
- Row metrics, reliability bins, incident detection/lead, episode precision/false-alert burden,
  whole-run uncertainty and per-service diagnostics. No active/recovery truth suppression.
- CLI corpus/training/evaluation and saved-evidence regeneration; five reviewed PNGs,
  machine-readable tables/manifests and generated report under `evidence/batch_b/generated`.
- 133 passing tests, including stage isolation and execution-order audit before holdout scoring.
- Feature/evaluation protocols, decisions, completion checklist, README and roadmap updated.

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

## Validation and reproducibility

- `pytest -q`: 133 passed, 12.07s; one macOS joblib core-discovery fallback warning.
- `ruff check .` / `ruff format --check .`: pass; `python -m pip check`: no broken requirements.
- Python 3.14.0, macOS arm64; exact runtime versions in requirements-lock.txt and evidence.
- Full CLI generation/evaluation passed twice. All five models, keyed predictions, frozen
  decisions and numerical evaluation outputs are byte-identical across runs.
- Evidence-only CLI reproduced all 26 compact files byte-for-byte.
- All five final figures were visually reviewed; calibration layout corrected and rechecked.
- GitHub-hosted CI is configured but **unrun**; local success is not remote CI success.

## Gate and review entry points

**Batch B's requested local acceptance gate passes.** The complete 16-item checklist, exact
commands, validation details, module list and limitations are in
[docs/BATCH_B_COMPLETION.md](docs/BATCH_B_COMPLETION.md).

- [Generated evidence/report](evidence/batch_b/generated/REPORT.md)
- [Feature contract](docs/FEATURE_CONTRACT.md)
- [Evaluation protocol](docs/EVALUATION_PROTOCOL.md)
- [Decisions](DECISIONS.md)
- [Batch A completion record](docs/BATCH_A_COMPLETION.md)

Raw corpus: `data/batch_b/`; final experiment: `data/batch_b_experiment/` (both Git-ignored).
Initial audit outputs and repeated evidence remain ignored under `data/batch_b_initial_*`
and `data/batch_b_repeated_evidence`. No output was silently overwritten.

## Commands

```bash
source .venv/bin/activate
reliability batch-b --config configs/batch_b.json --corpus data/batch_b --output data/batch_b_next --evidence data/batch_b_next_evidence
pytest -q
ruff check .
ruff format --check .
python -m pip check
```

Use unused output/evidence paths. Existing corpus bundles are reused only after strict
configuration/hash/semantic validation. See README for fresh setup and evidence-only commands.

## Git and next step

Branch `batch-b-ml-evaluation`, based on completed Batch A `f04274f`. Two coherent local
Batch B commits cover implementation/tests and evidence/documentation. No remote, PR, push,
merge or deployment was performed. See `git log -2 --oneline` for commit identifiers.

Review Batch B findings before planning Batch C. A revised statistical operating rule needs
fresh holdouts and a hard alert-burden constraint; existing holdouts cannot be reused for tuning.
API, PostgreSQL, Docker, external validation, deployment and monitoring remain deferred.
