"""SQLAlchemy Core schema: immutable telemetry, deduplicated model metadata, predictions."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from reliability_intelligence.features import METRICS

metadata = sa.MetaData()
services = sa.Table("services", metadata, sa.Column("id", sa.Text, primary_key=True))
telemetry = sa.Table(
    "telemetry",
    metadata,
    sa.Column("service_id", sa.Text, sa.ForeignKey("services.id"), primary_key=True),
    sa.Column("timestamp", sa.DateTime(timezone=True), primary_key=True),
    sa.Column(
        "ingested_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("clock_timestamp()"),
    ),
    *(sa.Column(name, sa.Double, nullable=False) for name in METRICS),
    *(
        sa.CheckConstraint(f"{name} >= 0 AND {name} < 'Infinity'::float8", name=f"finite_{name}")
        for name in METRICS
    ),
    sa.CheckConstraint(
        "error_rate <= 1 AND cpu_utilisation_pct <= 100 AND memory_utilisation_pct <= 100",
        name="metric_ranges",
    ),
    sa.CheckConstraint("latency_p95_ms >= latency_p50_ms", name="latency_order"),
    sa.CheckConstraint(
        "timestamp = date_trunc('minute', timestamp) AND timestamp >= "
        "'2000-01-01Z'::timestamptz AND timestamp < '2101-01-01Z'::timestamptz AND "
        "timestamp <= ingested_at AND isfinite(ingested_at)",
        name="telemetry_time",
    ),
)
models = sa.Table(
    "models",
    metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("sha256", sa.Text, nullable=False),
    sa.Column("feature_version", sa.Text, nullable=False),
    sa.Column("threshold", sa.Double, nullable=False),
    sa.Column("artifact_hashes", JSONB, nullable=False),
    sa.Column("runtime", JSONB, nullable=False),
    sa.CheckConstraint("threshold >= 0 AND threshold <= 1", name="threshold_range"),
)
predictions = sa.Table(
    "predictions",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("service_id", sa.Text, sa.ForeignKey("services.id"), nullable=False),
    sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
    sa.Column("model_id", sa.Text, sa.ForeignKey("models.id"), nullable=False),
    sa.Column("available_as_of", sa.DateTime(timezone=True), nullable=False),
    sa.Column(
        "produced_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("clock_timestamp()"),
    ),
    sa.Column("probability", sa.Double, nullable=False),
    sa.CheckConstraint("probability >= 0 AND probability <= 1", name="probability_range"),
    sa.CheckConstraint(
        "timestamp = date_trunc('minute', timestamp) AND timestamp >= "
        "'2000-01-01Z'::timestamptz AND timestamp < '2101-01-01Z'::timestamptz AND "
        "timestamp <= available_as_of AND available_as_of <= produced_at AND "
        "isfinite(produced_at)",
        name="prediction_time",
    ),
    sa.UniqueConstraint("service_id", "timestamp", "model_id", name="prediction_key"),
)
sa.Index(
    "prediction_history", predictions.c.service_id, predictions.c.timestamp.desc(), predictions.c.id
)

sa.Index("prediction_time_history", predictions.c.timestamp.desc(), predictions.c.id)


def make_engine(url: str):
    return sa.create_engine(
        url,
        pool_size=8,
        max_overflow=0,
        pool_timeout=5,
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": 3,
            "options": "-c timezone=UTC -c statement_timeout=10000 -c lock_timeout=5000",
        },
    )
