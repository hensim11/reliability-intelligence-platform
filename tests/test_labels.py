import pandas as pd
import pytest

from reliability_intelligence.labels import future_labels


def test_precise_boundaries_and_service_isolation():
    origin = pd.Timestamp("2026-01-01T00:00:00Z")
    minutes = [0, 9, 10, 19, 20, 21, 29, 30, 39]
    telemetry = pd.DataFrame(
        {
            "timestamp": [origin + pd.Timedelta(minutes=m) for m in minutes] * 2,
            "service_id": ["a"] * len(minutes) + ["b"] * len(minutes),
        }
    )
    incidents = pd.DataFrame(
        {"service_id": ["a"], "incident_start": [origin + pd.Timedelta(minutes=20)]}
    )
    labels = future_labels(
        telemetry, incidents, coverage_start=origin, coverage_end=origin + pd.Timedelta(minutes=40)
    )
    assert labels.incident_within_horizon.iloc[:7].tolist() == [0, 0, 1, 1, 0, 0, 0]
    assert labels.incident_within_horizon.iloc[7:9].isna().all()
    assert labels.incident_within_horizon.iloc[9:16].eq(0).all()
    assert labels.history_complete.iloc[:5].tolist() == [False, False, False, True, True]


def test_non_grid_onset_and_multiple_incidents():
    start = pd.Timestamp("2026-01-01T00:00Z")
    telemetry = pd.DataFrame(
        {"timestamp": [start, start + pd.Timedelta(seconds=30)], "service_id": ["a", "a"]}
    )
    incidents = pd.DataFrame(
        {
            "service_id": ["a", "a"],
            "incident_start": [
                start + pd.Timedelta(minutes=10, seconds=15),
                start + pd.Timedelta(minutes=10, seconds=20),
            ],
        }
    )
    labels = future_labels(
        telemetry, incidents, coverage_start=start, coverage_end=start + pd.Timedelta(hours=1)
    )
    assert labels.incident_within_horizon.tolist() == [0, 1]


def test_all_censored_short_run(config):
    from dataclasses import replace

    from reliability_intelligence.simulation.engine import simulate

    result = simulate(replace(config, duration_minutes=5))
    assert result.labels.incident_within_horizon.isna().all()
    assert not result.labels.history_complete.any()


def test_bad_coverage():
    start = pd.Timestamp("2026-01-01T00:00Z")
    with pytest.raises(ValueError):
        future_labels(pd.DataFrame(), pd.DataFrame(), coverage_start=start, coverage_end=start)
