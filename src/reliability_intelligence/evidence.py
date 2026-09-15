"""Data-derived, noninteractive evidence; no model fitting or feature engineering."""

import json
import os
import tempfile
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "reliability-matplotlib"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from reliability_intelligence.config import INCIDENT_TYPES  # noqa: E402
from reliability_intelligence.storage import read_dataset  # noqa: E402

METRICS = [
    ("request_rate_rps", "Requests / second"),
    ("latency_p95_ms", "p95 latency (ms)"),
    ("error_rate", "Error fraction"),
    ("cpu_utilisation_pct", "CPU (%)"),
    ("memory_utilisation_pct", "Memory (%)"),
    ("dependency_latency_ms", "Dependency latency (ms)"),
]


def timeline(rows: pd.DataFrame, path: Path, title: str, event: pd.Series | None = None) -> None:
    figure, axes = plt.subplots(3, 2, figsize=(12, 8), sharex=True, layout="constrained")
    reference = rows.timestamp.iloc[0] if event is None else event.incident_start
    x = (rows.timestamp - reference).dt.total_seconds() / 60
    for axis, (metric, label) in zip(axes.flat, METRICS, strict=True):
        axis.plot(x, rows[metric], color="#176e9c", linewidth=1.5)
        axis.set_ylabel(label)
        axis.grid(alpha=0.2)
        if event is not None:
            for start, end, color, phase in (
                (event.precursor_start, event.incident_start, "#ebba52", "Precursor"),
                (event.incident_start, event.incident_end, "#e67373", "Active"),
                (event.incident_end, event.recovery_end, "#65bc93", "Recovery"),
            ):
                axis.axvspan(
                    (start - reference).total_seconds() / 60,
                    (end - reference).total_seconds() / 60,
                    color=color,
                    alpha=0.22,
                    label=phase,
                )
            axis.axvline(0, color="#992727", linestyle="--", linewidth=1)
    axes[0, 0].legend(loc="upper left", fontsize=8) if event is not None else None
    for axis in axes[-1]:
        axis.set_xlabel("Minutes from incident onset" if event is not None else "Elapsed minutes")
    figure.suptitle(title + " · synthetic telemetry", fontsize=14)
    figure.savefig(path, dpi=150)
    plt.close(figure)


def generate_evidence(dataset: Path, output: Path) -> dict:
    result, manifest = read_dataset(dataset)
    if output.exists():
        raise FileExistsError(f"Evidence output exists: {output}; choose a new directory")
    output.mkdir(parents=True)
    telemetry, incidents, labels = result.telemetry, result.incidents, result.labels
    observed = labels.incident_within_horizon.dropna()
    eligible = labels.loc[labels.history_complete & labels.horizon_complete]
    durations = (incidents.incident_end - incidents.incident_start).dt.total_seconds() / 60
    summary = {
        "synthetic": True,
        "source_manifest": manifest,
        "telemetry_rows": len(telemetry),
        "services": sorted(telemetry.service_id.unique().tolist()),
        "incidents": len(incidents),
        "incident_counts_by_type": incidents.incident_type.value_counts().sort_index().to_dict(),
        "incident_counts_by_service": incidents.service_id.value_counts().sort_index().to_dict(),
        "active_duration_minutes": {
            "min": float(durations.min()) if len(durations) else None,
            "mean": float(durations.mean()) if len(durations) else None,
            "max": float(durations.max()) if len(durations) else None,
        },
        "labels": {
            "positive": int(observed.sum()),
            "negative": int((observed == 0).sum()),
            "unknown": int(labels.incident_within_horizon.isna().sum()),
            "positive_fraction_observed": float(observed.mean()) if len(observed) else None,
            "history_incomplete": int((~labels.history_complete).sum()),
            "eligible_rows": len(eligible),
            "positive_fraction_eligible": float(eligible.incident_within_horizon.mean())
            if len(eligible)
            else None,
        },
    }
    metrics = [name for name, _ in METRICS]
    telemetry.groupby("service_id")[metrics].describe().to_csv(
        output / "descriptive_statistics.csv"
    )
    correlations = telemetry[metrics].corr()
    correlations.to_csv(output / "metric_correlations.csv")
    incidents.to_csv(output / "incident_catalog.csv", index=False)
    summary["examples"] = {}
    # Use the first service's actual uninterrupted pre-incident segment, capped at two hours.
    service = str(telemetry.service_id.iloc[0])
    normal = telemetry.loc[telemetry.service_id == service]
    normal_end = normal.timestamp.iloc[0] + pd.Timedelta(minutes=120)
    service_events = incidents.loc[incidents.service_id == service]
    if len(service_events):
        normal_end = min(normal_end, service_events.precursor_start.min())
    normal = normal.loc[normal.timestamp < normal_end]
    if len(normal):
        timeline(normal, output / "normal.png", f"Normal operation: {service}")
        summary["examples"]["normal"] = {"service_id": service, "rows": len(normal)}
    phase_records = []
    for kind in INCIDENT_TYPES:
        matches = incidents.loc[incidents.incident_type == kind]
        if matches.empty:
            continue
        event = matches.sort_values("incident_start").iloc[0]
        rows = telemetry.loc[
            (telemetry.service_id == event.service_id)
            & (telemetry.timestamp >= event.precursor_start - pd.Timedelta(minutes=20))
            & (telemetry.timestamp <= event.recovery_end + pd.Timedelta(minutes=20))
        ]
        timeline(
            rows,
            output / f"{kind}.png",
            f"{kind.replace('_', ' ').title()}: {event.service_id}",
            event,
        )
        summary["examples"][kind] = str(event.incident_id)
        for phase, begin, end in (
            ("baseline", event.precursor_start - pd.Timedelta(minutes=20), event.precursor_start),
            ("precursor", event.precursor_start, event.incident_start),
            ("active", event.incident_start, event.incident_end),
            ("recovery", event.incident_end, event.recovery_end),
            ("post_recovery", event.recovery_end, event.recovery_end + pd.Timedelta(minutes=20)),
        ):
            phase_rows = rows.loc[(rows.timestamp >= begin) & (rows.timestamp < end)]
            if len(phase_rows):
                phase_records.append(
                    {
                        "incident_id": event.incident_id,
                        "incident_type": kind,
                        "phase": phase,
                        "rows": len(phase_rows),
                        **phase_rows[metrics].mean().to_dict(),
                    }
                )
    pd.DataFrame(phase_records).to_csv(output / "example_phase_means.csv", index=False)
    figure, axes = plt.subplots(2, 2, figsize=(12, 9), layout="constrained")
    counts = incidents.incident_type.value_counts().reindex(INCIDENT_TYPES, fill_value=0)
    axes[0, 0].barh(counts.index, counts.values, color="#176e9c")
    axes[0, 0].set_title("Incident counts")
    axes[0, 1].bar(
        ["Negative", "Positive", "Unknown"],
        [summary["labels"][k] for k in ("negative", "positive", "unknown")],
    )
    axes[0, 1].set_title("Future-start labels (all timestamps)")
    for name, group in telemetry.groupby("service_id"):
        axes[1, 0].hist(group.latency_p95_ms, bins=40, alpha=0.4, label=name)
    axes[1, 0].set(xlabel="p95 latency (ms)", ylabel="Rows", title="Latency distributions")
    axes[1, 0].legend(fontsize=8)
    axes[1, 1].scatter(
        telemetry.request_rate_rps, telemetry.cpu_utilisation_pct, s=3, alpha=0.15, rasterized=True
    )
    axes[1, 1].set(xlabel="Requests / second", ylabel="CPU (%)", title="Traffic / CPU relationship")
    figure.suptitle("Batch A dataset overview · synthetic telemetry")
    figure.savefig(output / "overview.png", dpi=150)
    plt.close(figure)
    figure, axis = plt.subplots(figsize=(9, 7), layout="constrained")
    axis.imshow(correlations, vmin=-1, vmax=1, cmap="RdBu_r")
    axis.set_xticks(range(len(metrics)), [label for _, label in METRICS], rotation=45, ha="right")
    axis.set_yticks(range(len(metrics)), [label for _, label in METRICS])
    for (row, col), value in np.ndenumerate(correlations.to_numpy()):
        axis.text(col, row, f"{value:.2f}", ha="center", va="center", fontsize=9)
    axis.set_title("Pooled Pearson correlations · descriptive, not causal evidence")
    figure.savefig(output / "correlations.png", dpi=150)
    plt.close(figure)
    (output / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    balance = summary["labels"]
    (output / "REPORT.md").write_text(
        "# Batch A simulation evidence\n\n"
        "Generated from verified Parquet inputs. All data is synthetic.\n\n"
        f"- Telemetry rows: {len(telemetry):,}; services: {len(summary['services'])}.\n"
        f"- Incidents: {len(incidents)}; counts: {summary['incident_counts_by_type']}.\n"
        f"- Active duration (minutes): {summary['active_duration_minutes']}.\n"
        f"- Future labels: {balance['positive']} positive, {balance['negative']} negative, "
        f"{balance['unknown']} unknown.\n"
        f"- Positive fraction among observed labels: {balance['positive_fraction_observed']}.\n"
        f"- Complete history and horizon: {balance['eligible_rows']} rows.\n\n"
        "## Review the data\n\n"
        "![Overview](overview.png)\n\n"
        + ("![Normal](normal.png)\n\n" if len(normal) else "No initial normal segment.\n\n")
        + "\n\n".join(
            f"![{kind}]({kind}.png)" for kind in INCIDENT_TYPES if kind in summary["examples"]
        )
        + "\n\n![Correlations](correlations.png)\n\n"
        "## Interpretation and limits\n\n"
        "Each scenario plot uses the earliest onset of that type, with 20-minute context. "
        "Shading is ground truth used only for review. Precursor and recovery slopes are "
        "visible before and after the active phase; exact phase means are in "
        "`example_phase_means.csv`. `incident_catalog.csv` contains every incident, "
        "and `descriptive_statistics.csv` includes per-service distributions.\n\n"
        "The schedule deliberately covers scenarios; label prevalence is designed, not an "
        "estimate of production outages. Pooled correlations mix services and regimes. "
        "These plots demonstrate simulator mechanics, not real-world predictability. "
        "Onset marks an injected fault-pressure boundary, not a measured SLO violation. "
        "No model or forecasting performance is claimed. Source configuration, versions "
        "and hashes are recorded in `summary.json`.\n"
    )
    return summary
