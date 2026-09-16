# Batch B evaluation protocol

## Objective and decision ordering

Controlled feasibility of near-term **future incident starts**, not current-anomaly classification
or real-world forecasting validation. Every eligible row follows Batch A's target definition,
including active/recovery rows. No random row split, resampling, class weighting, oversampling,
post-test refitting or hyperparameter search is used.

1. Generate/verify all configured bundles. Computing features and auditing counts are mechanical;
   holdout outcomes are not used for candidate or operating-point decisions.
2. Fit preprocessing and estimators on `train` only.
3. Fit one-dimensional sigmoid probability mappings on `calibration` only.
4. Compare raw model families by validation average precision. Choose sigmoid for the winning
   family only if **both** validation Brier score and log loss strictly improve. Ties in raw AP
   use lower log loss, then name. Thresholds for **every** candidate use validation only.
5. Persist `selection.json` (including all thresholds) and all models before generating any
   temporal-test or held-out prediction. The integration test audits this execution order.
6. Score frozen candidates on temporal test, held-out seeds and changed regime, without revising
   choices. Reruns verify reproducibility; they are not new independent test evaluations.

The fitting and selection functions reject wrong-stage tables. These guards supplement, not
replace, the orchestrator's tested timestamp-based partition assignments. A malicious caller
could falsify stage labels; the package is a trusted local pipeline, not a security boundary.

## Corpus

`configs/batch_b.json` embeds a separately validated simulation configuration: four services,
5,760 minutes (four days), one-minute telemetry, 32 generated incidents per service, unchanged
Batch A dynamics and profiles. Each seed starts 2026-01-05 00:00 UTC. The fixture in `data/batch_a`
is never a model-development input.

| Group | Seeds | Schedule | Incidents in reference run |
| --- | --- | --- | --- |
| Development | 101, 202, 303 | Batch A stratified schedule | 384 |
| Held-out seeds | 404, 505 | Same generating regime, independent RNG streams | 256 |
| Held-out regime | 606, 707 | Renewal-like non-stratified schedule | 206 |

Total: 846 incidents, 161,280 telemetry rows, 28 run-days / 112 raw service-days. All events are
independently realised conditional on shared simulator assumptions; they are not 846 independent
real-world cases. Exact counts by run, service, type and onset partition are generated in
`corpus.csv` and `event_counts.csv`, with separate eligible/scorable denominators in saved metrics.

Regime scheduling starts after the usual warmup and draws a gap uniformly from 45–210 minutes
before each lifecycle. Precursor duration is uniform 15–45m, active 20–50m, recovery 10–35m,
severity 0.6–1.4; incident type is independently uniform over the four types. The next gap starts
at recovery end; stop before the existing cooldown. No within-service overlap or equation change.
This jointly shifts spacing, frequency, duration and severity. It is deliberately not a fitted
production arrival process and cannot isolate individual sources of distribution shift.

Hundreds of events across independent runs support this **small fixed comparison** and provide
60 calibration and 60 validation onsets. Two held-out seeds per regime remain few independent
replicates. More complex model search or confident population-level uncertainty is not justified.
The full reproduction remains separate from fast CI fixtures.

## Temporal partitions and purge

Partitions are half-open `[start,end)`. The development boundaries, as offsets from run start:

| Stage | Offset minutes | UTC start | UTC exclusive end | Eligible rows across 3 seeds | Eligible positives |
| --- | --- | --- | --- | --- | --- |
| Train | [0,2880) | Jan 5 00:00 | Jan 7 00:00 | 34260 | 1920 |
| Calibration | [2880,3744) | Jan 7 00:00 | Jan 7 14:24 | 10068 | 600 |
| Validation | [3744,4608) | Jan 7 14:24 | Jan 8 04:48 | 10068 | 597 |
| Temporal test | [4608,5760) | Jan 8 04:48 | Jan 9 00:00 | 13524 | 720 |

The machine-readable authority is generated `boundaries.csv` / `splits.csv`. Retain a prediction
only if `t−15m >= start` **and** `t+10m < end`. Thus the first retained minute is start+15m and
last is end−11m. This conservative full-window rule agrees with the existing coverage contract,
even though the open-left boundary's sample is not included. It purges the first 15 and last 10
minute-grid timestamps. No row-offset assumptions. At internal boundaries 900 additional
feature-ready rows across seeds/services are purged, including three positive rows. Dataset-edge
ineligible histories/horizons are excluded before this assignment and separately inferable from
raw versus eligible counts. Held-out groups each have 45,880 eligible rows over their full runs.

## Candidates and calibration

- Training-prevalence `DummyClassifier(strategy='prior')`: a constant probability, no calibration.
- Logistic regression: training-fitted StandardScaler in a single pipeline, L2 C=1, max_iter=2000,
  no class balancing. Interpretable additive statistical baseline.
- Histogram gradient boosting: 100 iterations, learning rate 0.1, at most 15 leaves, minimum 30
  samples/leaf, L2=1, no early stopping. It captures nonlinear precursor/resource interactions
  that an additive logistic model cannot; no extra framework or parameter search is needed.

All randomness uses model seed 2026; thread pools are limited to one during fit/predict.
Boosting's internal random validation/early-stopping path is explicitly disabled, as documented
by [scikit-learn](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingClassifier.html).

Sigmoid mapping is logistic regression (C=1e6, max_iter=1000) on clipped raw probability log-odds
(epsilon 1e-8). It estimates just intercept and slope on calibration rows. At least 20 rows in
each class are required; the reference has 600 positives from 60 incidents and 9,468 negatives.
This is a pragmatic numerical minimum, not a statistical guarantee. A nonpositive slope fails
clearly rather than silently reversing ranking. Isotonic's greater flexibility is unnecessary
for this corpus. Sigmoid raw/calibrated evidence is reported for both learned families. Raw boosting
wins the reference decision; its calibrated version worsens both validation Brier and log loss.
No blanket claim that calibration helps is made.

## Row metrics

Primary ranking metric: **average precision**, the step-weighted PR-area summary, not trapezoidal
PR interpolation. Also precision, recall, TP/FP/FN/TN, ROC-AUC (secondary), Brier, binary log loss,
prevalence, rows and positives. Undefined precision/recall/ROC/AP use JSON null/CSV empty, not
fabricated zero. AP is undefined with no positives; ROC needs both classes. Reliability uses
10 equal-width bins including zero/one; saved counts distinguish sparse bins. No accuracy headline.

## Alerts, incident matching and threshold rule

Alert if `probability >= threshold`. Within each run/service, consecutive eligible alerted
minutes form one episode. Below-threshold minutes, missing eligible timestamps or run boundaries
break episodes. No refractory period, cooldown or active-incident suppression is added.

An incident is **scorable** if any eligible timestamp lies in `[onset−10m,onset)`. It is detected
only if one of those timestamps alerts. Lead time is onset minus the earliest qualifying alerted
minute: `(0,10]` minutes. Episodes beginning earlier can qualify later through an in-window alerted
minute; their out-of-window start is never reported as warning time. Events near purges can have
partial opportunities and remain scorable, explicitly disclosed. Events with no opportunity are
excluded from detection denominators; onset counts remain separately available.

An episode matches if at least one of its alerted minutes predicts a scorable incident. One event
can match multiple separated episodes; each episode is counted once, and each event once. False
alert frequency = unmatched episodes / (eligible scored minutes / 1440). This is **eligible
service-day exposure**, not wall-clock calendar days. Alert precision = matched / all episodes.
Burden is all alerted minutes, including current-incident/recovery minutes.

Fixed grid: 0, 50 evenly spaced values 0.01…0.99, and 1.0. Select the highest detection rate
subject to at most **one false episode per eligible service-day**. Ties choose fewer alert minutes,
then the higher threshold. Fail if no threshold meets the budget. This is an exploratory operating
point, not a deployment recommendation or guaranteed future budget. Frozen thresholds and every
grid tradeoff are saved before test scoring.

**Known rule weakness:** always-on forecasts form long matched episodes and can satisfy the
false-episode budget while consuming every eligible minute. The reference prevalence/logistic
operating points exhibit this degeneracy. Their recall/episode precision must be read together
with alert minutes and row precision, not as useful warning performance. The selected boosting
point has much lower burden. Do not repair the rule using these now-observed holdouts. A future
separately preregistered experiment should impose a hard burden constraint and use fresh holdouts.

## Uncertainty and limitations

Seeded 200-replicate percentile bootstrap of **whole simulation runs**, retaining all services and
minutes together, for selected-model AP and incident detection. No minute-row bootstrap. With
three development runs and two runs per holdout, intervals are coarse/descriptive; with fewer
than two runs (CI fixture) intervals are omitted. Shared equations remain outside this uncertainty.
Coefficients are standardised logistic associations with correlated predictors, not causal
importance and not an explanation of the selected boosted model.

## Artefacts and reproducibility

`reliability batch-b` generates missing corpus bundles or verifies/reuses matching bundles, then
atomically publishes a fresh immutable experiment directory. Existing/incompatible outputs fail.
Outputs include config, feature schema, environment/source hashes, dataset manifests, exact split
assignments, models, calibration objects, selection, keyed predictions, metrics, incident/episode
results, threshold grid and generated Markdown. `batch-b-evidence` verifies experiment hashes and
atomically publishes compact CSV/JSON/report/figures with its own manifest. Output reports refer to
the figures in compact evidence; large row predictions and joblib files stay Git-ignored.

`load_model` validates schema/order/dtype, exact scikit-learn version and hash before loading a
trusted-local joblib artefact. Joblib is executable Python data: do not load untrusted files.
Sidecars/hashes detect corruption, not authenticity. Cross-platform binary identity is not promised.
No API, model registry, database, Docker, remote publishing or Batch C functionality is included.

## Batch D extensions

The Batch B selection, thresholds and heldouts remain frozen. Operational delayed evaluation is
specified in [MONITORING.md](MONITORING.md): full matured horizons, separately certified complete
outcomes available by evaluation cutoff, null for undefined metrics and the unchanged threshold.
The independent SMD study in [EXTERNAL_VALIDATION.md](EXTERNAL_VALIDATION.md) uses ordinal steps and
anonymous features. It is neither the production task nor direct model transfer; its results are
not comparable to Batch B scores as measurements of the same task.
