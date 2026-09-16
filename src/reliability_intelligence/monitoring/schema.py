"""Batch D tables, kept separate from inference data and queries."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from reliability_intelligence.serving.database import metadata


def outcomes_table(name, coverage=False):
    return sa.Table(
        name,
        metadata,
        sa.Column("source_id", sa.Text, primary_key=True),
        sa.Column("service_id", sa.Text, sa.ForeignKey("services.id"), nullable=False),
        sa.Column("start", sa.DateTime(timezone=True), nullable=False),
        *([sa.Column("end", sa.DateTime(timezone=True), nullable=False)] if coverage else []),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        *(
            []
            if coverage
            else [sa.UniqueConstraint("service_id", "start", name="incident_start_key")]
        ),
        sa.CheckConstraint("length(source_id) BETWEEN 1 AND 200", name=f"{name}_source"),
        sa.CheckConstraint(
            "isfinite(start) AND isfinite(recorded_at) AND start <= recorded_at"
            + (
                ' AND isfinite("end") AND start < "end" AND "end" <= recorded_at'
                if coverage
                else ""
            ),
            name=f"{name}_time",
        ),
    )


incident_starts = outcomes_table("incident_starts")
outcome_coverage = outcomes_table("outcome_coverage", True)
for table in (incident_starts, outcome_coverage):
    sa.Index(f"{table.name}_lookup", table.c.service_id, table.c.start)
snapshots = sa.Table(
    "monitoring_snapshots",
    metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("kind", sa.Text, nullable=False),
    sa.Column("start", sa.DateTime(timezone=True), nullable=False),
    sa.Column("end", sa.DateTime(timezone=True), nullable=False),
    sa.Column("cutoff", sa.DateTime(timezone=True), nullable=False),
    sa.Column(
        "computed_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("clock_timestamp()"),
    ),
    sa.Column("model_id", sa.Text, sa.ForeignKey("models.id"), nullable=False),
    sa.Column("reference_id", sa.Text, nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("results", JSONB, nullable=False),
    sa.CheckConstraint("kind IN ('drift', 'delayed')", name="snapshot_kind"),
    sa.CheckConstraint(
        "status IN ('stable', 'warning', 'severe', 'insufficient', 'invalid', 'evaluated')",
        name="snapshot_status",
    ),
    sa.CheckConstraint("length(id) = 64 AND length(reference_id) = 64", name="snapshot_hash"),
    sa.CheckConstraint(
        'isfinite(start) AND isfinite("end") AND start < "end" '
        'AND "end" - start <= interval \'31 days\' AND "end" <= cutoff '
        "AND cutoff <= computed_at AND isfinite(computed_at)",
        name="snapshot_time",
    ),
)
sa.Index("snapshot_history", snapshots.c.kind, snapshots.c.start, snapshots.c.cutoff)
