"""Ground-truth scheduling and continuous lifecycle pressure (never exported as telemetry)."""

import numpy as np
import pandas as pd

from reliability_intelligence.config import INCIDENT_TYPES, IncidentSpec, SimulationConfig

TRUTH_COLUMNS = [
    "incident_id",
    "service_id",
    "incident_type",
    "precursor_start",
    "incident_start",
    "incident_end",
    "recovery_end",
    "severity",
]


def schedule(config: SimulationConfig, rng: np.random.Generator) -> tuple[IncidentSpec, ...]:
    if config.incidents is not None:
        return tuple(
            sorted(config.incidents, key=lambda i: (i.precursor_start_minute, i.service_id))
        )
    count = config.incidents_per_service
    if not count:
        return ()
    block = (config.duration_minutes - config.warmup_minutes - config.cooldown_minutes) / count
    lifecycle = config.precursor_minutes + config.active_minutes + config.recovery_minutes
    events = []
    for service in config.services:
        kinds = list(np.resize(INCIDENT_TYPES, count))
        rng.shuffle(kinds)
        for index, kind in enumerate(kinds):
            begin = config.warmup_minutes + index * block + rng.uniform(0, block - lifecycle)
            events.append(
                IncidentSpec(
                    service_id=service.name,
                    incident_type=str(kind),
                    precursor_start_minute=float(begin),
                    precursor_minutes=config.precursor_minutes,
                    active_minutes=config.active_minutes,
                    recovery_minutes=config.recovery_minutes,
                    severity=float(rng.uniform(0.85, 1.15)),
                )
            )
    return tuple(sorted(events, key=lambda i: (i.precursor_start_minute, i.service_id)))


def pressure(minutes: np.ndarray, incident: IncidentSpec, onset: float) -> np.ndarray:
    """Smooth precursor to onset, active ramp/plateau, then linear recovery; zero outside."""
    result = np.zeros(len(minutes))
    before = (minutes >= incident.precursor_start_minute) & (minutes < incident.start_minute)
    active = (minutes >= incident.start_minute) & (minutes < incident.end_minute)
    recovery = (minutes >= incident.end_minute) & (minutes < incident.recovery_end_minute)
    result[before] = onset * (
        (minutes[before] - incident.precursor_start_minute) / incident.precursor_minutes
    )
    result[active] = onset + (1 - onset) * np.minimum(
        (minutes[active] - incident.start_minute) / (incident.active_minutes / 3), 1
    )
    result[recovery] = 1 - (minutes[recovery] - incident.end_minute) / incident.recovery_minutes
    return result * incident.severity


def ground_truth(config: SimulationConfig, events: tuple[IncidentSpec, ...]) -> pd.DataFrame:
    rows = []
    start = pd.Timestamp(config.start).tz_convert("UTC")
    for index, incident in enumerate(events):
        rows.append(
            {
                "incident_id": f"incident-{index:04d}",
                "service_id": incident.service_id,
                "incident_type": incident.incident_type,
                "precursor_start": start + pd.Timedelta(minutes=incident.precursor_start_minute),
                "incident_start": start + pd.Timedelta(minutes=incident.start_minute),
                "incident_end": start + pd.Timedelta(minutes=incident.end_minute),
                "recovery_end": start + pd.Timedelta(minutes=incident.recovery_end_minute),
                "severity": incident.severity,
            }
        )
    frame = pd.DataFrame(rows, columns=TRUTH_COLUMNS)
    for name in ("precursor_start", "incident_start", "incident_end", "recovery_end"):
        frame[name] = pd.to_datetime(frame[name], utc=True)
    for name in ("incident_id", "service_id", "incident_type"):
        frame[name] = frame[name].astype("string")
    frame["severity"] = frame["severity"].astype("float64")
    return frame
