import pandas as pd
import pytest

from reliability_intelligence.labels import future_labels, history_grid_complete


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
        telemetry,
        incidents,
        coverage_start=origin,
        coverage_end=origin + pd.Timedelta(minutes=40),
        interval_seconds=60,
    )
    assert labels.incident_within_horizon.iloc[:7].tolist() == [0, 0, 1, 1, 0, 0, 0]
    assert labels.incident_within_horizon.iloc[7:9].isna().all()
    assert labels.incident_within_horizon.iloc[9:16].eq(0).all()
    assert not labels.history_complete.any()


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
        telemetry,
        incidents,
        coverage_start=start,
        coverage_end=start + pd.Timedelta(hours=1),
        interval_seconds=60,
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
        future_labels(
            pd.DataFrame(),
            pd.DataFrame(),
            coverage_start=start,
            coverage_end=start,
            interval_seconds=60,
        )


def grid(start, *, interval_seconds=60, periods=16, service="a"):
    return pd.DataFrame(
        {
            "timestamp": pd.date_range(
                start, periods=periods, freq=pd.Timedelta(seconds=interval_seconds)
            ),
            "service_id": service,
        }
    )


def completeness(telemetry, prediction_keys, start, interval_seconds=60):
    return history_grid_complete(
        telemetry,
        prediction_keys,
        coverage_start=start,
        observation_minutes=15,
        interval_seconds=interval_seconds,
    )


def test_complete_history_requires_every_expected_grid_timestamp():
    start = pd.Timestamp("2026-01-01T00:00Z")
    telemetry = grid(start)
    assert completeness(telemetry, telemetry.iloc[[-1]], start).item()


@pytest.mark.parametrize("missing_index", [1, 7])
def test_history_rejects_oldest_or_internal_missing_observation(missing_index):
    start = pd.Timestamp("2026-01-01T00:00Z")
    complete = grid(start)
    telemetry = complete.drop(index=missing_index)
    assert not completeness(telemetry, complete.iloc[[-1]], start).item()


def test_history_requires_current_prediction_timestamp():
    start = pd.Timestamp("2026-01-01T00:00Z")
    complete = grid(start)
    assert not completeness(complete.iloc[:-1], complete.iloc[[-1]], start).item()


def test_row_count_cannot_hide_wrong_timestamp():
    start = pd.Timestamp("2026-01-01T00:00Z")
    complete = grid(start)
    telemetry = complete.drop(index=7).copy()
    replacement = telemetry.iloc[[0]].copy()
    replacement["timestamp"] = start + pd.Timedelta(minutes=7, seconds=30)
    telemetry = pd.concat([telemetry, replacement], ignore_index=True)
    assert len(telemetry) == len(complete)
    assert not completeness(telemetry, complete.iloc[[-1]], start).item()


def test_other_service_cannot_fill_missing_history():
    start = pd.Timestamp("2026-01-01T00:00Z")
    complete = grid(start)
    service_a = complete.drop(index=7)
    service_b = complete.iloc[[7]].assign(service_id="b")
    telemetry = pd.concat([service_a, service_b], ignore_index=True)
    assert not completeness(telemetry, complete.iloc[[-1]], start).item()


def test_history_uses_configured_subminute_interval():
    start = pd.Timestamp("2026-01-01T00:00Z")
    complete = grid(start, interval_seconds=30, periods=31)
    assert completeness(complete, complete.iloc[[-1]], start, 30).item()
    assert not completeness(complete.drop(index=15), complete.iloc[[-1]], start, 30).item()
