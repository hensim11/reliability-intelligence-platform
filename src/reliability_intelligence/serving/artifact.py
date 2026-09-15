"""Validate a trusted-local frozen Batch B experiment before executable deserialisation."""

import hashlib
import importlib.metadata
import json
import platform
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from reliability_intelligence.features import FEATURE_NAMES, FEATURE_VERSION
from reliability_intelligence.models import ForecastModel, load_model
from reliability_intelligence.serving.contracts import SERVICES
from reliability_intelligence.storage import file_hash

REFERENCE_NAME = "boosting_raw"
REFERENCE_THRESHOLD = 0.5700000000000001


@dataclass(frozen=True)
class Artifact:
    model: ForecastModel
    metadata: dict


def load_artifact(directory: Path) -> Artifact:
    names = [
        "boosting_raw.joblib",
        "boosting_raw.json",
        "selection.json",
        "feature_schema.json",
        "environment.json",
        "config.json",
    ]
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest["schema_version"] != "batch-b-1.0":
        raise ValueError("Unsupported experiment manifest")
    hashes = {}
    for name in names:
        hashes[name] = file_hash(directory / name)
        if hashes[name] != manifest["sha256"][name]:
            raise ValueError(f"Experiment integrity mismatch: {name}")
    selection = json.loads((directory / "selection.json").read_text())
    if selection["candidate"] != REFERENCE_NAME or selection["threshold"] != REFERENCE_THRESHOLD:
        raise ValueError("Only the frozen Batch B reference is supported")
    schema = json.loads((directory / "feature_schema.json").read_text())
    if schema != {"version": FEATURE_VERSION, "names": list(FEATURE_NAMES), "dtype": "float64"}:
        raise ValueError("Incompatible feature schema")
    environment = json.loads((directory / "environment.json").read_text())
    if environment["python"].split(".")[:2] != platform.python_version().split(".")[:2]:
        raise ValueError("Incompatible Python runtime")
    for dependency in ("numpy", "pandas", "scikit-learn", "scipy", "joblib", "threadpoolctl"):
        if environment["dependencies"][dependency] != importlib.metadata.version(dependency):
            raise ValueError(f"Incompatible runtime dependency: {dependency}")
    config = json.loads((directory / "config.json").read_text())["simulation"]
    if (
        config["observation_minutes"] != 15
        or config["horizon_minutes"] != 10
        or config["interval_seconds"] != 60
        or {service["name"] for service in config["services"]} != set(SERVICES)
    ):
        raise ValueError("Incompatible prediction configuration")
    model = load_model(directory / "boosting_raw.joblib")
    probe = model.predict(pd.DataFrame(np.zeros((1, len(FEATURE_NAMES))), columns=FEATURE_NAMES))
    if np.shape(probe) != (1,) or not np.isfinite(probe).all() or not 0 <= probe[0] <= 1:
        raise ValueError("Model failed inference readiness probe")
    identity = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    return Artifact(
        model,
        {
            "id": identity,
            "name": model.name,
            "sha256": hashes["boosting_raw.joblib"],
            "feature_version": FEATURE_VERSION,
            "threshold": REFERENCE_THRESHOLD,
            "artifact_hashes": hashes,
            "runtime": {
                "python": environment["python"],
                "dependencies": environment["dependencies"],
            },
        },
    )
