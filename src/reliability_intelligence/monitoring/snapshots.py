"""Bounded, cutoff-aware statistical snapshots with immutable idempotent persistence."""

from datetime import timedelta

import numpy as np
import pandas as pd
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from reliability_intelligence.features import FEATURE_NAMES, build_features
from reliability_intelligence.monitoring.outcomes import delayed_labels, metrics
from reliability_intelligence.monitoring.reference import DriftConfig, digest, drift, seal, verify
from reliability_intelligence.monitoring.schema import incident_starts, outcome_coverage, snapshots
from reliability_intelligence.serving.contracts import SERVICES, telemetry_frame, utc_time
from reliability_intelligence.serving.database import predictions, telemetry


def summary(values):
    values = np.asarray(values, dtype=float)
    return {
        "count": len(values),
        "min": float(values.min()) if len(values) else None,
        "median": float(np.median(values)) if len(values) else None,
        "max": float(values.max()) if len(values) else None,
    }


def create_snapshot(repo, kind, start, end, cutoff, reference=None):
    start, end = utc_time(start), utc_time(end)
    if (
        kind not in ("drift", "delayed")
        or not start < end
        or end - start > timedelta(days=31)
        or cutoff.tzinfo is None
        or cutoff < end
    ):
        raise ValueError("Invalid bounded interval/cutoff")
    if kind == "drift":
        verify(reference)
        if reference["model_id"] != repo.artifact.metadata["id"]:
            raise ValueError("Reference/model mismatch")
    reference_id = (
        reference["sha256"]
        if kind == "drift"
        else digest({"delayed_contract": 1, "threshold": repo.artifact.metadata["threshold"]})
    )
    identity = {
        "kind": kind,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "cutoff": cutoff.isoformat(),
        "model_id": repo.artifact.metadata["id"],
        "reference_id": reference_id,
    }
    key = digest(identity)
    with repo.engine.begin() as connection:
        connection.execute(sa.text("SELECT pg_advisory_xact_lock(73022)"))
        now = connection.scalar(sa.text("SELECT clock_timestamp()"))
        if cutoff > now:
            raise ValueError("Cutoff cannot be in the future")
        existing = (
            connection.execute(sa.select(snapshots).where(snapshots.c.id == key))
            .mappings()
            .one_or_none()
        )
        if existing:
            verify(existing["results"])
            return dict(existing)
        scored = [
            dict(r)
            for r in connection.execute(
                sa.select(predictions)
                .where(
                    predictions.c.timestamp >= start,
                    predictions.c.timestamp < end,
                    predictions.c.model_id == repo.artifact.metadata["id"],
                    predictions.c.produced_at <= cutoff,
                )
                .order_by(predictions.c.service_id, predictions.c.timestamp)
            ).mappings()
        ]
        if kind == "delayed":
            incidents = [
                dict(r)
                for r in connection.execute(
                    sa.select(incident_starts)
                    .where(
                        incident_starts.c.start > start,
                        incident_starts.c.start <= end + timedelta(minutes=10),
                        incident_starts.c.recorded_at <= cutoff,
                    )
                    .limit(100001)
                ).mappings()
            ]
            certificates = [
                dict(r)
                for r in connection.execute(
                    sa.select(outcome_coverage)
                    .where(
                        outcome_coverage.c.start <= end + timedelta(minutes=10),
                        outcome_coverage.c.end > start,
                        outcome_coverage.c.recorded_at <= cutoff,
                    )
                    .limit(100001)
                ).mappings()
            ]
            if len(incidents) > 100000 or len(certificates) > 100000:
                raise ValueError("Outcome query limit exceeded")
            eligible, excluded = delayed_labels(scored, incidents, certificates, cutoff)
            detail = {
                "threshold": repo.artifact.metadata["threshold"],
                "predictions": len(scored),
                "excluded": excluded,
                "metrics": metrics(eligible, incidents),
                "services": {
                    s: metrics(
                        [r for r in eligible if r["service_id"] == s],
                        [r for r in incidents if r["service_id"] == s],
                    )
                    for s in SERVICES
                },
            }
            overall = "evaluated" if eligible else "insufficient"
        else:
            records = [
                dict(r)
                for r in connection.execute(
                    sa.select(telemetry)
                    .where(
                        telemetry.c.timestamp > start - timedelta(minutes=15),
                        telemetry.c.timestamp < end,
                        telemetry.c.ingested_at <= cutoff,
                    )
                    .order_by(telemetry.c.timestamp, telemetry.c.service_id)
                ).mappings()
            ]
            config = DriftConfig(**reference["config"]).checked()
            features = (
                build_features(
                    telemetry_frame(records),
                    coverage_start=pd.Timestamp(start) - timedelta(minutes=15),
                )
                if records
                else pd.DataFrame(columns=["timestamp", *FEATURE_NAMES])
            )
            features = features.loc[features.timestamp >= start]
            results = {
                name: drift(features[name], reference["distributions"][name], config)
                for name in FEATURE_NAMES
            }
            results["probability"] = drift(
                [r["probability"] for r in scored],
                reference["distributions"]["probability"],
                config,
            )
            order = ["stable", "insufficient", "warning", "severe", "invalid"]
            overall = max((r["status"] for r in results.values()), key=order.index)
            services = {}
            for service in SERVICES:
                local = [
                    r for r in records if r["service_id"] == service and r["timestamp"] >= start
                ]
                count = len(local)
                expected = int((end - start).total_seconds() / 60)
                services[service] = {
                    "rows": count,
                    "expected_minutes": expected,
                    "missing_minutes": expected - count,
                    "grid_completeness": count / expected,
                    "event_freshness_seconds": (
                        cutoff - max(r["timestamp"] for r in local)
                    ).total_seconds()
                    if local
                    else None,
                    "ingestion_lag_seconds": summary(
                        [(r["ingested_at"] - r["timestamp"]).total_seconds() for r in local]
                    ),
                }
            detail = {
                "config": config.model_dump(),
                "feature_samples": len(features),
                "prediction_samples": len(scored),
                "elevated_risk_rate": sum(
                    r["probability"] >= repo.artifact.metadata["threshold"] for r in scored
                )
                / len(scored)
                if scored
                else None,
                "services": services,
                "drift": results,
                "rejected_requests": None,
                "rejected_requests_note": (
                    "Available only in process-local application metrics; no durable request ledger"
                ),
            }
        results = seal({"schema_version": "monitoring-snapshot-1", "identity": identity, **detail})
        connection.execute(
            insert(snapshots).values(
                id=key,
                kind=kind,
                start=start,
                end=end,
                cutoff=cutoff,
                model_id=identity["model_id"],
                reference_id=reference_id,
                status=overall,
                results=results,
            )
        )
        return dict(
            connection.execute(sa.select(snapshots).where(snapshots.c.id == key)).mappings().one()
        )


def history(engine, kind, start=None, end=None, limit=100):
    if (
        kind not in ("drift", "delayed")
        or not 1 <= limit <= 1000
        or (start is not None and end is not None and start >= end)
    ):
        raise ValueError("Invalid snapshot filter")
    query = sa.select(snapshots).where(snapshots.c.kind == kind)
    if start is not None:
        query = query.where(snapshots.c.start >= start)
    if end is not None:
        query = query.where(snapshots.c.start < end)
    with engine.connect() as connection:
        rows = [
            dict(r)
            for r in connection.execute(
                query.order_by(snapshots.c.cutoff.desc(), snapshots.c.id).limit(limit)
            ).mappings()
        ]
    for row in rows:
        verify(row["results"])
    return rows
