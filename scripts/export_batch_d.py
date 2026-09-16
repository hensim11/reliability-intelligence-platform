"""Publish compact, data-derived external-study evidence atomically."""

import argparse
import io
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from reliability_intelligence.monitoring.reference import publish, verify
from reliability_intelligence.storage import file_hash


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--study", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    manifest = json.loads((args.study / "manifest.json").read_text())
    verify(manifest)
    for name, expected in manifest["files"].items():
        if file_hash(args.study / name) != expected:
            raise ValueError("Study integrity failure")
    results = json.loads((args.study / "results.json").read_text())
    rows = pd.DataFrame(results["per_machine"])
    final = rows.loc[(rows.partition == "evaluation") & (rows.family == "logistic")].set_index(
        "machine"
    )
    fig, axes = plt.subplots(1, 2, figsize=(12, 8), sharey=True, layout="constrained")
    final = final.sort_index()
    for axis, key, label in zip(
        axes,
        ("start_detection_rate", "alert_row_fraction"),
        ("Episode-start detection fraction", "Alert-row fraction"),
        strict=True,
    ):
        axis.barh(final.index, final[key].fillna(0), color="#317873")
        for i, value in enumerate(final[key]):
            if pd.isna(value):
                axis.text(0.01, i, "unavailable", va="center", fontsize=7)
        axis.set_xlabel(label)
        axis.set_xlim(0, max(0.05, float(final[key].max()) * 1.1))
    fig.suptitle(
        "SMD ordinal forecasting: fixed logistic baseline, final region\n"
        "Unavailable includes no training positives or no scorable final starts"
    )
    buffer = io.BytesIO()
    fig.savefig(
        buffer, format="png", dpi=130, metadata={"Software": "reliability-intelligence Batch D"}
    )
    plt.close(fig)
    pooled = pd.DataFrame(results["pooled"])
    unavailable = final.loc[final.unavailable.notna()].index.tolist()
    no_starts = rows.loc[
        (rows.partition == "evaluation")
        & (rows.family == "prevalence")
        & (rows.scorable_starts == 0),
        "machine",
    ].tolist()
    report = """# SMD external forecasting study

This is a separate ordinal forecasting study, not validation of the production model or real
ten-minute incident warning. Machines are entity proxies, anomalies are not service incidents,
and the 38 anonymous normalized dimensions have no mapping to the seven production metrics.
Cadence is insufficiently documented; every horizon and lead is in samples/steps.

All 28 machines are included. The provider's labelled **test** sequences are repurposed into
chronological 50% development-training, 20% selection-validation and 30% final regions. Official
train files are validated and hashed but not fitted here: they lack the labels needed for this
supervised task. Full observation/target windows are purged at every boundary. Features are only
current values and preceding-15-step means. Consecutive positive labels collapse to episodes;
targets indicate starts in `(t,t+10 steps]`; final ten rows are censored. Point and
interpretation labels are never features, and machine IDs only group separate models.

Protocol fixed before final scoring: per-machine training-fitted standardization and L2 logistic
C=1, maximum 2000 iterations, seed 2026; training prevalence comparator; threshold 0.5 for both.
No family, threshold or hyperparameter selection. Validation is diagnostic. Six one-class
training regions cannot fit logistic; their results are unavailable, not excluded from the
dataset. Pooled logistic and prevalence denominators therefore differ and are displayed
explicitly.

## Final results

| Family | Machines | Rows | Positives | AP | Brier | Detected/scorable | False episodes | Alerts |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
"""
    for row in results["pooled"]:
        if row["partition"] == "evaluation":
            values = [
                row[k]
                for k in ("family", "machines", "rows", "positives", "average_precision", "brier")
            ]
            values += [
                f"{row['detected_starts']}/{row['scorable_starts']}",
                row["false_alert_episodes"],
                row["alert_rows"],
            ]
            report += "| " + " | ".join(str(v) for v in values) + " |\n"
    report += (
        "\nLogistic unavailable (no training positive starts): "
        + ", ".join(unavailable)
        + ".\n\nFinal regions with no scorable starts: "
        + ", ".join(no_starts)
        + ".\n"
        "AP, recall and detection use null where undefined. Full per-machine metrics, class "
        "balance, lead steps and validation results are in `per_machine.csv` and `results.json`.\n"
        "\n![Per-machine detection and burden](external_results.png)\n\n"
        "The weak final results expose domain and temporal mismatch. Sparse episode starts "
        "differ from point-anomaly prevalence; long anomalies contribute only one start. "
        "The fixed threshold misses nearly all starts, while logistic false alerts persist. "
        "This supports reproducibility of the forecasting/evaluation method and exposes its "
        "limitations; it supports neither useful real-world warning nor transfer of the frozen "
        "synthetic model. SMD scores must not be numerically compared with Batch B scores as "
        "the same task. No production model was loaded or modified in this study.\n\n"
        "Source pin, dataset-specific MIT licence hash and all 84 consumed file hashes/shapes "
        "are in `source.json`; fixed protocol in `protocol.json`. Regeneration is deterministic "
        "in the recorded numerical environment; download timestamp and environment source "
        "paths are provenance fields.\n"
    )
    files = {name: (args.study / name).read_bytes() for name in manifest["files"]}
    files.update(
        {
            "REPORT.md": report,
            "per_machine.csv": rows.drop(columns="lead_steps").to_csv(index=False),
            "pooled.csv": pooled.to_csv(index=False),
            "external_results.png": buffer.getvalue(),
        }
    )
    publish(args.output, files)


if __name__ == "__main__":
    main()
