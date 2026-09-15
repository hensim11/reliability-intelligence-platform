"""Time-dependent synthetic signals, with independent noise and scheduling RNG streams."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from reliability_intelligence.config import INCIDENT_TYPES, SimulationConfig
from reliability_intelligence.labels import future_labels
from reliability_intelligence.schemas import TELEMETRY_COLUMNS, validate_telemetry
from reliability_intelligence.simulation.incidents import ground_truth, pressure, schedule
from reliability_intelligence.telemetry_grid import KEY_COLUMNS, configured_timestamps


@dataclass(frozen=True)
class SimulationResult:
    telemetry: pd.DataFrame
    incidents: pd.DataFrame
    labels: pd.DataFrame


def correlated_noise(
    rng: np.random.Generator,
    size: int,
    interval_seconds: int,
    correlation_minutes: float,
) -> np.ndarray:
    """Stationary AR(1) noise; correlation length is expressed in physical time."""
    rho = np.exp(-interval_seconds / (60 * correlation_minutes))
    draws = rng.normal(size=size)
    for index in range(1, size):
        draws[index] = rho * draws[index - 1] + np.sqrt(1 - rho**2) * draws[index]
    return draws


def simulate(config: SimulationConfig) -> SimulationResult:
    seeds = np.random.SeedSequence(config.seed).spawn(2 + len(config.services))
    events = schedule(config, np.random.default_rng(seeds[0]))
    timestamps = configured_timestamps(config)
    count = len(timestamps)
    minutes = np.arange(count) * config.interval_seconds / 60
    d = config.dynamics
    shared = correlated_noise(
        np.random.default_rng(seeds[1]), count, config.interval_seconds, d.noise_correlation_minutes
    )
    daily = 1 + d.daily_load_amplitude * np.sin(2 * np.pi * minutes / 1440)
    hourly = d.hourly_load_amplitude * np.sin(2 * np.pi * minutes / 60)
    frames = []
    for service, seed in zip(config.services, seeds[2:], strict=True):
        rng = np.random.default_rng(seed)
        noise = np.stack(
            [
                correlated_noise(rng, count, config.interval_seconds, d.noise_correlation_minutes)
                for _ in range(5)
            ]
        )
        effects = {kind: np.zeros(count) for kind in INCIDENT_TYPES}
        for incident in events:
            if incident.service_id == service.name:
                effects[incident.incident_type] += pressure(minutes, incident, d.onset_pressure)
        load = np.maximum(0.1, daily + hourly + d.noise_std * (shared + noise[0]))
        rps = service.baseline_rps * load * (1 + d.traffic_multiplier * effects["traffic_overload"])
        utilisation = rps / service.capacity_rps
        cpu = np.clip(
            d.cpu_idle_pct
            + d.cpu_load_pct * utilisation
            + noise[1]
            + d.cpu_pressure_pct * effects["cpu_saturation"],
            0,
            100,
        )
        memory = np.clip(
            service.base_memory_pct
            + d.memory_load_pct * utilisation
            + noise[2]
            + d.memory_leak_pct * effects["memory_leak"],
            0,
            100,
        )
        dependency = np.maximum(
            1,
            service.base_dependency_ms * (1 + 0.2 * utilisation + d.noise_std * noise[3])
            + d.database_delay_ms * effects["database_degradation"],
        )
        cpu_stress = np.maximum(0, (cpu - d.cpu_knee_pct) / (100 - d.cpu_knee_pct))
        memory_stress = np.maximum(0, (memory - d.memory_knee_pct) / (100 - d.memory_knee_pct))
        overload = np.maximum(0, utilisation - 1)
        stress = (
            d.cpu_latency_gain * cpu_stress
            + d.memory_latency_gain * memory_stress
            + d.overload_latency_gain * overload
        )
        p50 = np.maximum(
            1,
            service.base_latency_ms
            * (1 + 0.25 * utilisation + stress)
            * (1 + d.noise_std * noise[4])
            + dependency,
        )
        p95 = p50 * (1.6 + 0.4 * stress) + 0.3 * dependency
        errors = np.clip(
            d.baseline_error_rate * np.exp(0.3 * noise[4])
            + d.stress_error_gain
            * (stress + np.maximum(0, dependency / service.base_dependency_ms - 3) / 5),
            0,
            1,
        )
        frames.append(
            pd.DataFrame(
                {
                    "timestamp": timestamps,
                    "service_id": service.name,
                    "request_rate_rps": rps,
                    "latency_p50_ms": p50,
                    "latency_p95_ms": p95,
                    "error_rate": errors,
                    "cpu_utilisation_pct": cpu,
                    "memory_utilisation_pct": memory,
                    "dependency_latency_ms": dependency,
                },
                columns=TELEMETRY_COLUMNS,
            )
        )
    telemetry = pd.concat(frames, ignore_index=True).sort_values(KEY_COLUMNS, ignore_index=True)
    telemetry["service_id"] = telemetry.service_id.astype("string")
    validate_telemetry(telemetry)
    truth = ground_truth(config, events)
    labels = future_labels(
        telemetry,
        truth,
        coverage_start=timestamps[0],
        coverage_end=timestamps[0] + pd.Timedelta(minutes=config.duration_minutes),
        horizon_minutes=config.horizon_minutes,
        observation_minutes=config.observation_minutes,
        interval_seconds=config.interval_seconds,
    )
    return SimulationResult(telemetry, truth, labels)
