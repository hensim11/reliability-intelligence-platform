"""Training-only, content-addressed monitoring references; no fitting or selection."""

import hashlib
import json
import shutil
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from pydantic import Field

from reliability_intelligence.config import SimulationConfig
from reliability_intelligence.experiment import verify_experiment
from reliability_intelligence.features import (
    FEATURE_NAMES,
    FEATURE_VERSION,
    build_features,
    partition_mask,
)
from reliability_intelligence.serving.artifact import load_artifact
from reliability_intelligence.serving.contracts import StrictModel
from reliability_intelligence.storage import file_hash, read_dataset


class DriftConfig(StrictModel):
    bins: int = Field(10, ge=2, le=100, strict=True)
    minimum_samples: int = Field(100, ge=2, le=100000, strict=True)
    smoothing: float = Field(0.0001, gt=0, le=0.01, allow_inf_nan=False)
    warning: float = Field(0.1, gt=0, allow_inf_nan=False)
    severe: float = Field(0.25, gt=0, allow_inf_nan=False)

    def checked(self):
        if self.warning >= self.severe:
            raise ValueError("warning must be below severe")
        return self


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def seal(value):
    return {**value, "sha256": digest(value)}


def verify(value):
    body = {k: v for k, v in value.items() if k != "sha256"}
    if value.get("sha256") != digest(body):
        raise ValueError("Manifest integrity mismatch")
    return body


def publish(output, files):
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        for name, value in files.items():
            if isinstance(value, bytes):
                (staging / name).write_bytes(value)
            elif isinstance(value, str):
                (staging / name).write_text(value)
            else:
                (staging / name).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
        (staging / "manifest.json").write_text(
            json.dumps(
                seal(
                    {
                        "schema_version": "batch-d-1",
                        "files": {name: file_hash(staging / name) for name in sorted(files)},
                    }
                ),
                indent=2,
            )
            + "\n"
        )
        if output.exists():
            raise FileExistsError(output)
        staging.rename(output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def distribution(values, bins):
    x = np.asarray(values, dtype=float)
    if not len(x) or not np.isfinite(x).all():
        raise ValueError("Reference requires finite nonempty values")
    # Interior quantiles plus extrema preserve out-of-range sensitivity, even for constants.
    edges = np.unique(np.quantile(x, np.linspace(0, 1, bins + 1)))
    upper = np.nextafter(edges[-1], np.inf)
    if not np.isfinite(upper):
        raise ValueError("Reference maximum cannot be bounded")
    edges = np.append(edges, upper)
    counts = np.bincount(np.searchsorted(edges, x, side="right"), minlength=len(edges) + 1)
    return {"edges": edges.tolist(), "expected": (counts / len(x)).tolist(), "samples": len(x)}


def status(psi, config):
    return "severe" if psi >= config.severe else "warning" if psi >= config.warning else "stable"


def drift(values, reference, config):
    config.checked()
    x = np.asarray(values, dtype=float)
    if not np.isfinite(x).all():
        return {"status": "invalid", "samples": len(x), "psi": None}
    if len(x) < config.minimum_samples:
        return {"status": "insufficient", "samples": len(x), "psi": None}
    actual = np.bincount(
        np.searchsorted(reference["edges"], x, side="right"), minlength=len(reference["expected"])
    ) / len(x)
    expected = np.asarray(reference["expected"])
    actual, expected = actual + config.smoothing, expected + config.smoothing
    actual, expected = actual / actual.sum(), expected / expected.sum()
    psi = float(np.sum((actual - expected) * np.log(actual / expected)))
    return {"status": status(psi, config), "samples": len(x), "psi": psi}


def generate_reference(experiment, corpus, output, config=None):
    config = (config or DriftConfig()).checked()
    manifest = verify_experiment(experiment)
    artifact = load_artifact(experiment)
    assignments = pd.read_parquet(experiment / "assignments.parquet")
    keys = ["run_id", "timestamp", "service_id"]
    if assignments.duplicated(keys).any():
        raise ValueError("Duplicate partition assignments")
    train = assignments.loc[assignments.partition == "train", keys]
    settings = json.loads((experiment / "config.json").read_text())
    sources = json.loads((experiment / "corpus_manifests.json").read_text())
    frames = []
    for run, rows in train.groupby("run_id", sort=True):
        if run not in {f"development-{seed}" for seed in settings["development_seeds"]}:
            raise ValueError("Non-development training assignment")
        result, source = read_dataset(corpus / run)
        if source != sources[run]:
            raise ValueError("Corpus differs from frozen experiment")
        simulation = SimulationConfig.load(corpus / run / "config.json")
        start = pd.Timestamp(simulation.start)
        if not partition_mask(
            rows.timestamp, start, start + pd.Timedelta(minutes=settings["boundaries_minutes"][1])
        ).all():
            raise ValueError("Training assignment escapes training region")
        features = build_features(result.telemetry, coverage_start=start)
        joined = rows.merge(features, on=["timestamp", "service_id"], validate="one_to_one")
        if len(joined) != len(rows):
            raise ValueError("Training feature keys missing")
        frames.append(joined)
    frame = pd.concat(frames).sort_values(keys)
    probability = artifact.model.predict(frame[list(FEATURE_NAMES)])
    reference = seal(
        {
            "schema_version": "monitoring-reference-1",
            "feature_version": FEATURE_VERSION,
            "model_id": artifact.metadata["id"],
            "features": list(FEATURE_NAMES),
            "config": config.model_dump(),
            "training_rows": len(frame),
            "source_hashes": {
                "experiment_manifest": file_hash(experiment / "manifest.json"),
                "assignments": manifest["sha256"]["assignments.parquet"],
                "corpus_manifests": manifest["sha256"]["corpus_manifests.json"],
            },
            "distributions": {
                **{name: distribution(frame[name], config.bins) for name in FEATURE_NAMES},
                "probability": distribution(probability, config.bins),
            },
        }
    )
    publish(output, {"reference.json": reference})
    return reference


def load_reference(directory, model_id):
    manifest = json.loads((directory / "manifest.json").read_text())
    verify(manifest)
    if manifest["files"] != {"reference.json": file_hash(directory / "reference.json")}:
        raise ValueError("Reference file hash mismatch")
    reference = json.loads((directory / "reference.json").read_text())
    verify(reference)
    if (
        reference["schema_version"] != "monitoring-reference-1"
        or reference["model_id"] != model_id
        or reference["features"] != list(FEATURE_NAMES)
        or reference["feature_version"] != FEATURE_VERSION
    ):
        raise ValueError("Incompatible monitoring reference")
    DriftConfig(**reference["config"]).checked()
    if set(reference["distributions"]) != {*FEATURE_NAMES, "probability"}:
        raise ValueError("Invalid distribution inventory")
    for value in reference["distributions"].values():
        edges, expected = np.asarray(value["edges"]), np.asarray(value["expected"])
        if (
            not np.isfinite(edges).all()
            or not (np.diff(edges) > 0).all()
            or len(expected) != len(edges) + 1
            or not np.isfinite(expected).all()
            or (expected < 0).any()
            or not np.isclose(expected.sum(), 1)
        ):
            raise ValueError("Invalid distribution")
    return reference
