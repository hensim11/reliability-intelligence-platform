"""Frozen initial operational schema and SQL analytics."""

from alembic import op

revision = "c001"
down_revision = None
branch_labels = None
depends_on = None

SQL = r"""
CREATE TABLE models (
    id TEXT NOT NULL,
    name TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    feature_version TEXT NOT NULL,
    threshold DOUBLE PRECISION NOT NULL,
    artifact_hashes JSONB NOT NULL,
    runtime JSONB NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT threshold_range CHECK (threshold >= 0 AND threshold <= 1)
)

;

CREATE TABLE services (
    id TEXT NOT NULL,
    PRIMARY KEY (id)
)

;

CREATE TABLE predictions (
    id UUID NOT NULL,
    service_id TEXT NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    model_id TEXT NOT NULL,
    available_as_of TIMESTAMP WITH TIME ZONE NOT NULL,
    produced_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
    probability DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT probability_range CHECK (probability >= 0 AND probability <= 1),
        CONSTRAINT prediction_time CHECK (timestamp = date_trunc('minute', timestamp) AND
    timestamp >= '2000-01-01Z'::timestamptz AND timestamp < '2101-01-01Z'::timestamptz AND
    timestamp <= available_as_of AND available_as_of <= produced_at AND isfinite(produced_at)),
    CONSTRAINT prediction_key UNIQUE (service_id, timestamp, model_id),
    FOREIGN KEY(service_id) REFERENCES services (id),
    FOREIGN KEY(model_id) REFERENCES models (id)
)

;

CREATE TABLE telemetry (
    service_id TEXT NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    ingested_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
    request_rate_rps DOUBLE PRECISION NOT NULL,
    latency_p50_ms DOUBLE PRECISION NOT NULL,
    latency_p95_ms DOUBLE PRECISION NOT NULL,
    error_rate DOUBLE PRECISION NOT NULL,
    cpu_utilisation_pct DOUBLE PRECISION NOT NULL,
    memory_utilisation_pct DOUBLE PRECISION NOT NULL,
    dependency_latency_ms DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (service_id, timestamp),
        CONSTRAINT finite_request_rate_rps CHECK (request_rate_rps >= 0 AND request_rate_rps <
    'Infinity'::float8),
        CONSTRAINT finite_latency_p50_ms CHECK (latency_p50_ms >= 0 AND latency_p50_ms <
    'Infinity'::float8),
        CONSTRAINT finite_latency_p95_ms CHECK (latency_p95_ms >= 0 AND latency_p95_ms <
    'Infinity'::float8),
    CONSTRAINT finite_error_rate CHECK (error_rate >= 0 AND error_rate < 'Infinity'::float8),
        CONSTRAINT finite_cpu_utilisation_pct CHECK (cpu_utilisation_pct >= 0 AND
    cpu_utilisation_pct < 'Infinity'::float8),
        CONSTRAINT finite_memory_utilisation_pct CHECK (memory_utilisation_pct >= 0 AND
    memory_utilisation_pct < 'Infinity'::float8),
        CONSTRAINT finite_dependency_latency_ms CHECK (dependency_latency_ms >= 0 AND
    dependency_latency_ms < 'Infinity'::float8),
        CONSTRAINT metric_ranges CHECK (error_rate <= 1 AND cpu_utilisation_pct <= 100 AND
    memory_utilisation_pct <= 100),
    CONSTRAINT latency_order CHECK (latency_p95_ms >= latency_p50_ms),
        CONSTRAINT telemetry_time CHECK (timestamp = date_trunc('minute', timestamp) AND
    timestamp >= '2000-01-01Z'::timestamptz AND timestamp < '2101-01-01Z'::timestamptz AND
    timestamp <= ingested_at AND isfinite(ingested_at)),
    FOREIGN KEY(service_id) REFERENCES services (id)
)

;
CREATE INDEX prediction_history ON predictions (service_id, timestamp DESC, id);
CREATE INDEX prediction_time_history ON predictions (timestamp DESC, id);
INSERT INTO services VALUES
    ('api-gateway'), ('auth-service'), ('catalog-service'), ('search-service');
CREATE FUNCTION reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Operational records are immutable'; END; $$;
CREATE TRIGGER telemetry_immutable BEFORE UPDATE OR DELETE ON telemetry FOR EACH ROW EXECUTE
    FUNCTION reject_mutation();
CREATE TRIGGER models_immutable BEFORE UPDATE OR DELETE ON models FOR EACH ROW EXECUTE FUNCTION
    reject_mutation();
CREATE TRIGGER predictions_immutable BEFORE UPDATE OR DELETE ON predictions FOR EACH ROW EXECUTE
    FUNCTION reject_mutation();
CREATE VIEW latest_risk AS
SELECT DISTINCT ON (p.service_id) p.*, m.name AS model_name, m.threshold,
p.probability >= m.threshold AS elevated
FROM predictions p JOIN models m ON p.model_id = m.id
ORDER BY p.service_id, p.timestamp DESC, p.produced_at DESC, p.id;
CREATE VIEW daily_risk AS
SELECT p.service_id, (p.timestamp AT TIME ZONE 'UTC')::date AS day,
p.model_id, count(*) AS predictions,
count(*) FILTER (WHERE p.probability >= m.threshold) AS elevated_predictions,
avg(p.probability) AS mean_probability, min(p.probability) AS min_probability,
max(p.probability) AS max_probability,
percentile_cont(0.5) WITHIN GROUP (ORDER BY p.probability) AS median_probability
FROM predictions p JOIN models m ON p.model_id = m.id
GROUP BY p.service_id, (p.timestamp AT TIME ZONE 'UTC')::date, p.model_id;
"""


def upgrade():
    op.get_bind().exec_driver_sql(SQL)


def downgrade():
    op.execute("DROP VIEW daily_risk, latest_risk")
    op.execute("DROP TABLE predictions, models, telemetry, services")
    op.execute("DROP FUNCTION reject_mutation()")
