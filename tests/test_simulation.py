from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from reliability_intelligence.config import INCIDENT_TYPES, IncidentSpec, SimulationConfig
from reliability_intelligence.schemas import TELEMETRY_COLUMNS, validate_telemetry
from reliability_intelligence.simulation.engine import simulate
from reliability_intelligence.simulation.incidents import pressure, schedule


def test_deterministic_generation_and_different_seed(config):
    first, second = simulate(config), simulate(config)
    for name in ("telemetry", "incidents", "labels"):
        pd.testing.assert_frame_equal(getattr(first, name), getattr(second, name))
    assert not first.telemetry.equals(simulate(replace(config, seed=99)).telemetry)


def test_default_schedule_covers_scenarios_without_overlap():
    config = SimulationConfig.load("configs/batch_a.json")
    first = schedule(config, np.random.default_rng(123))
    assert first == schedule(config, np.random.default_rng(123))
    assert first != schedule(config, np.random.default_rng(456))
    for service in config.services:
        events = [event for event in first if event.service_id == service.name]
        assert {event.incident_type for event in events} == set(INCIDENT_TYPES)
        assert len(events) == 4
        assert events[0].precursor_start_minute >= config.warmup_minutes
        assert events[-1].recovery_end_minute <= config.duration_minutes - config.cooldown_minutes
        assert all(
            a.recovery_end_minute <= b.precursor_start_minute
            for a, b in zip(events, events[1:], strict=False)
        )


def test_lifecycle_continuity_and_boundaries():
    incident = IncidentSpec("a", "memory_leak", 10, 20, 30, 20)
    assert pressure(np.array([0, 10, 20, 30, 40, 60, 70, 80, 90]), incident, 0.7).tolist() == (
        [0, 0, 0.35, 0.7, 1, 1, 0.5, 0, 0]
    )
    for boundary in (10, 30, 60, 80):
        values = pressure(np.array([boundary - 1e-7, boundary + 1e-7]), incident, 0.7)
        assert abs(values[1] - values[0]) < 1e-6


@pytest.mark.parametrize(
    "kind,metric",
    [
        ("memory_leak", "memory_utilisation_pct"),
        ("database_degradation", "dependency_latency_ms"),
        ("cpu_saturation", "cpu_utilisation_pct"),
        ("traffic_overload", "request_rate_rps"),
    ],
)
def test_scenario_causal_effects_and_recovery(config, kind, metric):
    event = IncidentSpec(config.services[0].name, kind, 40)
    baseline = simulate(config)
    affected = simulate(replace(config, incidents=(event,)))
    base = baseline.telemetry.loc[baseline.telemetry.service_id == event.service_id].reset_index(
        drop=True
    )
    rows = affected.telemetry.loc[affected.telemetry.service_id == event.service_id].reset_index(
        drop=True
    )
    pd.testing.assert_frame_equal(base.iloc[:40], rows.iloc[:40])
    pd.testing.assert_frame_equal(base.iloc[115:], rows.iloc[115:])
    delta = rows[metric] - base[metric]
    assert delta.iloc[45:50].mean() > 0
    assert delta.iloc[55:60].mean() > delta.iloc[45:50].mean()
    assert delta.iloc[75:90].mean() > delta.iloc[55:60].mean()
    assert rows.latency_p95_ms.iloc[75:90].mean() > base.latency_p95_ms.iloc[75:90].mean()
    assert rows.error_rate.iloc[75:90].mean() > base.error_rate.iloc[75:90].mean()
    other = config.services[1].name
    pd.testing.assert_frame_equal(
        baseline.telemetry.loc[baseline.telemetry.service_id == other],
        affected.telemetry.loc[affected.telemetry.service_id == other],
    )


def test_schema_and_temporal_structure(config):
    result = simulate(config)
    validate_telemetry(result.telemetry)
    assert list(result.telemetry) == TELEMETRY_COLUMNS
    assert len(result.telemetry) == 360
    assert result.incidents.empty
    assert result.labels.incident_within_horizon.dropna().eq(0).all()
    for _, rows in result.telemetry.groupby("service_id"):
        assert rows.timestamp.diff().dropna().eq(pd.Timedelta(seconds=60)).all()
        assert rows.request_rate_rps.autocorr() > 0.8
        assert rows.request_rate_rps.corr(rows.cpu_utilisation_pct) > 0.5


@pytest.mark.parametrize("corruption", ["leak", "nan", "range", "p95", "duplicate", "order"])
def test_schema_rejects_invalid_data(config, corruption):
    frame = simulate(config).telemetry.copy()
    if corruption == "leak":
        frame["incident_type"] = "memory_leak"
    elif corruption == "nan":
        frame.loc[0, "request_rate_rps"] = np.nan
    elif corruption == "range":
        frame.loc[0, "error_rate"] = 1.1
    elif corruption == "p95":
        frame.loc[0, "latency_p95_ms"] = 0
    elif corruption == "duplicate":
        frame = pd.concat([frame, frame.iloc[:1]])
    else:
        frame = frame.iloc[::-1]
    with pytest.raises(ValueError):
        validate_telemetry(frame)


def test_subminute_sampling(config):
    result = simulate(replace(config, interval_seconds=30))
    assert len(result.telemetry) == 720
    assert result.labels.incident_within_horizon.isna().sum() == 40
