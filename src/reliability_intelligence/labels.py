"""Offline targets, isolated from generation: future starts in (t, t + 10 minutes]."""

import numpy as np
import pandas as pd


def future_labels(
    telemetry: pd.DataFrame,
    incidents: pd.DataFrame,
    *,
    coverage_start: pd.Timestamp,
    coverage_end: pd.Timestamp,
    horizon_minutes: int = 10,
    observation_minutes: int = 15,
) -> pd.DataFrame:
    """Coverage is [start, end). Incomplete horizons are unknown, never false negatives.

    History completeness refers to elapsed coverage, not feature materialisation. Batch A
    provides dense samples; later ingestion must separately assess gaps and late arrival.
    """
    if horizon_minutes <= 0 or observation_minutes <= 0:
        raise ValueError("Window durations must be positive")
    if coverage_start >= coverage_end:
        raise ValueError("Coverage must be nonempty")
    if ((telemetry.timestamp < coverage_start) | (telemetry.timestamp >= coverage_end)).any():
        raise ValueError("Telemetry lies outside declared coverage")
    result = telemetry[["timestamp", "service_id"]].copy().reset_index(drop=True)
    horizon = pd.Timedelta(minutes=horizon_minutes)
    result["history_complete"] = (
        result.timestamp - pd.Timedelta(minutes=observation_minutes) >= coverage_start
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
