"""HTTP + PostgreSQL demonstration and modest concurrency exercise on an EMPTY database.

Run against the documented one-worker local server. Never use a shared database.
The output directory must not exist. Inputs are telemetry only, never labels or truth.
"""

import argparse
import concurrent.futures
import importlib.metadata
import json
import os
import platform
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import sqlalchemy as sa

from reliability_intelligence.features import FEATURE_NAMES, build_features
from reliability_intelligence.serving.analytics import coverage, risk_summary
from reliability_intelligence.serving.artifact import load_artifact
from reliability_intelligence.serving.database import make_engine, predictions, telemetry
from reliability_intelligence.serving.repository import online_features
from reliability_intelligence.storage import file_hash


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--telemetry", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    engine = make_engine(os.environ["RIP_DATABASE_URL"])
    artifact = load_artifact(Path(os.environ["RIP_MODEL_DIR"]))

    def request(path, payload=None):
        started = time.perf_counter()
        req = urllib.request.Request(
            args.url + path,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                result = response.status, json.load(response)
        except urllib.error.HTTPError as error:
            result = error.code, json.load(error)
        return {
            "status": result[0],
            "body": result[1],
            "latency_ms": (time.perf_counter() - started) * 1000,
        }

    assert request("/health/ready")["status"] == 200
    with engine.connect() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(telemetry)) == 0, (
            "Use an empty database"
        )
        assert c.scalar(sa.select(sa.func.count()).select_from(predictions)) == 0
        version = c.scalar(sa.text("SELECT version()"))
        revision = c.scalar(sa.text("SELECT version_num FROM alembic_version"))
    source = pd.read_parquet(args.telemetry)
    times = sorted(source.timestamp.unique())[:46]
    source = source.loc[source.timestamp.isin(times)].copy()
    assert len(times) == 46
    samples = source.to_dict(orient="records")
    for sample in samples:
        sample["timestamp"] = sample["timestamp"].isoformat()
    ingested = request("/telemetry", {"samples": samples})
    assert ingested["status"] == 200 and ingested["body"]["inserted"] == len(source)
    offline = build_features(source, coverage_start=pd.Timestamp(times[0]))
    rows = offline.loc[offline.timestamp < times[-1]]
    payloads = [
        {"service_id": row.service_id, "timestamp": row.timestamp.isoformat()}
        for row in rows.itertuples()
    ]
    results = {}
    ids = set()
    for label, workers in [("new_predictions", 8), ("identical_retries", 8)]:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            outcomes = list(pool.map(lambda p: request("/predictions", p), payloads))
        assert all(r["status"] == (201 if label == "new_predictions" else 200) for r in outcomes)
        for r in outcomes:
            ids.add(r["body"]["id"])
        durations = [r["latency_ms"] for r in outcomes]
        results[label] = {
            "requests": len(outcomes),
            "workers": workers,
            "status_counts": dict(Counter(str(r["status"]) for r in outcomes)),
            "latency_ms": dict(
                zip(
                    ("min", "p50", "p95", "max"),
                    map(float, np.percentile(durations, [0, 50, 95, 100])),
                    strict=True,
                )
            ),
        }
    contended = {"service_id": "api-gateway", "timestamp": pd.Timestamp(times[-1]).isoformat()}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(lambda _: request("/predictions", contended), range(32)))
    assert sum(r["status"] == 201 for r in outcomes) == 1
    assert sum(r["status"] == 200 for r in outcomes) == 31
    assert len({r["body"]["id"] for r in outcomes}) == 1
    results["same_key_race"] = {
        "requests": 32,
        "workers": 8,
        "created": 1,
        "reused": 31,
        "latency_ms": dict(
            zip(
                ("min", "p50", "p95", "max"),
                map(float, np.percentile([r["latency_ms"] for r in outcomes], [0, 50, 95, 100])),
                strict=True,
            )
        ),
    }
    with engine.connect() as c:
        saved = c.execute(sa.select(predictions)).mappings().all()
        assert len(saved) == len(payloads) + 1
        parity_count = 0
        max_error = 0.0
        for row in saved:
            stored = (
                c.execute(
                    sa.select(telemetry)
                    .where(
                        telemetry.c.service_id == row["service_id"],
                        telemetry.c.timestamp > row["timestamp"] - pd.Timedelta(minutes=15),
                        telemetry.c.timestamp <= row["timestamp"],
                        telemetry.c.ingested_at <= row["available_as_of"],
                    )
                    .order_by(telemetry.c.timestamp)
                )
                .mappings()
                .all()
            )
            online = online_features(stored, row["service_id"], row["timestamp"])
            expected = offline.loc[
                (offline.service_id == row["service_id"]) & (offline.timestamp == row["timestamp"]),
                list(FEATURE_NAMES),
            ].reset_index(drop=True)
            pd.testing.assert_frame_equal(online, expected, check_exact=True)
            delta = abs(float(artifact.model.predict(expected)[0]) - row["probability"])
            assert delta == 0
            max_error = max(max_error, delta)
            parity_count += 1
        analytics = {
            "coverage": coverage(
                c,
                pd.Timestamp(times[0]).to_pydatetime(),
                (pd.Timestamp(times[-1]) + pd.Timedelta(minutes=1)).to_pydatetime(),
            ),
            "risk_summary": risk_summary(
                c,
                pd.Timestamp(times[0]).to_pydatetime(),
                (pd.Timestamp(times[-1]) + pd.Timedelta(minutes=1)).to_pydatetime(),
            ),
            "daily_risk": [
                dict(r)
                for r in c.execute(
                    sa.text("SELECT * FROM daily_risk ORDER BY service_id")
                ).mappings()
            ],
        }
    failures = {
        "incomplete_history": request(
            "/predictions",
            {"service_id": "api-gateway", "timestamp": pd.Timestamp(times[0]).isoformat()},
        ),
        "unknown_service": request(
            "/predictions",
            {"service_id": "unknown", "timestamp": pd.Timestamp(times[-1]).isoformat()},
        ),
        "conflicting_telemetry": request(
            "/telemetry", {"samples": [{**samples[0], "error_rate": 0.987654321}]}
        ),
    }
    assert [v["status"] for v in failures.values()] == [422, 422, 409]
    contract = request("/openapi.json")["body"]
    report = {
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "postgres": version,
            "dependencies": {
                d.metadata["Name"]: d.version
                for d in importlib.metadata.distributions()
                if d.metadata["Name"] != "reliability-intelligence"
            },
        },
        "schema_revision": revision,
        "model": artifact.metadata,
        "telemetry_sha256": file_hash(args.telemetry),
        "telemetry_rows": len(source),
        "persisted_predictions": len(saved),
        "feature_parity": {
            "windows": parity_count,
            "features": 49,
            "dtype": "float64",
            "exact": True,
            "max_probability_error": max_error,
        },
        "benchmark": results,
        "failures": failures,
        "analytics": analytics,
        "api_paths": {path: sorted(methods) for path, methods in contract["paths"].items()},
        "source_sha256": {
            str(path): file_hash(path)
            for root in ("src/reliability_intelligence/serving", "migrations", "scripts")
            for path in sorted(Path(root).rglob("*.py"))
        },
        "limitations": [
            "Local one-worker Uvicorn over loopback; no production SLO.",
            "Retrospective event-time scoring at server availability cutoff.",
            "Docker Compose not exercised by this script.",
        ],
    }
    (args.output / "results.json").write_text(
        json.dumps(report, indent=2, default=str, sort_keys=True) + "\n"
    )
    (args.output / "REPORT.md").write_text(f"""# Batch C local HTTP/PostgreSQL evidence

{len(source)} telemetry samples ingested, {len(saved)} predictions persisted.
{parity_count} database windows match all 49 offline float64 features exactly; saved
probabilities match the frozen model exactly (maximum absolute error {max_error}).

Eight concurrent HTTP clients exercised new requests and retries. A 32-request same-key
race produced exactly one row (201) and 31 identical retries (200).
See `results.json` for measured latency percentiles, environment, hashes, API paths,
SQL analytics and representative failures. The database started empty at revision {revision}.

This is a loopback, one-worker local exercise, not a production SLO. Inputs are historical
telemetry scored at the current ingestion cutoff. Synthetic validity and changed-regime
limitations from Batch B remain. Docker Compose validation is a separate gate.
""")
    engine.dispose()
    print(
        json.dumps(
            {"output": str(args.output), "windows": parity_count, "benchmark": results}, indent=2
        )
    )


if __name__ == "__main__":
    main()
