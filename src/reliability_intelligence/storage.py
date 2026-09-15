"""Atomic local Parquet bundles with configuration, schema version and integrity hashes."""

import hashlib
import importlib.metadata
import json
import platform
import shutil
import tempfile
from pathlib import Path

import pandas as pd

from reliability_intelligence import __version__
from reliability_intelligence.config import SimulationConfig
from reliability_intelligence.schemas import (
    validate_incidents,
    validate_labels,
    validate_telemetry,
    validate_telemetry_grid,
)
from reliability_intelligence.simulation.engine import SimulationResult

TABLES = ("telemetry", "incidents", "labels")


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_dataset(result: SimulationResult, config: SimulationConfig, output: Path) -> dict:
    """Never overwrite a previous run. Publish a complete directory via an atomic rename."""
    output = Path(output)
    if output.exists():
        raise FileExistsError(f"Output exists: {output}; choose a new run directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        for name in TABLES:
            getattr(result, name).to_parquet(staging / f"{name}.parquet", index=False)
        (staging / "config.json").write_text(json.dumps(config.to_dict(), indent=2) + "\n")
        manifest = {
            "schema_version": "1.0",
            "package_version": __version__,
            "synthetic": True,
            "python_version": platform.python_version(),
            "dependencies": {
                name: importlib.metadata.version(name)
                for name in ("numpy", "pandas", "pyarrow", "matplotlib")
            },
            "coverage_start": config.to_dict()["start_time"],
            "coverage_end_exclusive": (
                pd.Timestamp(config.start) + pd.Timedelta(minutes=config.duration_minutes)
            ).isoformat(),
            "rows": {name: len(getattr(result, name)) for name in TABLES},
            "sha256": {
                name: file_hash(staging / name)
                for name in [*(f"{table}.parquet" for table in TABLES), "config.json"]
            },
        }
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        # Recheck immediately before rename; concurrent writers to one path are unsupported.
        if output.exists():
            raise FileExistsError(f"Output appeared during generation: {output}")
        staging.rename(output)
        return manifest
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def read_dataset(path: Path) -> tuple[SimulationResult, dict]:
    path = Path(path)
    manifest = json.loads((path / "manifest.json").read_text())
    if manifest["schema_version"] != "1.0":
        raise ValueError("Unsupported dataset schema")
    expected = {*(f"{table}.parquet" for table in TABLES), "config.json"}
    if set(manifest["sha256"]) != expected:
        raise ValueError("Manifest must cover exactly the dataset files")
    for name, digest in manifest["sha256"].items():
        if file_hash(path / name) != digest:
            raise ValueError(f"Dataset integrity check failed: {name}")
    try:
        config = SimulationConfig.load(path / "config.json")
        coverage_start = pd.Timestamp(manifest["coverage_start"])
        coverage_end = pd.Timestamp(manifest["coverage_end_exclusive"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("Dataset configuration or manifest coverage is invalid") from error
    expected_start = pd.Timestamp(config.start)
    expected_end = expected_start + pd.Timedelta(minutes=config.duration_minutes)
    if coverage_start != expected_start or coverage_end != expected_end:
        raise ValueError("Manifest coverage disagrees with resolved configuration")
    if coverage_start.tz is None or coverage_end.tz is None:
        raise ValueError("Manifest coverage must be timezone aware")
    if str(coverage_start.tz) != "UTC" or str(coverage_end.tz) != "UTC":
        raise ValueError("Manifest coverage must use UTC")
    result = SimulationResult(
        **{name: pd.read_parquet(path / f"{name}.parquet") for name in TABLES}
    )
    validate_telemetry(result.telemetry)
    for name in TABLES:
        if len(getattr(result, name)) != manifest["rows"][name]:
            raise ValueError(f"Manifest row count mismatch: {name}")
    validate_telemetry_grid(result.telemetry, config)
    configured_services = {service.name for service in config.services}
    if set(result.telemetry.service_id) != configured_services:
        raise ValueError("Telemetry services disagree with resolved configuration")
    validate_incidents(
        result.incidents,
        configured_services=configured_services,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
    )
    validate_labels(
        result.labels,
        result.telemetry,
        result.incidents,
        config=config,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
    )
    return result, manifest
