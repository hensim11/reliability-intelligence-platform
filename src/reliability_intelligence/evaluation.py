"""Offline row and operational scoring; truth is consulted only after predictions."""

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score


def row_metrics(y, probability, threshold=0.5) -> dict:
    y, p = np.asarray(y), np.asarray(probability, dtype=float)
    if (
        len(y) != len(p)
        or not np.isin(y, [0, 1]).all()
        or not np.isfinite(p).all()
        or ((p < 0) | (p > 1)).any()
    ):
        raise ValueError("Invalid binary targets or probabilities")
    if not 0 <= threshold <= 1:
        raise ValueError("Threshold must lie in [0,1]")
    alert = p >= threshold
    tp, fp = int(((y == 1) & alert).sum()), int(((y == 0) & alert).sum())
    fn, tn = int(((y == 1) & ~alert).sum()), int(((y == 0) & ~alert).sum())
    return {
        "rows": len(y),
        "positives": int(y.sum()),
        "prevalence": float(y.mean()) if len(y) else None,
        "average_precision": float(average_precision_score(y, p)) if y.sum() else None,
        "roc_auc": float(roc_auc_score(y, p)) if len(np.unique(y)) == 2 else None,
        "brier": float(brier_score_loss(y, p)) if len(y) else None,
        "log_loss": float(log_loss(y, p, labels=[0, 1])) if len(y) else None,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
    }


def reliability_table(y, p) -> pd.DataFrame:
    frame = pd.DataFrame({"target": np.asarray(y, dtype=int), "probability": p})
    frame["bin"] = pd.cut(frame.probability, np.linspace(0, 1, 11), include_lowest=True)
    return (
        frame.groupby("bin", observed=False)
        .agg(
            rows=("target", "size"),
            positives=("target", "sum"),
            mean_probability=("probability", "mean"),
            observed_fraction=("target", "mean"),
        )
        .reset_index()
    )


def operational_metrics(predictions: pd.DataFrame, incidents: pd.DataFrame, threshold: float):
    """Episodes join adjacent eligible alerted minutes within run/service only.

    An episode succeeds if ANY of its alerted minutes predicts a scored onset in
    (t,t+10m]. Detection uses the earliest such minute, even in a longer episode.
    Events are scorable if at least one eligible forecast minute can predict them.
    Exposure is eligible scored minutes / 1440, not full calendar coverage.
    """
    if not 0 <= threshold <= 1:
        raise ValueError("Threshold must lie in [0,1]")
    if predictions.duplicated(["run_id", "service_id", "timestamp"]).any():
        raise ValueError("Duplicate prediction keys")
    episodes, events = [], []
    for (run, service), rows in predictions.groupby(["run_id", "service_id"], sort=True):
        rows = rows.sort_values("timestamp")
        times = pd.DatetimeIndex(rows.timestamp)
        active = rows.loc[rows.probability >= threshold, "timestamp"]
        groups = (active.diff() != pd.Timedelta(minutes=1)).cumsum()
        local = []
        for _, group in active.groupby(groups):
            local.append(
                {
                    "run_id": run,
                    "service_id": service,
                    "start": group.iloc[0],
                    "end": group.iloc[-1],
                    "alert_minutes": len(group),
                    "matched": False,
                }
            )
        truth = incidents.loc[(incidents.run_id == run) & (incidents.service_id == service)]
        for event in truth.itertuples():
            qualifying = times[
                (times < event.incident_start)
                & (times >= event.incident_start - pd.Timedelta(minutes=10))
            ]
            if not len(qualifying):
                continue
            hits = active.loc[
                (active < event.incident_start)
                & (active >= event.incident_start - pd.Timedelta(minutes=10))
            ]
            lead = (event.incident_start - hits.min()).total_seconds() / 60 if len(hits) else None
            events.append(
                {
                    "run_id": run,
                    "service_id": service,
                    "incident_id": event.incident_id,
                    "incident_type": event.incident_type,
                    "detected": bool(len(hits)),
                    "lead_minutes": lead,
                }
            )
            if len(hits):
                for episode in local:
                    if ((hits >= episode["start"]) & (hits <= episode["end"])).any():
                        episode["matched"] = True
        episodes.extend(local)
    episode_frame = pd.DataFrame(
        episodes, columns=["run_id", "service_id", "start", "end", "alert_minutes", "matched"]
    )
    event_frame = pd.DataFrame(
        events,
        columns=[
            "run_id",
            "service_id",
            "incident_id",
            "incident_type",
            "detected",
            "lead_minutes",
        ],
    )
    detected = sum(event["detected"] for event in events)
    matched = sum(episode["matched"] for episode in episodes)
    exposure = len(predictions) / 1440
    leads = [event["lead_minutes"] for event in events if event["detected"]]
    return (
        {
            "scorable_incidents": len(events),
            "detected_incidents": detected,
            "missed_incidents": len(events) - detected,
            "incident_detection_rate": detected / len(events) if events else None,
            "mean_lead_minutes": float(np.mean(leads)) if leads else None,
            "median_lead_minutes": float(np.median(leads)) if leads else None,
            "episodes": len(episodes),
            "false_episodes": len(episodes) - matched,
            "alert_precision": matched / len(episodes) if episodes else None,
            "eligible_service_days": exposure,
            "false_alerts_per_service_day": (len(episodes) - matched) / exposure
            if exposure
            else None,
            "alert_minutes": sum(episode["alert_minutes"] for episode in episodes),
        },
        event_frame,
        episode_frame,
    )


def select_threshold(table: pd.DataFrame, max_false_alerts: float) -> float:
    """Maximise detection within budget; tie-break on burden then higher threshold."""
    feasible = table.loc[table.false_alerts_per_service_day <= max_false_alerts]
    if feasible.empty:
        raise ValueError("No threshold meets the false-alert budget")
    return float(
        feasible.sort_values(
            ["incident_detection_rate", "alert_minutes", "threshold"],
            ascending=[False, True, False],
            na_position="last",
        )
        .iloc[0]
        .threshold
    )


def grouped_uncertainty(
    predictions: pd.DataFrame, events: pd.DataFrame, seed=2026, repeats=200
) -> dict:
    """Percentile bootstrap entire independent run trajectories, never minute rows."""
    groups = list(predictions.groupby("run_id", sort=True))
    if len(groups) < 2:
        return {"groups": len(groups), "intervals": None}
    rng = np.random.default_rng(seed)
    estimates = []
    for _ in range(repeats):
        sampled = rng.integers(len(groups), size=len(groups))
        rows = pd.concat([groups[i][1] for i in sampled])
        event_samples = [events.loc[(events.run_id == groups[i][0])] for i in sampled]
        sampled_events = pd.concat(event_samples)
        estimates.append(
            [
                average_precision_score(rows.incident_within_horizon.astype(int), rows.probability),
                sampled_events.detected.mean() if len(sampled_events) else np.nan,
            ]
        )
    return {
        "groups": len(groups),
        "repeats": repeats,
        "seed": seed,
        "unit": "whole simulation run (all services together)",
        "intervals": {
            name: np.nanquantile(np.array(estimates)[:, i], [0.025, 0.975]).tolist()
            for i, name in enumerate(["average_precision", "incident_detection_rate"])
        },
    }
