"""Immutable monitoring snapshots and separately certified outcomes."""

from alembic import op

revision = "d001"
down_revision = "c001"
branch_labels = None
depends_on = None

SQL = """
CREATE TABLE incident_starts (
	source_id TEXT NOT NULL,
	service_id TEXT NOT NULL,
	start TIMESTAMP WITH TIME ZONE NOT NULL,
	recorded_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	PRIMARY KEY (source_id),
	CONSTRAINT incident_start_key UNIQUE (service_id, start),
	CONSTRAINT incident_starts_source CHECK (length(source_id) BETWEEN 1 AND 200),
        CONSTRAINT incident_starts_time CHECK (isfinite(start) AND isfinite(recorded_at) AND
start <= recorded_at),
	FOREIGN KEY(service_id) REFERENCES services (id)
)

;
CREATE INDEX incident_starts_lookup ON incident_starts (service_id, start);
CREATE TRIGGER incident_starts_immutable BEFORE UPDATE OR DELETE ON incident_starts FOR EACH ROW
EXECUTE FUNCTION reject_mutation();

CREATE TABLE outcome_coverage (
	source_id TEXT NOT NULL,
	service_id TEXT NOT NULL,
	start TIMESTAMP WITH TIME ZONE NOT NULL,
	"end" TIMESTAMP WITH TIME ZONE NOT NULL,
	recorded_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	PRIMARY KEY (source_id),
	CONSTRAINT outcome_coverage_source CHECK (length(source_id) BETWEEN 1 AND 200),
        CONSTRAINT outcome_coverage_time CHECK (isfinite(start) AND isfinite(recorded_at) AND
start <= recorded_at AND isfinite("end") AND start < "end" AND "end" <= recorded_at),
	FOREIGN KEY(service_id) REFERENCES services (id)
)

;
CREATE INDEX outcome_coverage_lookup ON outcome_coverage (service_id, start);
CREATE TRIGGER outcome_coverage_immutable BEFORE UPDATE OR DELETE ON outcome_coverage FOR EACH
ROW EXECUTE FUNCTION reject_mutation();

CREATE TABLE monitoring_snapshots (
	id TEXT NOT NULL,
	kind TEXT NOT NULL,
	start TIMESTAMP WITH TIME ZONE NOT NULL,
	"end" TIMESTAMP WITH TIME ZONE NOT NULL,
	cutoff TIMESTAMP WITH TIME ZONE NOT NULL,
	computed_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	model_id TEXT NOT NULL,
	reference_id TEXT NOT NULL,
	status TEXT NOT NULL,
	results JSONB NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT snapshot_kind CHECK (kind IN ('drift', 'delayed')),
        CONSTRAINT snapshot_status CHECK (status IN ('stable', 'warning', 'severe',
'insufficient', 'invalid', 'evaluated')),
	CONSTRAINT snapshot_hash CHECK (length(id) = 64 AND length(reference_id) = 64),
        CONSTRAINT snapshot_time CHECK (isfinite(start) AND isfinite("end") AND start < "end"
AND "end" - start <= interval '31 days' AND "end" <= cutoff AND cutoff <= computed_at AND
isfinite(computed_at)),
	FOREIGN KEY(model_id) REFERENCES models (id)
)

;
CREATE INDEX snapshot_history ON monitoring_snapshots (kind, start, cutoff);
CREATE TRIGGER monitoring_snapshots_immutable BEFORE UPDATE OR DELETE ON monitoring_snapshots
FOR EACH ROW EXECUTE FUNCTION reject_mutation();
"""


def upgrade():
    op.get_bind().exec_driver_sql(SQL)


def downgrade():
    op.execute("DROP TABLE monitoring_snapshots, outcome_coverage, incident_starts")
