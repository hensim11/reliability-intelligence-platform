from dataclasses import replace

import pytest

from reliability_intelligence.config import SimulationConfig


@pytest.fixture
def config():
    base = SimulationConfig.load("configs/batch_a.json")
    return replace(base, duration_minutes=180, incidents=(), services=base.services[:2])
