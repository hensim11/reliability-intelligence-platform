"""Test-only real PostgreSQL harness, called by the isolated Batch D Compose runner."""

from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import sqlalchemy as sa
from fastapi.testclient import TestClient

from reliability_intelligence.monitoring.outcomes import import_outcomes
from reliability_intelligence.monitoring.reference import load_reference
from reliability_intelligence.monitoring.snapshots import create_snapshot
from reliability_intelligence.serving.api import create_app
from reliability_intelligence.serving.artifact import load_artifact
from reliability_intelligence.serving.contracts import Settings
from reliability_intelligence.serving.database import make_engine
from reliability_intelligence.serving.repository import Repository


def run_exercises(url, model, reference_dir, corpus):
    engine = make_engine(url)
    artifact = load_artifact(model)
    reference = load_reference(reference_dir, artifact.metadata["id"])
    repo = Repository(engine, artifact)
    repo.check_database()
    repo.register_model()
    frame = pd.read_parquet(corpus / "development-101/telemetry.parquet")
    start = frame.timestamp.min() + timedelta(minutes=15)
    end = frame.timestamp.min() + timedelta(minutes=2880)
    stable = frame.loc[frame.timestamp < end]
    for offset in range(0, len(stable), 1000):
        repo.ingest(stable.iloc[offset : offset + 1000].to_dict(orient="records"))
    # Fixed deterministic stress interval, separate event-time keys; no outcome inputs.
    shifted = stable.groupby("service_id", sort=True).head(215).copy()
    shifted.timestamp += timedelta(days=7)
    for name in ("latency_p50_ms", "latency_p95_ms", "dependency_latency_ms", "request_rate_rps"):
        shifted[name] = shifted[name] * 20 + 10000
    shifted.error_rate = 0.95
    shifted.cpu_utilisation_pct = 99.0
    shifted.memory_utilisation_pct = 99.0
    for offset in range(0, len(shifted), 1000):
        repo.ingest(shifted.iloc[offset : offset + 1000].to_dict(orient="records"))
    for source in (stable, shifted):
        if source is stable:
            eligible = source.loc[source.timestamp >= start]
            candidates = pd.concat(
                [
                    rows.iloc[np.linspace(0, len(rows) - 1, 100, dtype=int)]
                    for _, rows in eligible.groupby("service_id", sort=True)
                ]
            )
        else:
            candidates = source.groupby("service_id", sort=True).tail(30)
        for row in candidates.itertuples():
            repo.predict(row.service_id, row.timestamp.to_pydatetime())

    def clock():
        with engine.connect() as connection:
            return connection.scalar(sa.text("SELECT clock_timestamp()"))

    a = create_snapshot(
        repo, "drift", start.to_pydatetime(), end.to_pydatetime(), clock(), reference
    )
    b = create_snapshot(
        repo,
        "drift",
        (start + timedelta(days=7)).to_pydatetime(),
        (shifted.timestamp.max() + timedelta(minutes=1)).to_pydatetime(),
        clock(),
        reference,
    )
    assert b["status"] == "severe"
    # Feature aggregate independently of operational prediction subsampling.
    assert a["status"] != "severe"
    assert create_snapshot(repo, "drift", b["start"], b["end"], b["cutoff"], reference) == b
    t = shifted.timestamp.max().to_pydatetime()
    payload = {
        "incidents": [
            {
                "source_id": "exercise-incident",
                "service_id": "api-gateway",
                "start": t + timedelta(minutes=10),
            }
        ],
        "coverage": [
            {
                "source_id": "exercise-coverage",
                "service_id": "api-gateway",
                "start": t - timedelta(minutes=30),
                "end": t + timedelta(minutes=10),
            }
        ],
    }
    imported = import_outcomes(engine, payload)
    repeated = import_outcomes(engine, payload)
    assert imported == {"inserted": 2, "unchanged": 0}
    assert repeated == {"inserted": 0, "unchanged": 2}
    delayed = create_snapshot(
        repo, "delayed", t - timedelta(minutes=30), t + timedelta(minutes=1), clock()
    )
    assert delayed["results"]["metrics"]["rows"] == 30
    assert delayed["results"]["metrics"]["positives"] == 1
    settings = Settings(database_url=url, model_directory=model, monitoring_reference=reference_dir)
    with TestClient(create_app(settings)) as client:
        assert client.get("/health/ready").status_code == 200
        before = len(repo.history(limit=1000))
        result = client.post(
            "/predictions",
            json={"service_id": "api-gateway", "timestamp": (t + timedelta(minutes=2)).isoformat()},
        )
        assert result.status_code == 422 and result.json()["error"]["code"] == "incomplete_history"

        class BrokenModel:
            def predict(self, features):
                raise RuntimeError("test-only injected model failure")

        from reliability_intelligence.serving.artifact import Artifact

        original = client.app.state.repository.artifact
        client.app.state.repository.artifact = Artifact(BrokenModel(), original.metadata)
        failure = client.post(
            "/predictions",
            json={
                "service_id": "api-gateway",
                "timestamp": (start + timedelta(minutes=1)).isoformat(),
            },
        )
        assert failure.status_code == 503
        assert len(repo.history(limit=1000)) == before
        text = client.get("/metrics").text
        assert 'rip_dependency_failures_total{dependency="model"} 1.0' in text
        assert 'rip_predictions_total{outcome="incomplete_history"} 1.0' in text
    with TestClient(
        create_app(
            Settings(
                database_url=url,
                model_directory=model,
                monitoring_reference=Path("/nonexistent-batch-d-reference"),
            )
        )
    ) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 503
        assert client.get("/metrics").status_code == 200
    with engine.connect() as connection:
        counts = {
            table: connection.scalar(sa.text(f"SELECT count(*) FROM {table}"))
            for table in (
                "telemetry",
                "predictions",
                "incident_starts",
                "outcome_coverage",
                "monitoring_snapshots",
            )
        }
    engine.dispose()
    return {
        "stable": a,
        "shifted": b,
        "delayed": delayed,
        "outcome_import": imported,
        "outcome_retry": repeated,
        "incomplete_history": result.json(),
        "model_failure": failure.json(),
        "rollback_prediction_count": before,
        "reference_startup_failure": "controlled",
        "durable_counts": counts,
        "reference_id": reference["sha256"],
    }
