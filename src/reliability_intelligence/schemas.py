"""Operational schema contract; a strict allowlist prevents metadata entering model inputs."""

import numpy as np
import pandas as pd

from reliability_intelligence.config import INCIDENT_TYPES, SimulationConfig
from reliability_intelligence.labels import future_labels
from reliability_intelligence.simulation.incidents import TRUTH_COLUMNS
from reliability_intelligence.telemetry_grid import KEY_COLUMNS, configured_telemetry_keys

TELEMETRY_COLUMNS = [
    "timestamp",
    "service_id",
    "request_rate_rps",
    "latency_p50_ms",
    "latency_p95_ms",
    "error_rate",
    "cpu_utilisation_pct",
    "memory_utilisation_pct",
    "dependency_latency_ms",
]

LABEL_COLUMNS = [
    "timestamp",
    "service_id",
    "history_complete",
    "horizon_complete",
    "incident_within_horizon",
]

LIFECYCLE_COLUMNS = [
    "precursor_start",
    "incident_start",
    "incident_end",
    "recovery_end",
]


def _validate_utc_timestamp(frame: pd.DataFrame, column: str, table: str) -> None:
    if not isinstance(frame[column].dtype, pd.DatetimeTZDtype):
        raise ValueError(f"{table} {column} must be a timezone-aware timestamp")
    if str(frame[column].dt.tz) != "UTC":
        raise ValueError(f"{table} {column} must use UTC")


def _validate_string_column(frame: pd.DataFrame, column: str, table: str) -> None:
    if not isinstance(frame[column].dtype, pd.StringDtype):
        raise ValueError(f"{table} {column} must use string dtype")
    if frame[column].isna().any() or (
        not frame.empty and frame[column].map(lambda value: not value.strip()).any()
    ):
        raise ValueError(f"{table} {column} must contain nonempty strings")


def validate_telemetry(frame: pd.DataFrame) -> None:
    if list(frame.columns) != TELEMETRY_COLUMNS:
        raise ValueError("Telemetry columns must match the operational allowlist exactly")
    if frame.empty:
        raise ValueError("Telemetry must not be empty")
    if frame.isna().any().any():
        raise ValueError("Telemetry must not contain nulls")
    if not isinstance(frame.timestamp.dtype, pd.DatetimeTZDtype):
        raise ValueError("Timestamps must be timezone aware")
    if str(frame.timestamp.dt.tz) != "UTC":
        raise ValueError("Telemetry timestamps must use UTC")
    if frame.service_id.map(lambda value: not isinstance(value, str) or not value.strip()).any():
        raise ValueError("Service identifiers must be nonempty strings")
    if frame.duplicated(KEY_COLUMNS).any():
        raise ValueError("Duplicate service/timestamp keys")
    for _, rows in frame.groupby("service_id", sort=False):
        if not rows.timestamp.is_monotonic_increasing:
            raise ValueError("Per-service telemetry must be ordered")
    try:
        values = frame[TELEMETRY_COLUMNS[2:]].to_numpy(dtype=float)
    except (TypeError, ValueError) as error:
        raise ValueError("Metrics must be numeric") from error
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("Metrics must be finite and nonnegative")
    if (frame.error_rate > 1).any():
        raise ValueError("Error rate must be a fraction in [0, 1]")
    if (frame[["cpu_utilisation_pct", "memory_utilisation_pct"]] > 100).any().any():
        raise ValueError("Resource utilisation must lie in [0, 100]")
    if (frame.latency_p95_ms < frame.latency_p50_ms).any():
        raise ValueError("p95 latency cannot be below p50")


def validate_telemetry_grid(frame: pd.DataFrame, config: SimulationConfig) -> None:
    """Require exactly the configured keys in canonical timestamp/service order."""
    actual = pd.MultiIndex.from_frame(frame[KEY_COLUMNS])
    if actual.has_duplicates:
        raise ValueError("Telemetry grid contains duplicate service/timestamp keys")
    expected = configured_telemetry_keys(config)
    missing = expected.difference(actual)
    unexpected = actual.difference(expected)
    if len(missing) or len(unexpected):
        raise ValueError(
            "Telemetry grid disagrees with configuration: "
            f"missing {len(missing)} expected key(s); "
            f"unexpected {len(unexpected)} key(s)"
        )
    if not actual.equals(expected):
        raise ValueError("Telemetry rows must use canonical timestamp/service ordering")


def validate_incidents(
    frame: pd.DataFrame,
    *,
    configured_services: set[str],
    coverage_start: pd.Timestamp,
    coverage_end: pd.Timestamp,
) -> None:
    """Validate simulation truth without exposing it to operational telemetry."""
    if list(frame.columns) != TRUTH_COLUMNS:
        raise ValueError("Incident columns must match the ground-truth contract exactly")
    for column in ("incident_id", "service_id", "incident_type"):
        _validate_string_column(frame, column, "Incident")
    for column in LIFECYCLE_COLUMNS:
        _validate_utc_timestamp(frame, column, "Incident")
    if frame.severity.dtype != np.dtype("float64"):
        raise ValueError("Incident severity must use float64 dtype")
    if frame.incident_id.duplicated().any():
        raise ValueError("Incident IDs must be unique")
    if not set(frame.service_id).issubset(configured_services):
        raise ValueError("Incident references a service absent from configuration")
    if not set(frame.incident_type).issubset(INCIDENT_TYPES):
        raise ValueError("Incident type is not supported")
    if (
        not np.isfinite(frame.severity.to_numpy()).all()
        or not frame.severity.between(0.5, 1.5, inclusive="both").all()
    ):
        raise ValueError("Incident severity must be finite and in [0.5, 1.5]")
    ordered = (
        (frame.precursor_start < frame.incident_start)
        & (frame.incident_start < frame.incident_end)
        & (frame.incident_end < frame.recovery_end)
    )
    if not ordered.all():
        raise ValueError("Incident lifecycle boundaries must be strictly ordered")
    if (frame.precursor_start < coverage_start).any() or (frame.recovery_end > coverage_end).any():
        raise ValueError("Incident lifecycle lies outside dataset coverage")
    for _, incidents in frame.groupby("service_id", sort=False):
        incidents = incidents.sort_values("precursor_start")
        if (
            incidents.recovery_end.iloc[:-1].reset_index(drop=True)
            > incidents.precursor_start.iloc[1:].reset_index(drop=True)
        ).any():
            raise ValueError("Incident lifecycles overlap for one service")


def validate_labels(
    frame: pd.DataFrame,
    telemetry: pd.DataFrame,
    incidents: pd.DataFrame,
    *,
    config: SimulationConfig,
    coverage_start: pd.Timestamp,
    coverage_end: pd.Timestamp,
) -> None:
    """Validate offline labels against coverage and same-service incident starts."""
    if list(frame.columns) != LABEL_COLUMNS:
        raise ValueError("Label columns must match the offline-target contract exactly")
    if len(frame) != len(telemetry):
        raise ValueError("Labels must contain exactly one row per telemetry row")
    _validate_utc_timestamp(frame, "timestamp", "Label")
    _validate_string_column(frame, "service_id", "Label")
    if frame.duplicated(["service_id", "timestamp"]).any():
        raise ValueError("Label service/timestamp keys must be unique")
    if not telemetry[["timestamp", "service_id"]].equals(frame[["timestamp", "service_id"]]):
        raise ValueError("Labels must align one-to-one and in order with operational telemetry")
    for column in ("history_complete", "horizon_complete"):
        if frame[column].dtype != np.dtype("bool") or frame[column].isna().any():
            raise ValueError(f"Label {column} must use non-null boolean dtype")
    if frame.incident_within_horizon.dtype != pd.Int8Dtype():
        raise ValueError("Label target must use nullable Int8 dtype")
    observed = frame.incident_within_horizon.dropna()
    if not observed.isin([0, 1]).all():
        raise ValueError("Label target values must be 0, 1, or null")
    if not frame.loc[~frame.horizon_complete, "incident_within_horizon"].isna().all():
        raise ValueError("Label target must be null when the horizon is incomplete")
    if frame.loc[frame.horizon_complete, "incident_within_horizon"].isna().any():
        raise ValueError("Label target must not be null when the horizon is complete")
    expected = future_labels(
        telemetry,
        incidents,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        horizon_minutes=config.horizon_minutes,
        observation_minutes=config.observation_minutes,
        interval_seconds=config.interval_seconds,
    )
    for column in ("history_complete", "horizon_complete", "incident_within_horizon"):
        if not frame[column].equals(expected[column]):
            raise ValueError(f"Label {column} is inconsistent with coverage or incident truth")
