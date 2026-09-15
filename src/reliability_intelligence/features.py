"""Versioned telemetry-only features, reusable without targets or incident truth."""

import numpy as np
import pandas as pd

from reliability_intelligence.schemas import LABEL_COLUMNS, TELEMETRY_COLUMNS, validate_telemetry
from reliability_intelligence.telemetry_grid import KEY_COLUMNS

FEATURE_VERSION = "1.0"
METRICS = tuple(TELEMETRY_COLUMNS[2:])
STATISTICS = ("current", "mean", "std", "min", "max", "change", "slope")
FEATURE_NAMES = tuple(f"{metric}__{stat}" for metric in METRICS for stat in STATISTICS)
TARGET = "incident_within_horizon"


def feature_matrix(frame: pd.DataFrame) -> pd.DataFrame:
    """Strict inference boundary: no extra, reordered, non-float or nonfinite columns."""
    if tuple(frame.columns) != FEATURE_NAMES:
        raise ValueError("Feature columns must match the versioned allowlist in order")
    if any(dtype != np.dtype("float64") for dtype in frame.dtypes):
        raise ValueError("Features must use float64")
    if not np.isfinite(frame.to_numpy()).all():
        raise ValueError("Features must be finite")
    return frame


def build_features(telemetry: pd.DataFrame, *, coverage_start: pd.Timestamp) -> pd.DataFrame:
    """Require a one-minute grid; gaps make affected windows ineligible, never repaired.

    Off-grid observations are rejected. Only exact contiguous per-service 15-point
    windows enter the result; full elapsed history remains a conservative requirement.
    """
    validate_telemetry(telemetry)
    if coverage_start.tz is None or str(coverage_start.tz) != "UTC":
        raise ValueError("coverage_start must be UTC")
    elapsed = telemetry.timestamp - coverage_start
    if (elapsed < pd.Timedelta(0)).any() or (elapsed % pd.Timedelta(minutes=1)).any():
        raise ValueError("Telemetry must lie on the one-minute coverage grid")
    frames = []
    x = np.arange(15, dtype=float) - 7
    for _, rows in telemetry.groupby("service_id", sort=True):
        rows = rows.reset_index(drop=True)
        if len(rows) < 15:
            continue
        values = rows[list(METRICS)].to_numpy(dtype=float)
        windows = np.lib.stride_tricks.sliding_window_view(values, 15, axis=0)
        stats = np.stack(
            [
                windows[:, :, -1],
                windows.mean(2),
                windows.std(2),
                windows.min(2),
                windows.max(2),
                windows[:, :, -1] - windows[:, :, 0],
                windows @ x / (x @ x),
            ],
            axis=2,
        ).reshape(-1, len(FEATURE_NAMES))
        keys = rows[KEY_COLUMNS].iloc[14:].reset_index(drop=True)
        span = rows.timestamp.iloc[14:].reset_index(drop=True) - rows.timestamp.iloc[
            :-14
        ].reset_index(drop=True)
        valid = (span == pd.Timedelta(minutes=14)) & (
            keys.timestamp >= coverage_start + pd.Timedelta(minutes=15)
        )
        frames.append(
            pd.concat([keys, pd.DataFrame(stats, columns=FEATURE_NAMES)], axis=1).loc[valid]
        )
    if not frames:
        return pd.DataFrame(columns=[*KEY_COLUMNS, *FEATURE_NAMES])
    result = pd.concat(frames, ignore_index=True).sort_values(KEY_COLUMNS, ignore_index=True)
    feature_matrix(result[list(FEATURE_NAMES)])
    return result


def attach_targets(features: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    if list(labels.columns) != LABEL_COLUMNS or labels.duplicated(KEY_COLUMNS).any():
        raise ValueError("Labels must have exact schema and unique keys")
    if labels[TARGET].dtype != pd.Int8Dtype() or not labels[TARGET].dropna().isin([0, 1]).all():
        raise ValueError("Target must be nullable binary Int8")
    for name in ("history_complete", "horizon_complete"):
        if labels[name].dtype != np.dtype("bool"):
            raise ValueError("Eligibility flags must be boolean")
    if list(features.columns) != [*KEY_COLUMNS, *FEATURE_NAMES]:
        raise ValueError("Unexpected feature table columns")
    feature_matrix(features[list(FEATURE_NAMES)])
    joined = features.merge(
        labels, on=KEY_COLUMNS, how="left", validate="one_to_one", indicator=True
    )
    if not joined._merge.eq("both").all():
        raise ValueError("Every feature key must have exactly one target row")
    eligible = joined.history_complete & joined.horizon_complete & joined[TARGET].notna()
    return joined.loc[eligible, [*KEY_COLUMNS, *FEATURE_NAMES, TARGET]].reset_index(drop=True)


def partition_mask(timestamps: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    """For [start,end), retain t-15m >= start and t+10m < end."""
    if start.tz is None or end.tz is None or start >= end:
        raise ValueError("Partition must be a nonempty timezone-aware interval")
    return (timestamps - pd.Timedelta(minutes=15) >= start) & (
        timestamps + pd.Timedelta(minutes=10) < end
    )
