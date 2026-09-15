"""Authoritative configured timestamp and service-key grids for generated telemetry."""

import pandas as pd

from reliability_intelligence.config import SimulationConfig

KEY_COLUMNS = ["timestamp", "service_id"]


def configured_timestamps(config: SimulationConfig) -> pd.DatetimeIndex:
    """Return the complete half-open timestamp grid defined by simulation configuration."""
    count = config.duration_minutes * 60 // config.interval_seconds
    return pd.date_range(
        pd.Timestamp(config.start).tz_convert("UTC"),
        periods=count,
        freq=pd.Timedelta(seconds=config.interval_seconds),
    )


def configured_telemetry_keys(config: SimulationConfig) -> pd.MultiIndex:
    """Return canonical keys ordered by ascending timestamp, then service identifier."""
    return pd.MultiIndex.from_product(
        [configured_timestamps(config), sorted(service.name for service in config.services)],
        names=KEY_COLUMNS,
    )
