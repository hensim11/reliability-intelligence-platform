import numpy as np
import pandas as pd
import pytest

from reliability_intelligence.evaluation import (
    grouped_uncertainty,
    operational_metrics,
    reliability_table,
    row_metrics,
    select_threshold,
)


def fixture_predictions(minutes, probabilities, onset=20):
    start = pd.Timestamp("2026-01-01T00:00Z")
    rows = pd.DataFrame(
        {
            "run_id": "r",
            "service_id": "a",
            "timestamp": [start + pd.Timedelta(minutes=m) for m in minutes],
            "probability": probabilities,
        }
    )
    events = pd.DataFrame(
        {
            "run_id": ["r"],
            "service_id": ["a"],
            "incident_id": ["i"],
            "incident_type": ["cpu_saturation"],
            "incident_start": [start + pd.Timedelta(minutes=onset)],
        }
    )
    return rows, events


@pytest.mark.parametrize(
    "minute,detected,lead", [(9, 0, None), (10, 1, 10), (19, 1, 1), (20, 0, None), (21, 0, None)]
)
def test_detection_lead_boundaries(minute, detected, lead):
    minutes = sorted(set([minute, 15]))
    rows, events = fixture_predictions(minutes, [float(m == minute) for m in minutes])
    metrics, result, _ = operational_metrics(rows, events, 0.5)
    assert metrics["detected_incidents"] == detected
    assert metrics["missed_incidents"] == 1 - detected
    assert metrics["mean_lead_minutes"] == lead
    assert len(result) == 1


def test_long_episode_uses_first_qualifying_minute():
    rows, events = fixture_predictions(list(range(5, 22)), [1.0] * 17)
    metrics, _, episodes = operational_metrics(rows, events, 0.5)
    assert metrics["mean_lead_minutes"] == 10
    assert len(episodes) == 1
    assert metrics["alert_minutes"] == 17  # active minute is never suppressed
    assert metrics["alert_precision"] == 1


def test_episode_gaps_false_alert_frequency_and_service_run_isolation():
    rows, events = fixture_predictions([0, 1, 3, 10, 11, 12, 15], [1, 1, 1, 1, 0, 1, 0])
    extra = rows.assign(service_id="b")
    other = rows.assign(run_id="other")
    metrics, _, episodes = operational_metrics(pd.concat([rows, extra, other]), events, 0.5)
    assert len(episodes) == 12
    assert metrics["false_episodes"] == 10
    assert metrics["alert_minutes"] == 15
    assert metrics["alert_precision"] == 2 / 12
    assert metrics["false_alerts_per_service_day"] == 10 / (21 / 1440)


def test_unscorable_incident_not_in_denominator():
    rows, events = fixture_predictions([0, 1], [1, 0])
    metrics, result, _ = operational_metrics(rows, events, 0.5)
    assert metrics["scorable_incidents"] == 0
    assert metrics["incident_detection_rate"] is None
    assert result.empty


def test_metric_edges_and_calibration_counts():
    assert row_metrics([], [])["average_precision"] is None
    zero = row_metrics([0, 0], [0.1, 0.2])
    assert zero["roc_auc"] is None
    assert zero["precision"] is None
    assert zero["brier"] == pytest.approx(0.025)
    positive = row_metrics([1, 1], [0.8, 0.9])
    assert positive["average_precision"] == 1
    assert positive["roc_auc"] is None
    table = reliability_table([0, 1, 1], [0, 0.5, 1])
    assert table.rows.sum() == 3
    assert table.positives.sum() == 2


@pytest.mark.parametrize("y,p", [([2], [0.5]), ([0], [np.nan]), ([0], [1.1]), ([1, 0], [0.2])])
def test_bad_metric_input(y, p):
    with pytest.raises(ValueError):
        row_metrics(y, p)


def test_threshold_selection_budget_and_ties():
    table = pd.DataFrame(
        {
            "threshold": [0.1, 0.2, 0.3, 0.4],
            "false_alerts_per_service_day": [2, 1, 0.5, 0.1],
            "incident_detection_rate": [1, 0.8, 0.8, 0.5],
            "alert_minutes": [100, 80, 60, 10],
        }
    )
    assert select_threshold(table, 1) == 0.3
    with pytest.raises(ValueError, match="No threshold"):
        select_threshold(table, 0)


def test_whole_run_bootstrap_determinism():
    rows, events = fixture_predictions([10, 11, 12], [0.8, 0.9, 0.1])
    rows["incident_within_horizon"] = [1, 1, 0]
    rows = pd.concat([rows, rows.assign(run_id="second")])
    events = pd.DataFrame({"run_id": ["r", "second"], "detected": [True, False]})
    a = grouped_uncertainty(rows, events, repeats=20)
    assert a == grouped_uncertainty(rows, events, repeats=20)
    assert a["groups"] == 2


def test_fractional_onset_window():
    rows, events = fixture_predictions([10, 11, 20, 21], [1, 0, 0, 0], onset=20.5)
    metrics, _, _ = operational_metrics(rows, events, 0.5)
    assert metrics["detected_incidents"] == 0
    rows["probability"] = [0, 1, 0, 0]
    metrics, _, _ = operational_metrics(rows, events, 0.5)
    assert metrics["mean_lead_minutes"] == 9.5
    with pytest.raises(ValueError):
        row_metrics([0.5], [0.1])
