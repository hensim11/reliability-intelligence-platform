import json
import shutil
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from reliability_intelligence.cli import main
from reliability_intelligence.config import INCIDENT_TYPES, IncidentSpec, SimulationConfig
from reliability_intelligence.evidence import generate_evidence
from reliability_intelligence.labels import future_labels
from reliability_intelligence.simulation.engine import simulate
from reliability_intelligence.storage import file_hash, read_dataset, write_dataset


def copy_and_mutate_table(source: Path, target: Path, table: str, mutate) -> Path:
    """Alter a Parquet table and refresh its hash so semantic validation is exercised."""
    shutil.copytree(source, target)
    table_path = target / f"{table}.parquet"
    frame = pd.read_parquet(table_path)
    mutate(frame)
    frame.to_parquet(table_path, index=False)
    manifest_path = target / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["sha256"][table_path.name] = file_hash(table_path)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return target


def rewrite_telemetry_and_labels(bundle: Path, telemetry: pd.DataFrame) -> None:
    """Recompute derived labels for altered telemetry and refresh bundle bookkeeping."""
    config = SimulationConfig.load(bundle / "config.json")
    incidents = pd.read_parquet(bundle / "incidents.parquet")
    coverage_start = pd.Timestamp(config.start)
    coverage_end = coverage_start + pd.Timedelta(minutes=config.duration_minutes)
    labels = future_labels(
        telemetry,
        incidents,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        horizon_minutes=config.horizon_minutes,
        observation_minutes=config.observation_minutes,
        interval_seconds=config.interval_seconds,
    )
    telemetry_path = bundle / "telemetry.parquet"
    labels_path = bundle / "labels.parquet"
    telemetry.to_parquet(telemetry_path, index=False)
    labels.to_parquet(labels_path, index=False)
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for table, path, frame in (
        ("telemetry", telemetry_path, telemetry),
        ("labels", labels_path, labels),
    ):
        manifest["rows"][table] = len(frame)
        manifest["sha256"][path.name] = file_hash(path)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")


@pytest.fixture
def semantic_bundle(config, tmp_path):
    events = (
        IncidentSpec(config.services[0].name, "memory_leak", 20),
        IncidentSpec(config.services[0].name, "cpu_saturation", 105),
    )
    configured = replace(config, incidents=events)
    output = tmp_path / "valid"
    write_dataset(simulate(configured), configured, output)
    return output


def test_bundle_roundtrip_and_integrity(config, tmp_path):
    config = replace(config, incidents=(IncidentSpec(config.services[0].name, "memory_leak", 30),))
    result = simulate(config)
    output = tmp_path / "run"
    manifest = write_dataset(result, config, output)
    loaded, loaded_manifest = read_dataset(output)
    assert manifest == loaded_manifest
    for name in ("telemetry", "incidents", "labels"):
        pd.testing.assert_frame_equal(getattr(result, name), getattr(loaded, name))
    with pytest.raises(FileExistsError):
        write_dataset(result, config, output)
    with (output / "telemetry.parquet").open("ab") as handle:
        handle.write(b"corruption")
    with pytest.raises(ValueError, match="integrity"):
        read_dataset(output)


def test_cli_and_evidence_for_all_scenarios(config, tmp_path, capsys):
    events = tuple(
        IncidentSpec(config.services[0].name, kind, 30 + index * 110)
        for index, kind in enumerate(INCIDENT_TYPES)
    )
    config = replace(config, duration_minutes=480, incidents=events)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config.to_dict()))
    output = tmp_path / "dataset"
    assert main(["generate", "--config", str(path), "--output", str(output)]) == 0
    log = json.loads(capsys.readouterr().err)
    assert log["event"] == "dataset_written"
    evidence = tmp_path / "evidence"
    assert main(["evidence", "--dataset", str(output), "--output", str(evidence)]) == 0
    summary = json.loads((evidence / "summary.json").read_text())
    assert summary["labels"]["positive"] == 40
    assert summary["labels"]["unknown"] == 20
    for name in ["normal", "overview", "correlations", *INCIDENT_TYPES]:
        assert (evidence / f"{name}.png").stat().st_size > 1000
    assert (evidence / "REPORT.md").exists()
    assert main(["generate", "--config", str(path), "--output", str(output)]) == 1


def test_empty_incidents_and_censored_evidence(config, tmp_path):
    config = replace(config, duration_minutes=5)
    output = tmp_path / "dataset"
    write_dataset(simulate(config), config, output)
    summary = generate_evidence(output, tmp_path / "evidence")
    assert summary["incidents"] == 0
    assert summary["labels"]["positive_fraction_observed"] is None
    assert summary["labels"]["eligible_rows"] == 0
    read_dataset(output)


def test_rejects_out_of_domain_target_after_hash_refresh(semantic_bundle, tmp_path):
    corrupted = copy_and_mutate_table(
        semantic_bundle,
        tmp_path / "target-two",
        "labels",
        lambda frame: frame.__setitem__(
            "incident_within_horizon",
            frame.incident_within_horizon.mask(frame.index == 0, 2),
        ),
    )
    with pytest.raises(ValueError, match="0, 1, or null"):
        read_dataset(corrupted)


@pytest.mark.parametrize("source_value,replacement", [(1, 0), (0, 1)])
def test_rejects_semantically_incorrect_target(
    semantic_bundle, tmp_path, source_value, replacement
):
    def mutate(frame):
        index = frame.index[frame.incident_within_horizon == source_value][0]
        frame.loc[index, "incident_within_horizon"] = replacement

    corrupted = copy_and_mutate_table(
        semantic_bundle, tmp_path / f"wrong-{source_value}", "labels", mutate
    )
    with pytest.raises(ValueError, match="incident_within_horizon is inconsistent"):
        read_dataset(corrupted)


@pytest.mark.parametrize("complete", [True, False])
def test_rejects_target_nullability_horizon_mismatch(semantic_bundle, tmp_path, complete):
    def mutate(frame):
        index = frame.index[frame.horizon_complete == complete][0]
        if complete:
            frame.loc[index, "incident_within_horizon"] = pd.NA
        else:
            frame.loc[index, "incident_within_horizon"] = 0

    corrupted = copy_and_mutate_table(
        semantic_bundle, tmp_path / f"nullability-{complete}", "labels", mutate
    )
    message = "must not be null" if complete else "must be null"
    with pytest.raises(ValueError, match=message):
        read_dataset(corrupted)


def test_rejects_invalid_incident_type(semantic_bundle, tmp_path):
    corrupted = copy_and_mutate_table(
        semantic_bundle,
        tmp_path / "bad-type",
        "incidents",
        lambda frame: frame.__setitem__(
            "incident_type", frame.incident_type.mask(frame.index == 0, "disk_fire")
        ),
    )
    with pytest.raises(ValueError, match="type is not supported"):
        read_dataset(corrupted)


def test_rejects_unknown_incident_service(semantic_bundle, tmp_path):
    corrupted = copy_and_mutate_table(
        semantic_bundle,
        tmp_path / "bad-service",
        "incidents",
        lambda frame: frame.__setitem__(
            "service_id", frame.service_id.mask(frame.index == 0, "unknown")
        ),
    )
    with pytest.raises(ValueError, match="absent from configuration"):
        read_dataset(corrupted)


def test_rejects_invalid_lifecycle_order(semantic_bundle, tmp_path):
    def mutate(frame):
        frame.loc[0, "incident_start"] = frame.loc[0, "precursor_start"]

    corrupted = copy_and_mutate_table(semantic_bundle, tmp_path / "bad-order", "incidents", mutate)
    with pytest.raises(ValueError, match="strictly ordered"):
        read_dataset(corrupted)


def test_rejects_overlapping_incidents(semantic_bundle, tmp_path):
    def mutate(frame):
        duration = frame.loc[1, "recovery_end"] - frame.loc[1, "precursor_start"]
        frame.loc[1, "precursor_start"] = frame.loc[0, "incident_start"]
        frame.loc[1, "incident_start"] = frame.loc[1, "precursor_start"] + pd.Timedelta(minutes=25)
        frame.loc[1, "incident_end"] = frame.loc[1, "incident_start"] + pd.Timedelta(minutes=30)
        frame.loc[1, "recovery_end"] = frame.loc[1, "precursor_start"] + duration

    corrupted = copy_and_mutate_table(semantic_bundle, tmp_path / "overlap", "incidents", mutate)
    with pytest.raises(ValueError, match="overlap"):
        read_dataset(corrupted)


def test_rejects_manifest_config_coverage_disagreement(semantic_bundle, tmp_path):
    corrupted = tmp_path / "coverage"
    shutil.copytree(semantic_bundle, corrupted)
    manifest_path = corrupted / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["coverage_end_exclusive"] = "2026-01-05T04:00:00+00:00"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    with pytest.raises(ValueError, match="coverage disagrees"):
        read_dataset(corrupted)


@pytest.mark.parametrize(
    "table,operation",
    [
        ("labels", "missing"),
        ("labels", "unexpected"),
        ("incidents", "missing"),
        ("incidents", "unexpected"),
    ],
)
def test_rejects_incorrect_semantic_columns(semantic_bundle, tmp_path, table, operation):
    def mutate(frame):
        if operation == "missing":
            frame.drop(columns=frame.columns[-1], inplace=True)
        else:
            frame["unexpected"] = 1

    corrupted = copy_and_mutate_table(
        semantic_bundle, tmp_path / f"{table}-{operation}", table, mutate
    )
    with pytest.raises(ValueError, match="columns must match"):
        read_dataset(corrupted)


def test_read_dataset_rejects_recomputed_bundle_with_missing_grid_member(semantic_bundle, tmp_path):
    """A missing raw key fails even after derived labels are made internally consistent."""
    corrupted = tmp_path / "missing-grid-point"
    shutil.copytree(semantic_bundle, corrupted)
    telemetry_path = corrupted / "telemetry.parquet"
    telemetry = pd.read_parquet(telemetry_path)
    service = telemetry.service_id.iloc[0]
    missing_timestamp = telemetry.timestamp.min() + pd.Timedelta(minutes=5)
    missing_key = (telemetry.service_id == service) & (telemetry.timestamp == missing_timestamp)
    telemetry = telemetry.loc[~missing_key].reset_index(drop=True)
    rewrite_telemetry_and_labels(corrupted, telemetry)

    with pytest.raises(ValueError, match=r"missing 1 expected key\(s\); unexpected 0"):
        read_dataset(corrupted)


def test_grid_identity_rejects_missing_key_with_preserved_row_count(semantic_bundle, tmp_path):
    corrupted = tmp_path / "same-count-grid-corruption"
    shutil.copytree(semantic_bundle, corrupted)
    telemetry = pd.read_parquet(corrupted / "telemetry.parquet")
    telemetry = telemetry.drop(index=10).reset_index(drop=True)
    off_grid = telemetry.iloc[[0]].copy()
    off_grid["timestamp"] = telemetry.timestamp.min() + pd.Timedelta(seconds=30)
    telemetry = pd.concat([telemetry, off_grid], ignore_index=True).sort_values(
        ["timestamp", "service_id"], ignore_index=True
    )
    rewrite_telemetry_and_labels(corrupted, telemetry)

    with pytest.raises(ValueError, match=r"missing 1 expected key\(s\); unexpected 1 key\(s\)"):
        read_dataset(corrupted)


def test_bundle_rejects_duplicate_telemetry_key(semantic_bundle, tmp_path):
    corrupted = tmp_path / "duplicate-key"
    shutil.copytree(semantic_bundle, corrupted)
    telemetry = pd.read_parquet(corrupted / "telemetry.parquet")
    telemetry = pd.concat([telemetry, telemetry.iloc[[0]]], ignore_index=True).sort_values(
        ["timestamp", "service_id"], ignore_index=True
    )
    rewrite_telemetry_and_labels(corrupted, telemetry)

    with pytest.raises(ValueError, match="Duplicate service/timestamp keys"):
        read_dataset(corrupted)


def test_bundle_rejects_unexpected_off_grid_timestamp(semantic_bundle, tmp_path):
    corrupted = tmp_path / "off-grid-key"
    shutil.copytree(semantic_bundle, corrupted)
    telemetry = pd.read_parquet(corrupted / "telemetry.parquet")
    off_grid = telemetry.iloc[[0]].copy()
    off_grid["timestamp"] = telemetry.timestamp.min() + pd.Timedelta(seconds=30)
    telemetry = pd.concat([telemetry, off_grid], ignore_index=True).sort_values(
        ["timestamp", "service_id"], ignore_index=True
    )
    rewrite_telemetry_and_labels(corrupted, telemetry)

    with pytest.raises(ValueError, match=r"unexpected 1 key\(s\)"):
        read_dataset(corrupted)


def test_bundle_rejects_noncanonical_telemetry_order(semantic_bundle, tmp_path):
    corrupted = tmp_path / "wrong-order"
    shutil.copytree(semantic_bundle, corrupted)
    telemetry = pd.read_parquet(corrupted / "telemetry.parquet")
    telemetry = pd.concat(
        [telemetry.iloc[[1]], telemetry.iloc[[0]], telemetry.iloc[2:]], ignore_index=True
    )
    rewrite_telemetry_and_labels(corrupted, telemetry)

    with pytest.raises(ValueError, match="canonical timestamp/service ordering"):
        read_dataset(corrupted)


def test_bundle_grid_uses_configured_subminute_interval(config, tmp_path):
    configured = replace(config, interval_seconds=30)
    output = tmp_path / "thirty-second-grid"
    write_dataset(simulate(configured), configured, output)
    loaded, _ = read_dataset(output)
    expected_rows = (
        configured.duration_minutes * 60 // configured.interval_seconds * len(configured.services)
    )
    assert len(loaded.telemetry) == expected_rows
