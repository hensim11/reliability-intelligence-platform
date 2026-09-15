"""Batch C unit and real PostgreSQL integration tests.

RIP_TEST_DATABASE_URL must name a disposable database: fixtures reset its public schema.
"""

import importlib.metadata
import json
import os
import platform
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sklearn.dummy import DummyClassifier
from sklearn.pipeline import make_pipeline

from reliability_intelligence.features import (
    FEATURE_NAMES,
    FEATURE_VERSION,
    METRICS,
    build_features,
)
from reliability_intelligence.models import ForecastModel, save_model
from reliability_intelligence.serving.analytics import coverage, risk_summary
from reliability_intelligence.serving.api import create_app
from reliability_intelligence.serving.artifact import REFERENCE_THRESHOLD, load_artifact
from reliability_intelligence.serving.contracts import Ingest, Settings, telemetry_frame
from reliability_intelligence.serving.database import make_engine, metadata, predictions, telemetry
from reliability_intelligence.serving.repository import DomainError, online_features
from reliability_intelligence.storage import file_hash

T = datetime(2025, 1, 1, 0, 15, tzinfo=UTC)


def sample(timestamp=T, service_id="api-gateway", value=10.0):
    return {
        "timestamp": timestamp.isoformat(),
        "service_id": service_id,
        **dict.fromkeys(METRICS, value),
        "error_rate": 0.01,
    }


def history(service="api-gateway", end=T):
    return [sample(end - timedelta(minutes=14 - i), service, 10.0 + i) for i in range(15)]


def rehash(path):
    hashes = {p.name: file_hash(p) for p in path.iterdir() if p.name != "manifest.json"}
    (path / "manifest.json").write_text(
        json.dumps({"schema_version": "batch-b-1.0", "sha256": hashes})
    )


@pytest.fixture
def artifact_dir(tmp_path):
    x = pd.DataFrame(np.zeros((4, 49)), columns=FEATURE_NAMES)
    model = ForecastModel(
        "boosting_raw", make_pipeline(DummyClassifier(strategy="prior").fit(x, [0, 0, 0, 1]))
    )
    save_model(model, tmp_path / "boosting_raw.joblib")
    (tmp_path / "selection.json").write_text(
        json.dumps({"candidate": "boosting_raw", "threshold": REFERENCE_THRESHOLD})
    )
    (tmp_path / "feature_schema.json").write_text(
        json.dumps({"version": FEATURE_VERSION, "names": FEATURE_NAMES, "dtype": "float64"})
    )
    (tmp_path / "environment.json").write_text(
        json.dumps(
            {
                "python": platform.python_version(),
                "dependencies": {
                    d: importlib.metadata.version(d)
                    for d in ("numpy", "pandas", "scikit-learn", "scipy", "joblib", "threadpoolctl")
                },
            }
        )
    )
    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "simulation": {
                    "observation_minutes": 15,
                    "horizon_minutes": 10,
                    "interval_seconds": 60,
                    "services": [
                        {"name": name}
                        for name in (
                            "api-gateway",
                            "auth-service",
                            "catalog-service",
                            "search-service",
                        )
                    ],
                }
            }
        )
    )
    rehash(tmp_path)
    return tmp_path


@pytest.fixture
def db():
    url = os.environ.get("RIP_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set RIP_TEST_DATABASE_URL to a disposable PostgreSQL database")
    engine = make_engine(url)
    with engine.begin() as c:
        c.execute(sa.text("DROP SCHEMA public CASCADE"))
        c.execute(sa.text("CREATE SCHEMA public"))
    config = Config("alembic.ini")
    config.attributes["database_url"] = url
    command.upgrade(config, "head")
    yield engine
    engine.dispose()


@pytest.fixture
def client(db, artifact_dir):
    settings = Settings(
        database_url=os.environ["RIP_TEST_DATABASE_URL"], model_directory=artifact_dir
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/health/ready").status_code == 200
        yield client


def test_artifact_valid(artifact_dir):
    artifact = load_artifact(artifact_dir)
    assert artifact.metadata["threshold"] == REFERENCE_THRESHOLD
    assert len(artifact.metadata["id"]) == 64


@pytest.mark.parametrize(
    "name",
    [
        "boosting_raw.joblib",
        "boosting_raw.json",
        "feature_schema.json",
        "selection.json",
        "environment.json",
        "manifest.json",
        "config.json",
    ],
)
def test_artifact_missing(artifact_dir, name):
    (artifact_dir / name).unlink()
    with pytest.raises((OSError, ValueError, KeyError)):
        load_artifact(artifact_dir)


@pytest.mark.parametrize(
    "name",
    [
        "boosting_raw.joblib",
        "boosting_raw.json",
        "feature_schema.json",
        "selection.json",
        "environment.json",
        "config.json",
    ],
)
def test_artifact_hash(artifact_dir, name):
    with (artifact_dir / name).open("ab") as f:
        f.write(b"changed")
    with pytest.raises(ValueError, match="integrity"):
        load_artifact(artifact_dir)


@pytest.mark.parametrize(
    "name,key,value",
    [
        ("feature_schema.json", "version", "9"),
        ("feature_schema.json", "names", list(reversed(FEATURE_NAMES))),
        ("feature_schema.json", "dtype", "float32"),
        ("selection.json", "threshold", 0.5),
        ("selection.json", "candidate", "logistic_raw"),
        ("environment.json", "python", "3.13.0"),
        ("environment.json", "dependencies", {"numpy": "0"}),
        ("boosting_raw.json", "sklearn_version", "0"),
        ("boosting_raw.json", "sha256", "0"),
    ],
)
def test_artifact_incompatible(artifact_dir, name, key, value):
    path = artifact_dir / name
    data = json.loads(path.read_text())
    data[key] = value
    path.write_text(json.dumps(data))
    rehash(artifact_dir)
    with pytest.raises(ValueError):
        load_artifact(artifact_dir)


def test_parity_exact():
    records = (
        [sample(T - timedelta(minutes=15), value=99)]
        + history()
        + [sample(T + timedelta(minutes=1), value=99)]
    )
    records += history("auth-service")
    frame = telemetry_frame(sorted(records, key=lambda r: (r["service_id"], r["timestamp"])))
    offline = build_features(frame, coverage_start=pd.Timestamp(T) - pd.Timedelta(minutes=15))
    expected = offline.loc[
        (offline.timestamp == T) & (offline.service_id == "api-gateway"), list(FEATURE_NAMES)
    ].reset_index(drop=True)
    online = online_features(history(), "api-gateway", T)
    pd.testing.assert_frame_equal(online, expected, check_exact=True)


@pytest.mark.parametrize(
    "change",
    [
        "empty",
        "missing",
        "duplicate",
        "wrong_service",
        "off_grid",
        "left_boundary",
        "before_left",
        "future",
        "missing_current",
    ],
)
def test_online_boundaries(change):
    rows = history()
    if change == "empty":
        rows = []
    elif change == "missing":
        rows.pop(7)
    elif change == "duplicate":
        rows[7] = rows[6]
    elif change == "wrong_service":
        rows[7]["service_id"] = "auth-service"
    elif change == "off_grid":
        rows[7]["timestamp"] = (T - timedelta(minutes=7, seconds=1)).isoformat()
    elif change == "left_boundary":
        rows[0]["timestamp"] = (T - timedelta(minutes=15)).isoformat()
    elif change == "before_left":
        rows[0]["timestamp"] = (T - timedelta(minutes=15, microseconds=1)).isoformat()
    elif change == "future":
        rows[-1]["timestamp"] = (T + timedelta(microseconds=1)).isoformat()
    elif change == "missing_current":
        rows.pop()
    with pytest.raises((DomainError, ValueError)):
        online_features(rows, "api-gateway", T)


@pytest.mark.parametrize(
    "field,value",
    [
        ("service_id", "unknown"),
        ("timestamp", "2025-01-01T00:15:00"),
        ("timestamp", "2025-01-01T01:15:00+01:00"),
        ("timestamp", "2025-01-01T00:15:01Z"),
        ("timestamp", 1735689600),
        ("timestamp", "1999-01-01T00:00:00Z"),
        ("error_rate", True),
        ("error_rate", "0.1"),
        ("error_rate", float("inf")),
        ("error_rate", float("nan")),
        ("error_rate", -1),
        ("incident_id", "secret"),
    ],
)
def test_invalid_contract(field, value):
    row = sample()
    row[field] = value
    with pytest.raises(ValueError):
        Ingest(samples=[row])


def test_missing_metric():
    row = sample()
    del row["error_rate"]
    with pytest.raises(ValueError):
        Ingest(samples=[row])


def test_unready_model(tmp_path):
    settings = Settings(
        database_url="postgresql+psycopg://localhost/unavailable", model_directory=tmp_path
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").json()["error"]["code"] == "model_unready"
        assert (
            client.post(
                "/predictions", json={"service_id": "api-gateway", "timestamp": T.isoformat()}
            ).status_code
            == 503
        )


def test_unready_database(artifact_dir):
    settings = Settings(
        database_url="postgresql+psycopg://localhost:1/unavailable", model_directory=artifact_dir
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").json()["error"]["code"] == "database_unready"


def test_migrations_and_drift(db):
    with db.connect() as c:
        assert compare_metadata(MigrationContext.configure(c), metadata) == []
        assert c.scalar(sa.text("SELECT version_num FROM alembic_version")) == "c001"
        assert c.scalar(sa.text("SELECT count(*) FROM services")) == 4
    config = Config("alembic.ini")
    config.attributes["database_url"] = os.environ["RIP_TEST_DATABASE_URL"]
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    with db.connect() as c:
        assert compare_metadata(MigrationContext.configure(c), metadata) == []


def test_end_to_end(client, db):
    rows = (
        [sample(T - timedelta(minutes=15), value=99)]
        + history()
        + [sample(T + timedelta(minutes=1), value=99)]
        + history("auth-service")
    )
    assert client.post("/telemetry", json={"samples": rows}).json() == {
        "inserted": 32,
        "unchanged": 0,
    }
    request = {"service_id": "api-gateway", "timestamp": T.isoformat()}
    response = client.post("/predictions", json=request)
    assert response.status_code == 201, response.text
    prediction = response.json()
    assert prediction["probability"] == 0.25
    assert prediction["decision"] == "not-elevated-risk"
    assert prediction["threshold"] == REFERENCE_THRESHOLD
    assert prediction["window_start"] == (T - timedelta(minutes=15)).isoformat().replace(
        "+00:00", "Z"
    )
    assert client.post("/predictions", json=request).json() == prediction
    assert client.get("/predictions", params={"service_id": "api-gateway", "limit": 1}).json() == [
        prediction
    ]
    assert client.get("/predictions", params={"service_id": "auth-service"}).json() == []
    assert client.get("/predictions", params={"end": T.isoformat()}).json() == []
    with db.connect() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(predictions)) == 1
        assert c.scalar(sa.text("SELECT predictions FROM daily_risk")) == 1
        assert c.scalar(sa.text("SELECT elevated FROM latest_risk")) is False
        assert risk_summary(c, T, T + timedelta(minutes=1))[0]["mean_probability"] == 0.25
        result = coverage(c, T - timedelta(minutes=14), T + timedelta(minutes=1))
        assert result[0]["missing_minutes"] == 0
        assert result[2]["missing_minutes"] == 15
    # Database-backed float64 inputs produce precisely the offline output.
    with db.connect() as c:
        stored = (
            c.execute(
                sa.select(telemetry)
                .where(
                    telemetry.c.service_id == "api-gateway",
                    telemetry.c.timestamp > T - timedelta(minutes=15),
                    telemetry.c.timestamp <= T,
                )
                .order_by(telemetry.c.timestamp)
            )
            .mappings()
            .all()
        )
    pd.testing.assert_frame_equal(
        online_features(stored, "api-gateway", T),
        online_features(history(), "api-gateway", T),
        check_exact=True,
    )


def test_ingest_idempotency_rollback(client, db):
    assert client.post("/telemetry", json={"samples": [sample()]}).json()["inserted"] == 1
    assert client.post("/telemetry", json={"samples": [sample()]}).json()["unchanged"] == 1
    conflict = sample(value=11)
    earlier = sample(T - timedelta(minutes=1))
    assert client.post("/telemetry", json={"samples": [earlier, conflict]}).status_code == 409
    with db.connect() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(telemetry)) == 1
    assert client.post("/telemetry", json={"samples": [earlier, earlier]}).status_code == 422


@pytest.mark.parametrize(
    "bad",
    [
        {"error_rate": 1.1},
        {"cpu_utilisation_pct": 101},
        {"latency_p95_ms": 1},
        {"timestamp": "2100-01-01T00:00:00Z"},
    ],
)
def test_batch_invalid_atomic(client, db, bad):
    row = sample()
    row.update(bad)
    assert (
        client.post(
            "/telemetry", json={"samples": [sample(T - timedelta(minutes=1)), row]}
        ).status_code
        == 422
    )
    with db.connect() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(telemetry)) == 0


def test_incomplete_and_failure(client, db, monkeypatch):
    request = {"service_id": "api-gateway", "timestamp": T.isoformat()}
    assert client.post("/predictions", json=request).json()["error"]["code"] == "incomplete_history"
    rows = history()
    missing = rows.pop(7)
    client.post("/telemetry", json={"samples": rows})
    assert client.post("/predictions", json=request).status_code == 422
    client.post("/telemetry", json={"samples": [missing]})

    def fail(features):
        raise RuntimeError("private failure")

    monkeypatch.setattr(client.app.state.repository.artifact.model, "predict", fail)
    response = client.post("/predictions", json=request)
    assert response.status_code == 503 and "private" not in response.text
    with db.connect() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(predictions)) == 0


def test_concurrent_retries(client, db):
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(
            pool.map(lambda _: client.post("/telemetry", json={"samples": history()}), range(16))
        )
    assert sum(r.json()["inserted"] for r in responses) == 15
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(
            pool.map(
                lambda _: client.post(
                    "/predictions", json={"service_id": "api-gateway", "timestamp": T.isoformat()}
                ),
                range(16),
            )
        )
    assert [r.status_code for r in responses].count(201) == 1
    assert [r.status_code for r in responses].count(200) == 15
    assert len({r.json()["id"] for r in responses}) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("error_rate", float("nan")),
        ("request_rate_rps", float("inf")),
        ("error_rate", 1.1),
        ("service_id", "unknown"),
        ("timestamp", T + timedelta(seconds=1)),
    ],
)
def test_database_constraints(db, field, value):
    row = Ingest(samples=[sample()]).samples[0].model_dump()
    row[field] = value
    with pytest.raises(sa.exc.IntegrityError), db.begin() as c:
        c.execute(telemetry.insert().values(**row))


def test_database_immutable(client, db):
    client.post("/telemetry", json={"samples": [sample()]})
    with pytest.raises(sa.exc.DBAPIError), db.begin() as c:
        c.execute(telemetry.update().values(error_rate=0.2))


def test_dependency_failure_after_start(client, db):
    with db.begin() as c:
        c.execute(sa.text("ALTER TABLE predictions RENAME TO broken_predictions"))
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 503
    assert client.get("/predictions").json()["error"]["code"] == "database_unavailable"


def test_request_errors(client):
    assert (
        client.post(
            "/telemetry", content="{broken", headers={"Content-Type": "application/json"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/telemetry",
            content='{"samples":[' + json.dumps(sample()).replace("0.01", "NaN") + "]}",
            headers={"Content-Type": "application/json"},
        ).status_code
        == 422
    )
    assert client.get("/predictions", params={"limit": 0}).status_code == 422
    assert (
        client.get(
            "/predictions", params={"start": T.isoformat(), "end": T.isoformat()}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/predictions", json={"service_id": "api-gateway", "timestamp": "2100-01-01T00:00:00Z"}
        ).status_code
        == 422
    )


def test_availability_cutoff(client, db):
    rows = Ingest(samples=history()).samples
    with db.begin() as c:
        for index, row in enumerate(rows):
            data = row.model_dump()
            if index == 7:
                data["ingested_at"] = datetime(2100, 1, 1, tzinfo=UTC)
            c.execute(telemetry.insert().values(**data))
    result = client.post(
        "/predictions", json={"service_id": "api-gateway", "timestamp": T.isoformat()}
    )
    assert result.status_code == 422
    assert result.json()["error"]["missing_minutes"] == 1


def test_prediction_write_failure_rolls_back(client, db):
    assert client.post("/telemetry", json={"samples": history()}).status_code == 200
    with db.begin() as c:
        c.execute(
            sa.text("""CREATE FUNCTION fail_prediction() RETURNS trigger LANGUAGE plpgsql
        AS $$ BEGIN RAISE EXCEPTION 'private database failure'; END; $$""")
        )
        c.execute(
            sa.text("""CREATE TRIGGER prediction_failure AFTER INSERT ON predictions
        FOR EACH ROW EXECUTE FUNCTION fail_prediction()""")
        )
    result = client.post(
        "/predictions", json={"service_id": "api-gateway", "timestamp": T.isoformat()}
    )
    assert result.status_code == 503 and "private database failure" not in result.text
    with db.connect() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(predictions)) == 0


def test_model_invalid_probability(client, db, monkeypatch):
    client.post("/telemetry", json={"samples": history()})
    monkeypatch.setattr(
        client.app.state.repository.artifact.model, "predict", lambda x: np.array([np.nan])
    )
    assert (
        client.post(
            "/predictions", json={"service_id": "api-gateway", "timestamp": T.isoformat()}
        ).status_code
        == 503
    )
    with db.connect() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(predictions)) == 0


def test_prediction_constraints(client, db):
    from uuid import uuid4

    client.post("/telemetry", json={"samples": history()})
    payload = {"service_id": "api-gateway", "timestamp": T.isoformat()}
    client.post("/predictions", json=payload)
    with db.connect() as c:
        saved = dict(c.execute(sa.select(predictions)).mappings().one())
    for changes in (
        {"id": uuid4()},
        {"id": uuid4(), "timestamp": T - timedelta(minutes=1), "probability": float("nan")},
        {"id": uuid4(), "timestamp": T - timedelta(minutes=1), "model_id": "absent"},
    ):
        with pytest.raises(sa.exc.IntegrityError), db.begin() as c:
            c.execute(predictions.insert().values(**{**saved, **changes}))
    with pytest.raises(sa.exc.DBAPIError), db.begin() as c:
        c.execute(predictions.delete())


def test_missing_migration_readiness(db, artifact_dir):
    with db.begin() as c:
        c.execute(sa.text("DROP TABLE alembic_version"))
    settings = Settings(
        database_url=os.environ["RIP_TEST_DATABASE_URL"], model_directory=artifact_dir
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/health/ready").status_code == 503
        assert client.get("/health/live").status_code == 200


def test_submicrosecond_timestamp_rejected():
    with pytest.raises(ValueError):
        Ingest(samples=[sample() | {"timestamp": "2025-01-01T00:15:00.000000001Z"}])


def test_float64_http_roundtrip(client, db):
    rng = np.random.default_rng(733)
    rows = history()
    for row in rows:
        row["request_rate_rps"] = float(rng.uniform(100, 300))
        row["error_rate"] = float(rng.uniform(0, 1))
    assert client.post("/telemetry", json={"samples": rows}).status_code == 200
    with db.connect() as c:
        saved = c.execute(sa.select(telemetry).order_by(telemetry.c.timestamp)).mappings().all()
    pd.testing.assert_frame_equal(
        online_features(rows, "api-gateway", T),
        online_features(saved, "api-gateway", T),
        check_exact=True,
    )
