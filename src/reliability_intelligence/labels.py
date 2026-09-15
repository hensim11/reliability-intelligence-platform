"""Offline targets, isolated from generation: future starts in (t, t + 10 minutes]."""

import math

import numpy as np
import pandas as pd


def history_grid_complete(
    telemetry: pd.DataFrame,
    prediction_keys: pd.DataFrame,
    *,
    coverage_start: pd.Timestamp,
    observation_minutes: int,
    interval_seconds: int,
) -> pd.Series:
    """Return whether every service-specific grid point in ``(t-window, t]`` exists.

    Prediction keys may include a timestamp absent from telemetry, which supports readiness
    checks for a requested prediction time. Expected points never extend past t.
    """
    if observation_minutes <= 0 or interval_seconds <= 0:
        raise ValueError("Observation window and telemetry interval must be positive")
    interval = pd.Timedelta(seconds=interval_seconds)
    window = pd.Timedelta(minutes=observation_minutes)
    expected_count = math.ceil(window / interval)
    available = {
        service: set(pd.DatetimeIndex(rows.timestamp))
        for service, rows in telemetry.groupby("service_id", sort=False)
    }
    result = []
    for row in prediction_keys[["timestamp", "service_id"]].itertuples(index=False):
        timestamp = row.timestamp
        elapsed = timestamp - coverage_start
        if elapsed < window or elapsed % interval:
            result.append(False)
            continue
        expected = pd.date_range(end=timestamp, periods=expected_count, freq=interval)
        service_timestamps = available.get(row.service_id, set())
        result.append(all(point in service_timestamps for point in expected))
    return pd.Series(result, index=prediction_keys.index, dtype="bool")


def future_labels(
    telemetry: pd.DataFrame,
    incidents: pd.DataFrame,
    *,
    coverage_start: pd.Timestamp,
    coverage_end: pd.Timestamp,
    horizon_minutes: int = 10,
    observation_minutes: int = 15,
    interval_seconds: int,
) -> pd.DataFrame:
    """Coverage is [start, end). Incomplete horizons are unknown, never false negatives.

    History completeness requires every configured service-specific telemetry grid point
    in the open-left, closed-right observation window. It never examines data after t.
    """
    if horizon_minutes <= 0 or observation_minutes <= 0:
        raise ValueError("Window durations must be positive")
    if coverage_start >= coverage_end:
        raise ValueError("Coverage must be nonempty")
    if ((telemetry.timestamp < coverage_start) | (telemetry.timestamp >= coverage_end)).any():
        raise ValueError("Telemetry lies outside declared coverage")
    result = telemetry[["timestamp", "service_id"]].copy().reset_index(drop=True)
    horizon = pd.Timedelta(minutes=horizon_minutes)
    result["history_complete"] = history_grid_complete(
        telemetry,
        result,
        coverage_start=coverage_start,
        observation_minutes=observation_minutes,
        interval_seconds=interval_seconds,
    )
    result["horizon_complete"] = result.timestamp + horizon < coverage_end
    targets = np.zeros(len(result), dtype=np.int8)
    for service, rows in result.groupby("service_id", sort=False):
        # DatetimeIndex comparisons retain time units across pandas 2 and 3.
        starts = pd.DatetimeIndex(
            incidents.loc[incidents.service_id == service, "incident_start"]
        ).sort_values()
        timestamps = pd.DatetimeIndex(rows.timestamp)
        left = starts.searchsorted(timestamps, side="right")
        right = starts.searchsorted(timestamps + horizon, side="right")
        targets[rows.index] = (right > left).astype(np.int8)
    result["incident_within_horizon"] = pd.array(targets, dtype="Int8")
    result.loc[~result.horizon_complete, "incident_within_horizon"] = pd.NA
    return result
