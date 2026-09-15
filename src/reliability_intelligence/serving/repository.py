"""Transactional operations. Service locks order ingestion, scoring and identical retries."""

import math
import threading
from datetime import timedelta
from uuid import uuid4

import pandas as pd
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from reliability_intelligence.features import FEATURE_NAMES, METRICS, build_features, feature_matrix
from reliability_intelligence.serving.contracts import SERVICES, telemetry_frame
from reliability_intelligence.serving.database import models, predictions, services, telemetry


class DomainError(Exception):
    def __init__(self, code, message, status=422, **context):
        self.code, self.message, self.status, self.context = code, message, status, context
        super().__init__(message)


def online_features(records, service_id, timestamp):
    start = pd.Timestamp(timestamp) - pd.Timedelta(minutes=15)
    if not records:
        raise DomainError(
            "incomplete_history", "15 exact minute samples are required", missing_minutes=15
        )
    frame = telemetry_frame(records)
    if (
        set(frame.service_id) != {service_id}
        or not ((frame.timestamp > start) & (frame.timestamp <= timestamp)).all()
    ):
        raise ValueError("Repository returned observations outside the requested service/window")
    expected = pd.date_range(start + pd.Timedelta(minutes=1), periods=15, freq="min")
    if not pd.DatetimeIndex(frame.timestamp).equals(expected):
        raise DomainError(
            "incomplete_history",
            "15 exact minute samples are required",
            missing_minutes=len(expected.difference(frame.timestamp)),
        )
    result = build_features(frame, coverage_start=start)
    if len(result) != 1:
        raise DomainError("incomplete_history", "Feature history is ineligible")
    return feature_matrix(result[list(FEATURE_NAMES)])


def lock_service(connection, service_id):
    # Fixed service list gives collision-free, stable cross-process advisory lock keys.
    connection.execute(
        sa.text("SELECT pg_advisory_xact_lock(73021, :key)"), {"key": SERVICES.index(service_id)}
    )


def prediction_query():
    return sa.select(
        predictions,
        models.c.name.label("model_name"),
        models.c.sha256.label("model_sha256"),
        models.c.feature_version,
        models.c.threshold,
        sa.case(
            (predictions.c.probability >= models.c.threshold, "elevated-risk"),
            else_="not-elevated-risk",
        ).label("decision"),
        (predictions.c.timestamp - sa.text("interval '15 minutes'")).label("window_start"),
        predictions.c.timestamp.label("window_end"),
    ).join(models)


class Repository:
    def __init__(self, engine, artifact):
        self.engine, self.artifact = engine, artifact
        # threadpoolctl changes process-wide native thread counts; do not overlap scopes.
        self.model_lock = threading.Lock()

    def check_database(self):
        with self.engine.connect() as connection:
            if connection.execute(
                sa.text("SELECT version_num FROM alembic_version")
            ).scalars().all() != ["c001"]:
                raise DomainError("schema_unready", "Apply the current database migrations", 503)
            if set(connection.execute(sa.select(services.c.id)).scalars()) != set(SERVICES):
                raise DomainError("schema_unready", "Service catalogue is incompatible", 503)
            for table in (telemetry, models, predictions):
                connection.execute(sa.select(table).limit(0))
                if not connection.scalar(
                    sa.text(
                        "SELECT has_table_privilege(current_user, :table, 'SELECT') "
                        "AND has_table_privilege(current_user, :table, 'INSERT')"
                    ),
                    {"table": table.name},
                ):
                    raise DomainError(
                        "database_unready", "Database permissions are insufficient", 503
                    )

    def register_model(self):
        with self.engine.begin() as connection:
            connection.execute(
                insert(models).values(**self.artifact.metadata).on_conflict_do_nothing()
            )
            saved = dict(
                connection.execute(
                    sa.select(models).where(models.c.id == self.artifact.metadata["id"])
                )
                .mappings()
                .one()
            )
            if saved != self.artifact.metadata:
                raise DomainError("model_metadata_conflict", "Stored model metadata differs", 503)

    def ingest(self, records):
        records = sorted(records, key=lambda row: (row["service_id"], row["timestamp"]))
        try:
            telemetry_frame(records)
        except ValueError as error:
            raise DomainError("invalid_telemetry", str(error)) from error
        inserted = 0
        with self.engine.begin() as connection:
            for service_id in sorted({row["service_id"] for row in records}):
                lock_service(connection, service_id)
            now = connection.scalar(sa.text("SELECT clock_timestamp()"))
            for row in records:
                if row["timestamp"] > now:
                    raise DomainError(
                        "future_timestamp", "Event timestamps cannot exceed database time"
                    )
                key = sa.and_(
                    telemetry.c.service_id == row["service_id"],
                    telemetry.c.timestamp == row["timestamp"],
                )
                existing = (
                    connection.execute(sa.select(telemetry).where(key)).mappings().one_or_none()
                )
                if existing:
                    if any(existing[name] != row[name] for name in METRICS):
                        raise DomainError(
                            "telemetry_conflict",
                            "Existing telemetry is immutable",
                            409,
                            service_id=row["service_id"],
                            timestamp=row["timestamp"].isoformat(),
                        )
                else:
                    connection.execute(telemetry.insert().values(**row))
                    inserted += 1
        return {"inserted": inserted, "unchanged": len(records) - inserted}

    def predict(self, service_id, timestamp):
        with self.engine.begin() as connection:
            lock_service(connection, service_id)
            cutoff = connection.scalar(sa.text("SELECT clock_timestamp()"))
            if timestamp > cutoff:
                raise DomainError("future_timestamp", "Prediction time cannot exceed database time")
            key = sa.and_(
                predictions.c.service_id == service_id,
                predictions.c.timestamp == timestamp,
                predictions.c.model_id == self.artifact.metadata["id"],
            )
            saved = connection.execute(prediction_query().where(key)).mappings().one_or_none()
            if saved is not None:
                return dict(saved), False
            rows = (
                connection.execute(
                    sa.select(telemetry)
                    .where(
                        telemetry.c.service_id == service_id,
                        telemetry.c.timestamp > timestamp - timedelta(minutes=15),
                        telemetry.c.timestamp <= timestamp,
                        telemetry.c.ingested_at <= cutoff,
                    )
                    .order_by(telemetry.c.timestamp)
                )
                .mappings()
                .all()
            )
            features = online_features(rows, service_id, timestamp)
            try:
                with self.model_lock:
                    values = self.artifact.model.predict(features)
                if (
                    len(values) != 1
                    or not math.isfinite(float(values[0]))
                    or not 0 <= values[0] <= 1
                ):
                    raise ValueError("Invalid model probability")
                probability = float(values[0])
            except Exception as error:
                raise DomainError(
                    "inference_failed", "The model could not produce a valid probability", 503
                ) from error
            connection.execute(
                predictions.insert().values(
                    id=uuid4(),
                    service_id=service_id,
                    timestamp=timestamp,
                    model_id=self.artifact.metadata["id"],
                    available_as_of=cutoff,
                    probability=probability,
                )
            )
            result = dict(connection.execute(prediction_query().where(key)).mappings().one())
        return result, True

    def history(self, service_id=None, start=None, end=None, limit=100):
        query = prediction_query()
        if service_id is not None:
            query = query.where(predictions.c.service_id == service_id)
        if start is not None:
            query = query.where(predictions.c.timestamp >= start)
        if end is not None:
            query = query.where(predictions.c.timestamp < end)
        with self.engine.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    query.order_by(predictions.c.timestamp.desc(), predictions.c.id).limit(limit)
                ).mappings()
            ]
