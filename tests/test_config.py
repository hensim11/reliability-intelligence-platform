from dataclasses import replace

import pytest

from reliability_intelligence.config import Dynamics, IncidentSpec, ServiceProfile, SimulationConfig


def test_round_trip(config, tmp_path):
    import json

    path = tmp_path / "config.json"
    path.write_text(json.dumps(config.to_dict()))
    assert SimulationConfig.load(path) == config


@pytest.mark.parametrize(
    "changes",
    [
        {"seed": -1},
        {"seed": True},
        {"interval_seconds": 0},
        {"interval_seconds": 61},
        {"interval_seconds": 7},
        {"duration_minutes": 1.2},
        {"horizon_minutes": 12},
        {"observation_minutes": 20},
        {"start_time": "2026-01-01"},
        {"services": ()},
        {"incidents_per_service": -1},
        {"duration_minutes": float("inf")},
    ],
)
def test_invalid_config(config, changes):
    with pytest.raises(ValueError):
        replace(config, **changes)


def test_schedule_constraints(config):
    with pytest.raises(ValueError, match="too short"):
        replace(config, incidents=None, incidents_per_service=5)
    event = IncidentSpec(config.services[0].name, "memory_leak", 30)
    with pytest.raises(ValueError, match="overlap"):
        replace(config, incidents=(event, event))
    with pytest.raises(ValueError, match="unknown service"):
        replace(config, incidents=(replace(event, service_id="missing"),))
    with pytest.raises(ValueError, match="fit"):
        replace(config, incidents=(replace(event, precursor_start_minute=160),))
    with pytest.raises(ValueError, match="unique"):
        replace(config, services=(config.services[0], config.services[0]))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"severity": float("nan")},
        {"severity": 2},
        {"incident_type": "unknown"},
        {"precursor_start_minute": -1},
        {"active_minutes": 0},
        {"precursor_start_minute": True},
    ],
)
def test_invalid_incident(kwargs):
    values = {
        "service_id": "api-gateway",
        "incident_type": "memory_leak",
        "precursor_start_minute": 10,
        **kwargs,
    }
    with pytest.raises(ValueError):
        IncidentSpec(**values)


def test_unknown_configuration_field(config):
    with pytest.raises(TypeError):
        SimulationConfig.from_dict({**config.to_dict(), "sead": 10})


def test_invalid_service_and_dynamics():
    with pytest.raises(ValueError):
        ServiceProfile("", 1, 2, 3, 4, 5)
    with pytest.raises(ValueError):
        ServiceProfile("svc", 2, 1, 3, 4, 5)
    with pytest.raises(ValueError):
        Dynamics(onset_pressure=1.0)
