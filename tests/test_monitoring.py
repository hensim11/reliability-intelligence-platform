"""Batch D contracts, including real PostgreSQL transactions and immutable snapshots."""

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
import sqlalchemy as sa
from test_serving import T, history

from reliability_intelligence.external import (
    features,
    partitions,
    step_metrics,
    targets,
    validate_dataset,
)
from reliability_intelligence.features import FEATURE_NAMES
from reliability_intelligence.monitoring.outcomes import (
    covered,
    delayed_labels,
    import_outcomes,
    metrics,
)
from reliability_intelligence.monitoring.reference import (
    DriftConfig,
    distribution,
    drift,
    seal,
    status,
    verify,
)
from reliability_intelligence.monitoring.schema import incident_starts, snapshots
from reliability_intelligence.monitoring.snapshots import (
    create_snapshot,
)
from reliability_intelligence.monitoring.snapshots import (
    history as snapshot_history,
)
from reliability_intelligence.serving.repository import DomainError

pytest_plugins = ["test_serving"]


@pytest.mark.parametrize(
    "value,expected",
    [(0.099999, "stable"), (0.1, "warning"), (0.249999, "warning"), (0.25, "severe")],
)
def test_threshold_boundaries(value, expected):
    assert status(value, DriftConfig()) == expected


@pytest.mark.parametrize(
    "values,expected",
    [
        ([], "insufficient"),
        ([1], "insufficient"),
        ([np.nan] * 100, "invalid"),
        ([np.inf] * 100, "invalid"),
        ([1] * 100, "stable"),
        ([2] * 100, "severe"),
    ],
)
def test_constant_empty_and_shift(values, expected):
    reference = distribution([1] * 100, 10)
    result = drift(values, reference, DriftConfig())
    assert result["status"] == expected
    if expected == "stable":
        assert result["psi"] == 0


def test_distribution_and_integrity():
    x = np.arange(100.0)
    assert distribution(x, 10) == distribution(x, 10)
    assert drift(x, distribution(x, 10), DriftConfig())["psi"] == 0
    with pytest.raises(ValueError):
        distribution([np.inf], 10)
    value = seal({"a": 1})
    verify(value)
    value["a"] = 2
    with pytest.raises(ValueError):
        verify(value)
    with pytest.raises(ValueError):
        DriftConfig(warning=1, severe=0.5).checked()


@pytest.mark.parametrize(
    "intervals,expected",
    [
        ([(0, 5), (5, 10)], True),
        ([(0, 4), (5, 10)], False),
        ([(1, 10)], False),
        ([(0, 11)], True),
        ([], False),
        ([(-1, 5), (2, 10)], True),
    ],
)
def test_coverage_union(intervals, expected):
    assert covered(0, 10, intervals) is expected


@pytest.mark.parametrize("offset,target", [(0, 0), (1, 1), (10, 1), (11, 0)])
def test_exact_delayed_boundaries(offset, target):
    row = {"service_id": "api-gateway", "timestamp": T, "produced_at": T, "probability": 0.8}
    coverage = [
        {
            "service_id": "api-gateway",
            "start": T,
            "end": T + timedelta(minutes=10),
            "recorded_at": T,
        }
    ]
    incident = {
        "service_id": "api-gateway",
        "start": T + timedelta(minutes=offset),
        "recorded_at": T,
    }
    eligible, _ = delayed_labels([row], [incident], coverage, T + timedelta(minutes=10))
    assert eligible[0]["target"] == target
    assert delayed_labels([row], [incident], [], T + timedelta(minutes=10))[1]["uncertified"] == 1
    assert delayed_labels([row], [incident], coverage, T + timedelta(minutes=9))[1]["immature"] == 1
    coverage[0]["recorded_at"] = T + timedelta(minutes=11)
    assert (
        delayed_labels([row], [incident], coverage, T + timedelta(minutes=10))[1]["uncertified"]
        == 1
    )


def test_undefined_metrics():
    result = metrics([], [])
    assert result["average_precision"] is None
    assert result["incident_detection_rate"] is None
    assert result["precision"] is None
    assert result["brier"] is None


def test_external_boundaries_and_no_label_features():
    labels = np.zeros(100)
    labels[20:24] = 1
    labels[50] = 1
    y, starts = targets(labels)
    assert starts.tolist() == [20, 50]
    assert y[10] == 1 and y[20] == 0 and y[9] == 0
    assert np.isnan(y[-10:]).all()
    values = np.ones((100, 38))
    x = features(values)
    assert x.shape == (100, 76) and np.isfinite(x[14:]).all()
    values[50:] = 100
    assert np.array_equal(features(values)[:50], x[:50], equal_nan=True)
    masks = partitions(1000)
    for mask, left, right in zip(masks.values(), (0, 500, 700), (500, 700, 1000), strict=True):
        index = np.flatnonzero(mask)
        assert (index - 15 >= left).all() and (index + 10 < right).all()
    result = step_metrics(np.arange(10, 20), np.ones(10), np.ones(10), np.array([20]))
    assert result["mean_lead_steps"] == 10 and result["alert_row_fraction"] == 1


def test_external_inventory(tmp_path):
    for folder in ("train", "test", "test_label"):
        (tmp_path / folder).mkdir()
        np.savetxt(
            tmp_path / folder / "machine-1-1.txt",
            np.zeros((50, 1 if folder == "test_label" else 38)),
            delimiter=",",
        )
    inventory, _ = validate_dataset(tmp_path, ("machine-1-1",))
    assert len(inventory) == 3
    with pytest.raises(ValueError):
        validate_dataset(tmp_path)
    (tmp_path / "test_label/machine-1-1.txt").write_text("2\n" * 50)
    with pytest.raises(ValueError):
        validate_dataset(tmp_path, ("machine-1-1",))


def test_application_metrics(client):
    assert client.get("/health/ready").status_code == 200
    assert client.get("/unknown/1234").status_code == 404
    assert client.get("/monitoring/drift").json() == []
    assert (
        client.post(
            "/predictions", json={"service_id": "api-gateway", "timestamp": T.isoformat()}
        ).status_code
        == 422
    )
    assert client.post("/telemetry", json={"samples": history()}).status_code == 200
    for expected in (201, 200):
        assert (
            client.post(
                "/predictions", json={"service_id": "api-gateway", "timestamp": T.isoformat()}
            ).status_code
            == expected
        )
    text = client.get("/metrics").text
    assert 'route="unmatched"' in text and "/unknown/1234" not in text
    assert 'route="/monitoring/{kind}"' in text
    assert 'rip_predictions_total{outcome="incomplete_history"} 1.0' in text
    assert 'rip_predictions_total{outcome="reused"} 1.0' in text
    assert "rip_ready 1.0" in text


def test_outcomes_transaction_and_immutability(db):
    incident = {"source_id": "i1", "service_id": "api-gateway", "start": T}
    certificate = {
        "source_id": "c1",
        "service_id": "api-gateway",
        "start": T - timedelta(minutes=20),
        "end": T + timedelta(minutes=20),
    }
    payload = {"incidents": [incident], "coverage": [certificate]}
    assert import_outcomes(db, payload) == {"inserted": 2, "unchanged": 0}
    assert import_outcomes(db, payload) == {"inserted": 0, "unchanged": 2}
    with pytest.raises(ValueError):
        import_outcomes(db, {"incidents": [{**incident, "source_id": "late"}]})
    with pytest.raises(DomainError):
        import_outcomes(db, {"incidents": [{**incident, "start": T - timedelta(minutes=30)}]})
    with pytest.raises(sa.exc.DBAPIError), db.begin() as connection:
        connection.execute(incident_starts.update().values(source_id="changed"))
    with pytest.raises(ValueError):
        import_outcomes(
            db,
            {
                "incidents": [
                    {**incident, "source_id": "new", "start": T - timedelta(minutes=30)},
                    {**incident, "source_id": "future", "start": datetime(2100, 1, 1, tzinfo=UTC)},
                ]
            },
        )
    with db.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(incident_starts)) == 1


def test_durable_snapshot_idempotency_and_delayed(client):
    client.post("/telemetry", json={"samples": history()})
    saved = client.post(
        "/predictions", json={"service_id": "api-gateway", "timestamp": T.isoformat()}
    ).json()
    repo = client.app.state.repository
    reference = seal(
        {
            "model_id": repo.artifact.metadata["id"],
            "config": DriftConfig().model_dump(),
            "distributions": {
                name: distribution([1] * 100, 10) for name in (*FEATURE_NAMES, "probability")
            },
        }
    )
    with repo.engine.connect() as connection:
        now = connection.scalar(sa.text("SELECT clock_timestamp()"))
    first = create_snapshot(repo, "drift", T, T + timedelta(minutes=1), now, reference)
    second = create_snapshot(repo, "drift", T, T + timedelta(minutes=1), now, reference)
    assert first == second
    assert first["results"]["feature_samples"] == 1
    assert first["results"]["services"]["api-gateway"]["missing_minutes"] == 0
    assert (
        create_snapshot(repo, "delayed", T, T + timedelta(minutes=1), now)["status"]
        == "insufficient"
    )
    import_outcomes(
        repo.engine,
        {
            "incidents": [
                {"source_id": "i", "service_id": "api-gateway", "start": T + timedelta(minutes=10)}
            ],
            "coverage": [
                {
                    "source_id": "c",
                    "service_id": "api-gateway",
                    "start": T,
                    "end": T + timedelta(minutes=10),
                }
            ],
        },
    )
    with repo.engine.connect() as connection:
        later = connection.scalar(sa.text("SELECT clock_timestamp()"))
    result = create_snapshot(repo, "delayed", T, T + timedelta(minutes=1), later)
    assert result["results"]["metrics"]["positives"] == 1
    assert (
        client.post(
            "/predictions", json={"service_id": "api-gateway", "timestamp": T.isoformat()}
        ).json()
        == saved
    )
    assert len(snapshot_history(repo.engine, "delayed")) == 2
    with pytest.raises(sa.exc.DBAPIError), repo.engine.begin() as connection:
        connection.execute(snapshots.delete())


@pytest.mark.parametrize("corrupt", [None, "hash", "heldout", "boundary"])
def test_reference_training_provenance(artifact_dir, tmp_path_factory, corrupt):
    tmp_path = tmp_path_factory.mktemp("reference-test")
    import json
    from dataclasses import replace

    import pandas as pd
    from test_serving import rehash

    from reliability_intelligence.config import SimulationConfig
    from reliability_intelligence.features import build_features
    from reliability_intelligence.monitoring.reference import generate_reference, load_reference
    from reliability_intelligence.serving.artifact import load_artifact
    from reliability_intelligence.simulation.engine import simulate
    from reliability_intelligence.storage import write_dataset

    config = replace(
        SimulationConfig.load("configs/batch_a.json"), duration_minutes=120, incidents=()
    )
    corpus = tmp_path / "corpus"
    source = write_dataset(simulate(config), config, corpus / "development-42")
    frame = build_features(simulate(config).telemetry, coverage_start=pd.Timestamp(config.start))
    assignments = frame[["timestamp", "service_id"]].copy()
    assignments["run_id"] = "development-42"
    assignments["partition"] = np.where(
        assignments.timestamp < pd.Timestamp(config.start) + timedelta(minutes=49),
        "train",
        "validation",
    )
    if corrupt == "heldout":
        assignments.loc[assignments.partition == "train", "run_id"] = "heldout_seed-42"
    if corrupt == "boundary":
        assignments.loc[assignments.timestamp == assignments.timestamp.max(), "partition"] = "train"
    assignments.to_parquet(artifact_dir / "assignments.parquet")
    (artifact_dir / "corpus_manifests.json").write_text(json.dumps({"development-42": source}))
    (artifact_dir / "config.json").write_text(
        json.dumps(
            {
                "simulation": config.to_dict(),
                "development_seeds": [42],
                "boundaries_minutes": [0, 60, 80, 100, 120],
            }
        )
    )
    rehash(artifact_dir)
    if corrupt == "hash":
        (artifact_dir / "assignments.parquet").write_bytes(b"bad")
    if corrupt:
        with pytest.raises(ValueError):
            generate_reference(artifact_dir, corpus, tmp_path / "ref")
    else:
        first = generate_reference(artifact_dir, corpus, tmp_path / "ref")
        second = generate_reference(artifact_dir, corpus, tmp_path / "ref2")
        assert first == second
        assert first["training_rows"] == int((assignments.partition == "train").sum())
        assert load_reference(tmp_path / "ref", load_artifact(artifact_dir).metadata["id"]) == first
        with pytest.raises(FileExistsError):
            generate_reference(artifact_dir, corpus, tmp_path / "ref")
        with pytest.raises(ValueError):
            load_reference(tmp_path / "ref", "wrong-model")


@pytest.mark.parametrize("mode", ["corrupt", "incompatible"])
def test_reference_startup_failure(db, artifact_dir, tmp_path_factory, mode):
    import json
    import os

    from fastapi.testclient import TestClient

    from reliability_intelligence.monitoring.reference import publish
    from reliability_intelligence.serving.api import create_app
    from reliability_intelligence.serving.contracts import Settings

    directory = tmp_path_factory.mktemp("bad-reference") / "published"
    reference = seal({"schema_version": "wrong-version", "model_id": "wrong"})
    publish(directory, {"reference.json": reference})
    if mode == "corrupt":
        (directory / "reference.json").write_text(json.dumps({"tampered": True}))
    settings = Settings(
        database_url=os.environ["RIP_TEST_DATABASE_URL"],
        model_directory=artifact_dir,
        monitoring_reference=directory,
    )
    with TestClient(create_app(settings)) as app:
        assert app.get("/health/live").status_code == 200
        response = app.get("/health/ready")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "reference_unready"
        assert app.get("/metrics").status_code == 200
