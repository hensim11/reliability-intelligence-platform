"""Strict, serialisable simulation configuration. All time durations use minutes."""

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

INCIDENT_TYPES = ("memory_leak", "database_degradation", "cpu_saturation", "traffic_overload")


def positive(value: float, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")


@dataclass(frozen=True)
class ServiceProfile:
    name: str
    baseline_rps: float
    capacity_rps: float
    base_latency_ms: float
    base_dependency_ms: float
    base_memory_pct: float

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Service name must be nonempty")
        for key, value in asdict(self).items():
            if key != "name":
                positive(value, key)
        if self.baseline_rps >= self.capacity_rps or self.base_memory_pct >= 80:
            raise ValueError("Baseline must leave traffic and memory headroom")


@dataclass(frozen=True)
class Dynamics:
    """Interpretable coefficients; pct values are percentage points, rates are fractions."""

    daily_load_amplitude: float = 0.22
    hourly_load_amplitude: float = 0.06
    noise_std: float = 0.025
    noise_correlation_minutes: float = 5.0
    cpu_idle_pct: float = 18.0
    cpu_load_pct: float = 48.0
    memory_load_pct: float = 5.0
    memory_leak_pct: float = 48.0
    database_delay_ms: float = 260.0
    cpu_pressure_pct: float = 68.0
    traffic_multiplier: float = 2.8
    onset_pressure: float = 0.7
    cpu_knee_pct: float = 70.0
    memory_knee_pct: float = 80.0
    cpu_latency_gain: float = 3.0
    memory_latency_gain: float = 2.0
    overload_latency_gain: float = 2.5
    baseline_error_rate: float = 0.001
    stress_error_gain: float = 0.035

    def __post_init__(self) -> None:
        for key, value in asdict(self).items():
            positive(value, key)
        if not 0 < self.onset_pressure < 1:
            raise ValueError("onset_pressure must be in (0, 1)")
        if self.daily_load_amplitude + self.hourly_load_amplitude >= 0.8:
            raise ValueError("Load cycles must retain positive baseline headroom")
        if not 0 < self.baseline_error_rate < 1:
            raise ValueError("baseline_error_rate must be in (0, 1)")
        if not 0 < self.cpu_knee_pct < 100 or not 0 < self.memory_knee_pct < 100:
            raise ValueError("Resource knees must be in (0, 100)")


@dataclass(frozen=True)
class IncidentSpec:
    service_id: str
    incident_type: str
    precursor_start_minute: float
    precursor_minutes: float = 25
    active_minutes: float = 30
    recovery_minutes: float = 20
    severity: float = 1.0

    def __post_init__(self) -> None:
        if self.incident_type not in INCIDENT_TYPES:
            raise ValueError(f"Unknown incident type: {self.incident_type}")
        if isinstance(self.precursor_start_minute, bool) or not isinstance(
            self.precursor_start_minute, (int, float)
        ):
            raise ValueError("precursor_start_minute must be numeric")
        if not math.isfinite(self.precursor_start_minute) or self.precursor_start_minute < 0:
            raise ValueError("precursor_start_minute must be finite and nonnegative")
        for key in ("precursor_minutes", "active_minutes", "recovery_minutes", "severity"):
            positive(getattr(self, key), key)
        if not 0.5 <= self.severity <= 1.5:
            raise ValueError("severity must be between 0.5 and 1.5")

    @property
    def start_minute(self) -> float:
        return self.precursor_start_minute + self.precursor_minutes

    @property
    def end_minute(self) -> float:
        return self.start_minute + self.active_minutes

    @property
    def recovery_end_minute(self) -> float:
        return self.end_minute + self.recovery_minutes


@dataclass(frozen=True)
class SimulationConfig:
    start_time: str
    duration_minutes: int
    interval_seconds: int
    seed: int
    services: tuple[ServiceProfile, ...]
    incidents_per_service: int = 4
    incidents: tuple[IncidentSpec, ...] | None = None
    observation_minutes: int = 15
    horizon_minutes: int = 10
    precursor_minutes: int = 25
    active_minutes: int = 30
    recovery_minutes: int = 20
    warmup_minutes: int = 120
    cooldown_minutes: int = 60
    dynamics: Dynamics = field(default_factory=Dynamics)

    def __post_init__(self) -> None:
        for key in (
            "duration_minutes",
            "interval_seconds",
            "observation_minutes",
            "horizon_minutes",
            "precursor_minutes",
            "active_minutes",
            "recovery_minutes",
            "warmup_minutes",
            "cooldown_minutes",
        ):
            value = getattr(self, key)
            positive(value, key)
            if type(value) is not int:
                raise ValueError(f"{key} must be an integer")
        if type(self.seed) is not int or self.seed < 0:
            raise ValueError("seed must be a nonnegative integer")
        if type(self.incidents_per_service) is not int or self.incidents_per_service < 0:
            raise ValueError("incidents_per_service must be a nonnegative integer")
        if self.observation_minutes != 15 or self.horizon_minutes != 10:
            raise ValueError("Batch A fixes observation=15 and horizon=10 minutes")
        if self.duration_minutes * 60 % self.interval_seconds:
            raise ValueError("Duration must contain a whole number of telemetry intervals")
        if self.interval_seconds > 60:
            raise ValueError("Batch A supports sampling intervals of at most 60 seconds")
        if not self.services or len({s.name for s in self.services}) != len(self.services):
            raise ValueError("At least one service is required; names must be unique")
        if self.start.tzinfo is None or self.start.utcoffset() is None:
            raise ValueError("start_time must include a timezone")
        object.__setattr__(self, "start_time", self.start.astimezone(UTC).isoformat())
        if self.incidents is not None:
            for incident in self.incidents:
                if incident.service_id not in {s.name for s in self.services}:
                    raise ValueError("Incident references an unknown service")
                if incident.recovery_end_minute > self.duration_minutes:
                    raise ValueError("All incident lifecycles must fit within the simulation")
            for service in self.services:
                events = sorted(
                    (i for i in self.incidents if i.service_id == service.name),
                    key=lambda i: i.precursor_start_minute,
                )
                if any(
                    a.recovery_end_minute > b.precursor_start_minute
                    for a, b in zip(events, events[1:], strict=False)
                ):
                    raise ValueError("Incident lifecycles cannot overlap within a service")
        elif self.incidents_per_service:
            available = self.duration_minutes - self.warmup_minutes - self.cooldown_minutes
            lifecycle = self.precursor_minutes + self.active_minutes + self.recovery_minutes
            if available / self.incidents_per_service < lifecycle + self.interval_seconds / 60:
                raise ValueError("Simulation is too short for the requested incident schedule")

    @property
    def start(self) -> datetime:
        return datetime.fromisoformat(self.start_time.replace("Z", "+00:00"))

    def to_dict(self) -> dict:
        result = asdict(self)
        result["start_time"] = self.start.astimezone(UTC).isoformat()
        return result

    @classmethod
    def from_dict(cls, raw: dict) -> SimulationConfig:
        values = dict(raw)
        values["services"] = tuple(ServiceProfile(**v) for v in values["services"])
        if values.get("incidents") is not None:
            values["incidents"] = tuple(IncidentSpec(**v) for v in values["incidents"])
        values["dynamics"] = Dynamics(**values.get("dynamics", {}))
        return cls(**values)

    @classmethod
    def load(cls, path: str | Path) -> SimulationConfig:
        with Path(path).open() as handle:
            return cls.from_dict(json.load(handle))
