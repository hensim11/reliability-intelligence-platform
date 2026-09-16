"""Operational SQL summaries; no incident or future-label joins."""

import sqlalchemy as sa

from reliability_intelligence.serving.repository import DomainError


def coverage(connection, start, end):
    """Expected whole minutes in [start,end), including services with no observations."""
    if start >= end or (end - start).total_seconds() > 31 * 86400:
        raise DomainError("invalid_range", "Coverage range must be nonempty and at most 31 days")
    return [
        dict(row)
        for row in connection.execute(
            sa.text("""
        SELECT s.id AS service_id,
               extract(epoch FROM (:end_time - :start_time)::interval)::bigint / 60
                   AS expected_minutes,
               count(t.timestamp) AS observed_minutes,
               extract(epoch FROM (:end_time - :start_time)::interval)::bigint / 60
                   - count(t.timestamp) AS missing_minutes
        FROM services s LEFT JOIN telemetry t ON t.service_id = s.id
            AND t.timestamp >= :start_time AND t.timestamp < :end_time
        GROUP BY s.id ORDER BY s.id
    """),
            {"start_time": start, "end_time": end},
        ).mappings()
    ]


def risk_summary(connection, start, end):
    if start >= end:
        raise DomainError("invalid_range", "start must precede end")
    return [
        dict(row)
        for row in connection.execute(
            sa.text("""
        SELECT service_id, model_id, count(*) AS predictions,
               avg(probability) AS mean_probability,
               min(probability) AS min_probability, max(probability) AS max_probability,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY probability) AS median_probability
        FROM predictions WHERE timestamp >= :start_time AND timestamp < :end_time
        GROUP BY service_id, model_id ORDER BY service_id, model_id
    """),
            {"start_time": start, "end_time": end},
        ).mappings()
    ]
