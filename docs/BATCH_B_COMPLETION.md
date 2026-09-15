# Batch B completion report

Completed locally on 2026-09-15 on `batch-b-ml-evaluation`, based on Batch A commit `f04274f`.
**Acceptance gate: passed for the requested controlled ML/evaluation scope.** This does not
mean the model meets a production performance gate: holdout degradation and budget breaches
are material findings. No Batch C work or remote operations were performed.

## Implementation and files

- `features.py`: strict 49-column telemetry-only inference schema, exact causal windows,
  one-to-one target join and time-based partition purging.
- `models.py`: training-only pipelines, isolated calibration, validation-only selection,
  trusted-local versioned joblib round trip.
- `evaluation.py`: AP and secondary row metrics, calibration bins, alert episodes, incident
  detection/lead/burden and whole-run bootstrap.
- `experiment.py`: validated separate configuration, reproducible corpus, four stages,
  pre-test choice freeze and atomic immutable outputs with hashes.
- `ml_evidence.py` and CLI: saved-result evidence regeneration, five figures and generated report.
- `configs/batch_b.json`, four new test modules, dependency spec/lock, CI name, README,
  PROJECT_STATE, ROADMAP, DECISIONS and feature/evaluation protocol documentation.

No simulator equations, operational target definitions or Batch A fixture were altered.
scikit-learn is the only new modelling framework; joblib/threadpoolctl are direct runtime uses,
with scipy/narwhals/cloudpickle installed transitively. Exact versions are locked and recorded.

## Corpus and split design

Seven four-day runs, 846 incidents, 161,280 telemetry rows, four services. Development seeds
101/202/303 contribute 384 events; held-out seeds 404/505 contribute 256; changed-regime seeds
606/707 contribute 206. Regime shifts scheduling, durations and severity without changing
simulator equations. Exact per-service/type/onset-partition counts are generated in evidence.

Development offsets: train [0,2880), calibration [2880,3744), validation [3744,4608), temporal
test [4608,5760). First 15 and final 10 minute-grid predictions are purged in each interval.
Train/calibration/validation/test eligible rows: 34260 / 10068 / 10068 / 13524. Each complete
holdout group contributes 45880 eligible rows. Labels and features retain locked 15m/10m windows.

## Models, frozen choice and actual findings

Training-prevalence, standardised regularised logistic regression and restricted histogram
boosting were compared. Hyperparameters are fixed; no search or random early-stopping split.
Each learned family also has a sigmoid mapping fitted only on calibration. Raw boosting won
validation AP. Sigmoid failed the requirement to improve both Brier and log loss. Threshold
`0.5700000000000001` was selected under the validation-only false-episode budget and frozen
with all other candidates' thresholds before final prediction. No holdout-driven retuning.

The following table is populated programmatically from generated `summary.json`:

| Partition | Rows / positives | AP | Brier | Detected / scorable | Mean lead (m) | False episodes / service-day |
| --- | --- | --- | --- | --- | --- | --- |
| validation | 10068 / 597 | 0.9199532597153073 | 0.014008618734939667 | 60 / 60 | 8.199379172222221 | 0.5721096543504172 |
| temporal_test | 13524 / 720 | 0.8800795523231142 | 0.01584777333970374 | 70 / 72 | 8.29760032904762 | 1.2777284826974267 |
| heldout_seed | 45880 / 2560 | 0.9133911284430838 | 0.013834647196806493 | 249 / 256 | 8.50489691900937 | 1.0671316477768091 |
| heldout_regime | 45880 / 2060 | 0.4512755938169232 | 0.03491791750138341 | 133 / 206 | 6.760603341854637 | 2.3853530950305144 |

Full precision/recall, ROC-AUC, log loss, confusion counts, episode precision, denominators,
misses and alert minutes are in [the generated report](../evidence/batch_b/generated/REPORT.md)
and `metrics.csv`. Validation AP for raw logistic is 0.649669510742927 and prevalence is
0.05929678188319428. Strong same-regime ranking does not survive the changed regime unchanged.
Every final partition exceeds the validation budget of one false episode per eligible service-day.

The operational rule also exposes a limitation: always-on prevalence/logistic forecasts form
long matched episodes. They can have high event recall and episode precision while alerting
through every eligible minute. Their burden is saved and disclosed; they are not useful operating
recommendations. The selected boosting point has lower burden, but is still exploratory.
A future revised rule requires a preregistered burden cap and new untouched holdouts.

## Validation and reproducibility

- `pytest -q`: **133 passed**, 12.07 seconds, one harmless macOS joblib physical-core discovery
  warning (fallback to logical cores; fit/predict thread pools explicitly limited to one).
- `ruff check .`: passed.
- `ruff format --check .`: passed (39 files checked).
- `python -m pip check`: no broken requirements. Pip also reported its disabled unwritable cache.
- Editable Python 3.14 package installation passed; all dependencies satisfy pyproject bounds.
- Full documented Batch B command passed twice (first generation, then verified corpus reuse).
  Frozen selection, all candidate predictions, all five fitted binaries, metrics, thresholds,
  event/episode results, coefficients and uncertainty are byte-identical across runs.
- Saved-evidence-only CLI passed; **all 26 compact evidence files** reproduce byte-for-byte.
- All five final PNGs were visually inspected. Calibration top-panel spacing was fixed and
  rechecked; threshold tradeoffs use discrete points rather than implying a monotonic frontier.
- Existing 71 Batch A tests remain passing. New tests include exact window causality/isolation,
  leakage and grid rejection, join eligibility, all purge boundaries, training-only scaling,
  calibration isolation, stage rejection, deterministic fitting, metric edges, episode and lead
  semantics, bootstrap unit, artefact integrity/compatibility and end-to-end freeze-order audit.
- GitHub-hosted CI **has not run**. The configured quality job will include the small Batch B
  integration test; full evidence generation remains a separate developer command.

Initial immutable audit outputs are retained locally under `data/batch_b_initial_experiment`
and `data/batch_b_initial_evidence`; final outputs are `data/batch_b_experiment` and committed
`evidence/batch_b/generated`. Regeneration did not alter frozen model choices or predictions.

## Acceptance checklist

- [x] Predictors use only the seven operational metrics available by t.
- [x] Exact per-service history grid is enforced without filling or repair.
- [x] No truth, target, eligibility, clock or future-data predictors.
- [x] Chronological partitions; no random temporal split.
- [x] Observation and label windows purged at every boundary.
- [x] Preprocessing/estimator fit, calibration and selection use only their permitted stages.
- [x] Final temporal and seed/regime holdouts scored only after persisted choices freeze.
- [x] Separate 846-event corpus; the 16-event fixture is not modelling evidence.
- [x] Prevalence, logistic and justified stronger model compared reproducibly.
- [x] Calibration measured and rejected when unsupported by validation evidence.
- [x] Row-level and incident-level evaluation implemented.
- [x] Warning lead, episodes, false-alert exposure and burden have tested definitions.
- [x] Evidence is generated from actual saved outputs; every final figure visually reviewed.
- [x] Tests, lint, formatting and dependency checks pass locally.
- [x] Documentation states implemented capabilities, negative findings and limitations.
- [x] No real-world or production-performance claims.

**Unmet requested Batch B criteria: none under local validation scope.** Remote CI remains unrun,
and production suitability is neither established nor claimed. These are not silently checked off.

## Reproduction commands

From the repository root:

```bash
source .venv/bin/activate
python -m pip install -r requirements-lock.txt
python -m pip install --no-deps --no-build-isolation -e '.[dev]'
reliability batch-b --config configs/batch_b.json --corpus data/batch_b --output data/batch_b_experiment --evidence evidence/batch_b/generated
reliability batch-b-evidence --experiment data/batch_b_experiment --output data/batch_b_repeated_evidence
pytest -q
ruff check .
ruff format --check .
python -m pip check
```

The reference paths already exist locally. For a fresh repeat, use unused output/evidence paths:

```bash
reliability batch-b --config configs/batch_b.json --corpus data/batch_b --output data/batch_b_next --evidence data/batch_b_next_evidence
```

Corpus paths are reusable only when resolved configuration and all bundle checks agree. New
corpus roots regenerate the raw bundles. Never silently overwrite a run.

## Limitations, Git and next step

Seven independent seeds, synthetic smooth precursors, unchanged service profiles/equations,
no benign precursor mimics or abrupt faults, no missing/late telemetry, coarse whole-run intervals,
trusted-local binary artefacts and no external validation. Regime holdout is a joint shift, not a
factorial mechanism study. Service metrics can proxy identity despite excluding service encoding.
No online latency/readiness or real incident contract is validated.

Work is committed in two coherent local commits on `batch-b-ml-evaluation`: implementation/tests,
then evidence/documentation. No push, PR, merge or remote change is authorised or performed.
Read `git log -2 --oneline` for their exact identifiers (a document cannot contain its own hash).

Recommended next step: review the negative regime/burden findings and the Batch B gate before
planning Batch C. Any further statistical selection needs a new evaluation protocol and fresh
holdouts. API, PostgreSQL, Docker, deployment and monitoring are deferred; Batch C has not begun.
