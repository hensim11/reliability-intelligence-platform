"""Compact evidence generated exclusively from immutable experiment outputs."""

import json
import shutil
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import precision_recall_curve

from reliability_intelligence.evidence import plt
from reliability_intelligence.experiment import publish_manifest, verify_experiment, write_json

COMPACT_FILES = (
    "config.json",
    "feature_schema.json",
    "environment.json",
    "corpus.csv",
    "boundaries.csv",
    "event_counts.csv",
    "corpus_manifests.json",
    "splits.csv",
    "validation_candidates.csv",
    "thresholds.csv",
    "selection.json",
    "metrics.csv",
    "service_metrics.csv",
    "calibration.csv",
    "incident_results.csv",
    "uncertainty.json",
    "coefficients.csv",
    "summary.json",
)


def markdown_table(frame):
    def cell(value):
        return "undefined" if pd.isna(value) else str(value)

    return (
        "| "
        + " | ".join(frame.columns)
        + " |\n| "
        + " | ".join(["---"] * len(frame.columns))
        + " |\n"
        + "\n".join(
            "| " + " | ".join(cell(v) for v in row) + " |"
            for row in frame.itertuples(index=False, name=None)
        )
        + "\n"
    )


def report_text(source):
    summary = json.loads((source / "summary.json").read_text())
    selected = summary["selection"]["candidate"]
    metrics = pd.read_csv(source / "metrics.csv")
    selection = summary["selection"]
    return (
        "# Batch B — synthetic ML and evaluation evidence\n\n"
        "Generated from saved outputs; no metrics are manually transcribed. This "
        "measures controlled synthetic feasibility, not production forecasting "
        "validity.\n\n"
        "## Corpus and protocol\n\n"
        f"{summary['telemetry_rows']} telemetry rows; {summary['corpus_incidents']} "
        "incidents. Each run spans four days in the reference configuration.\n\n"
        + markdown_table(pd.read_csv(source / "corpus.csv"))
        + "\nDevelopment runs use chronological train / calibration / validation / "
        "temporal-test intervals. Exact boundaries and eligible row/positive counts "
        "are in boundaries.csv and splits.csv. First 15 minutes and final 10 minutes "
        "are purged per interval. Held-out seeds and renewal-like schedule regimes "
        "use full-run eligible coverage. All seven telemetry metrics have "
        "current/mean/population-std/min/max/change/slope features; no identity or "
        "clock predictors.\n\n"
        "Onset counts by partition, service and type are in event_counts.csv; "
        "scorable event denominators below exclude events without any eligible "
        "pre-onset forecast minute. Partial forecast opportunities near purges remain "
        "scorable.\n\n"
        "## Validation evidence and frozen choice\n\n"
        + markdown_table(
            pd.read_csv(source / "validation_candidates.csv")[
                ["candidate", "average_precision", "brier", "log_loss"]
            ]
        )
        + f"\nSelected **{selected}**, threshold **{selection['threshold']}**. Family: "
        f"{selection['family_rule']}. Calibration: {selection['calibration_rule']}. "
        f"Operating point: {selection['threshold_rule']}; budget "
        f"{selection['false_alert_budget']} false episodes per eligible service-day. "
        "Every candidate's threshold is frozen in selection.json before test scoring. "
        "No hyperparameter search; boosting early stopping is disabled.\n\n"
        "## Frozen selected result\n\n"
        + markdown_table(
            metrics.loc[
                metrics.candidate == selected,
                [
                    "partition",
                    "rows",
                    "positives",
                    "prevalence",
                    "average_precision",
                    "roc_auc",
                    "brier",
                    "log_loss",
                    "precision",
                    "recall",
                ],
            ]
        )
        + "\n## Incident detection and operational burden\n\n"
        + markdown_table(
            metrics.loc[
                metrics.candidate == selected,
                [
                    "partition",
                    "scorable_incidents",
                    "detected_incidents",
                    "missed_incidents",
                    "mean_lead_minutes",
                    "false_alerts_per_service_day",
                    "alert_precision",
                    "episodes",
                    "alert_minutes",
                    "eligible_service_days",
                ],
            ]
        )
        + "\nAn episode groups consecutive above-threshold eligible service minutes "
        "within one run. It matches if any alerted minute precedes an onset by (0,10] "
        "minutes. Lead time uses the earliest qualifying minute, not an earlier "
        "out-of-window episode start. False episodes have no match. Alert minutes "
        "include active/recovery periods; no truth-based suppression occurs. Exposure "
        "is eligible minutes / 1440.\n\n"
        "The false-episode budget alone can admit always-on forecasts: their long episodes "
        "match events while consuming all eligible minutes. The baseline/logistic selected "
        "points exhibit this weakness; read their recall alongside burden and row precision. "
        "This rule was not revised after viewing holdouts. A future protocol needs a hard "
        "burden constraint and fresh holdouts.\n\n"
        "## All candidates, including untouched evaluations\n\n"
        + markdown_table(
            metrics[
                [
                    "partition",
                    "candidate",
                    "threshold",
                    "average_precision",
                    "brier",
                    "log_loss",
                    "incident_detection_rate",
                    "false_alerts_per_service_day",
                ]
            ]
        )
        + "\n## Uncertainty and service diagnostics\n\n"
        "uncertainty.json contains seeded 200-resample percentile intervals using "
        "whole independent simulation runs. Two held-out runs and three development "
        "runs make these intervals coarse and unstable; they do not quantify "
        "real-world uncertainty. Per-service results are in service_metrics.csv. "
        "Identity is excluded, but metric baselines can still proxy service. The "
        "holdout changes schedules within the same four profiles and does not "
        "establish generalisation to unseen services.\n\n"
        "## Figures\n\n"
        "![Precision-recall](precision_recall.png)\n\n![Calibration](calibration.png)\n\n"
        "![Validation tradeoffs](thresholds.png)\n\n![Operational results](operations.png)\n\n"
        "![Logistic coefficients](coefficients.png)\n\n"
        "Average precision is the primary step-weighted PR-area summary (not "
        "trapezoidal interpolation). Reliability points show occupied equal-width "
        "probability bins; bin counts are in calibration.csv. Coefficients describe "
        "the training-fitted standardised logistic model, even if another model is "
        "selected. Correlated features make them unstable associations, not causal "
        "importance.\n\n"
        "## Reproduction and limitations\n\n"
        "Run `reliability batch-b --config configs/batch_b.json --corpus data/batch_b "
        "--output data/batch_b_experiment --evidence evidence/batch_b/generated` from "
        "the repository root after installing requirements-lock.txt. Use new "
        "output/evidence paths for repeat runs; existing corpus bundles are strictly "
        "verified and reused. `reliability batch-b-evidence --experiment "
        "data/batch_b_experiment --output evidence/batch_b/repeated` regenerates "
        "compact evidence without fitting.\n\n"
        "Source hashes, dependency versions, seeds and immutable source manifests "
        "accompany this report. Raw tables, assignments, fitted trusted-local joblib "
        "models and all candidate row predictions remain in the ignored experiment "
        "directory.\n\n"
        "The reference corpus provides hundreds of controlled events across seeds for "
        "a small fixed candidate comparison, but events share simulator equations, "
        "smooth precursors, profiles and noise assumptions. It lacks abrupt "
        "unforeseeable faults, benign precursor lookalikes, missing/late data, unseen "
        "services and external telemetry. Schedule holdout shifts arrival spacing, "
        "type frequencies, durations and severity together; it cannot attribute "
        "degradation to one factor. No simulator equations were tuned. Results must "
        "not be described as production readiness or real-world forecasting. Remote "
        "CI is not claimed. API, persistence and online serving remain deferred to "
        "Batch C.\n"
    )


def generate_ml_evidence(experiment: Path, output: Path):
    manifest = verify_experiment(experiment)
    if output.exists():
        raise FileExistsError(f"Evidence output exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        for name in COMPACT_FILES:
            shutil.copyfile(experiment / name, staging / name)
        write_json(staging / "experiment_manifest.json", manifest)
        _figures(experiment, staging)
        (staging / "REPORT.md").write_text(report_text(experiment))
        publish_manifest(staging)
        if output.exists():
            raise FileExistsError(f"Output appeared: {output}")
        staging.rename(output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return json.loads((output / "summary.json").read_text())


def _figures(source, output):
    predictions = pd.read_parquet(source / "predictions.parquet")
    metrics = pd.read_csv(source / "metrics.csv")
    selection = json.loads((source / "selection.json").read_text())
    selected = selection["candidate"]
    partitions = ["validation", "temporal_test", "heldout_seed", "heldout_regime"]
    fig, axes = plt.subplots(2, 2, figsize=(12, 9), layout="constrained")
    for ax, partition in zip(axes.flat, partitions, strict=True):
        for name, group in predictions.loc[predictions.partition == partition].groupby("candidate"):
            precision, recall, _ = precision_recall_curve(
                group.incident_within_horizon.astype(int), group.probability
            )
            ax.step(recall, precision, where="post", label=name, alpha=0.85)
        ax.set(title=partition, xlabel="Recall", ylabel="Precision", xlim=(0, 1), ylim=(0, 1.02))
        ax.grid(alpha=0.2)
        ax.legend(fontsize=7)
    fig.suptitle("Precision–recall · controlled synthetic evaluation")
    fig.savefig(output / "precision_recall.png", dpi=150)
    plt.close(fig)
    calibration = pd.read_csv(source / "calibration.csv")
    fig, axes = plt.subplots(2, 2, figsize=(12, 9), layout="constrained")
    for ax, partition in zip(axes.flat, partitions, strict=True):
        for name, group in calibration.loc[calibration.partition == partition].groupby("candidate"):
            group = group.loc[group.rows > 0]
            ax.plot(group.mean_probability, group.observed_fraction, ".-", label=name, alpha=0.8)
        ax.plot([0, 1], [0, 1], "k--", alpha=0.5)
        ax.set(
            title=partition,
            xlabel="Mean predicted probability",
            ylabel="Observed positive fraction",
            xlim=(0, 1),
            ylim=(0, 1),
        )
        ax.legend(fontsize=7)
        ax.grid(alpha=0.2)
    fig.set_layout_engine(None)
    fig.subplots_adjust(top=0.90, bottom=0.08, left=0.08, right=0.98, hspace=0.36, wspace=0.22)
    fig.suptitle("Reliability · occupied equal-width bins (counts in calibration.csv)")
    fig.savefig(output / "calibration.png", dpi=150)
    plt.close(fig)
    thresholds = pd.read_csv(source / "thresholds.csv")
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), layout="constrained")
    for name, group in thresholds.groupby("candidate"):
        axes[0].scatter(
            group.false_alerts_per_service_day,
            group.incident_detection_rate,
            label=name,
            s=14,
            alpha=0.7,
        )
        axes[1].plot(group.threshold, group.alert_minutes, label=name)
    axes[0].axvline(
        selection["false_alert_budget"], color="black", linestyle="--", label="False-alert budget"
    )
    axes[0].set(
        xlabel="False episodes / eligible service-day",
        ylabel="Incident detection rate",
        ylim=(0, 1.02),
        xlim=(0, None),
    )
    axes[1].set(xlabel="Probability threshold", ylabel="Alert minutes", xlim=(0, 1), ylim=(0, None))
    axes[0].legend(fontsize=7)
    for ax in axes:
        ax.grid(alpha=0.2)
    fig.suptitle("Validation-only threshold tradeoffs · no truth-based suppression")
    fig.savefig(output / "thresholds.png", dpi=150)
    plt.close(fig)
    results = metrics.loc[metrics.candidate == selected].set_index("partition").loc[partitions]
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), layout="constrained")
    for ax, (column, label) in zip(
        axes.flat,
        [
            ("incident_detection_rate", "Incident detection fraction"),
            ("mean_lead_minutes", "Mean qualifying lead (minutes)"),
            ("false_alerts_per_service_day", "False episodes / eligible service-day"),
            ("alert_precision", "Matched episode fraction"),
        ],
        strict=True,
    ):
        ax.bar(np.arange(4), results[column], color="#176e9c")
        ax.set_xticks(np.arange(4), partitions, rotation=15, ha="right", fontsize=8)
        ax.set_ylabel(label)
        ax.set_ylim(0, 10 if column == "mean_lead_minutes" else 1 if "fraction" in label else None)
        ax.grid(axis="y", alpha=0.2)
    fig.suptitle(f"Frozen {selected} · threshold {selection['threshold']}")
    fig.savefig(output / "operations.png", dpi=150)
    plt.close(fig)
    coefficients = pd.read_csv(source / "coefficients.csv")
    coefficients = (
        coefficients.assign(magnitude=coefficients.standardised_logistic_coefficient.abs())
        .nlargest(15, "magnitude")
        .sort_values("standardised_logistic_coefficient")
    )
    fig, ax = plt.subplots(figsize=(11, 7), layout="constrained")
    ax.barh(coefficients.feature, coefficients.standardised_logistic_coefficient, color="#176e9c")
    ax.axvline(0, color="black", linewidth=0.8)
    ax.set(
        xlabel="Coefficient per training standard deviation",
        title="15 largest absolute logistic coefficients · correlated associations",
    )
    ax.tick_params(axis="y", labelsize=9)
    fig.savefig(output / "coefficients.png", dpi=150)
    plt.close(fig)
