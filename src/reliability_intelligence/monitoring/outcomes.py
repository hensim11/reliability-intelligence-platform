"""Trusted local outcome import and cutoff-aware certified delayed labels."""

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import sqlalchemy as sa
from pydantic import Field, field_validator, model_validator
from sqlalchemy.dialects.postgresql import insert

from reliability_intelligence.evaluation import operational_metrics, row_metrics
from reliability_intelligence.monitoring.schema import incident_starts, outcome_coverage
from reliability_intelligence.serving.artifact import REFERENCE_THRESHOLD
from reliability_intelligence.serving.contracts import Service, StrictModel
from reliability_intelligence.serving.repository import DomainError


class Incident(StrictModel):
    source_id: str = Field(min_length=1, max_length=200, strict=True)
    service_id: Service
    start: datetime

    @field_validator("start")
    @classmethod
    def utc(cls, value):
        if (
            value.tzinfo is None
            or value.utcoffset() != timedelta(0)
            or not 2000 <= value.year <= 2100
        ):
            raise ValueError("Explicit UTC time in 2000–2100 required")
        return value


class Coverage(Incident):
    end: datetime

    @model_validator(mode="after")
    def interval(self):
        self.utc(self.end)
        if self.end <= self.start:
            raise ValueError("Empty coverage interval")
        return self


class OutcomeImport(StrictModel):
    incidents: list[Incident] = Field(default_factory=list, max_length=10000)
    coverage: list[Coverage] = Field(default_factory=list, max_length=10000)


def import_outcomes(engine, payload):
    payload = OutcomeImport.model_validate(payload)
    counts = {"inserted": 0, "unchanged": 0}
    with engine.begin() as connection:
        # Serialise trusted imports so cross-record completeness checks are transactional.
        connection.execute(sa.text("SELECT pg_advisory_xact_lock(73022)"))
        now = connection.scalar(sa.text("SELECT clock_timestamp()"))
        for table, records in (
            (incident_starts, payload.incidents),
            (outcome_coverage, payload.coverage),
        ):
            for record in records:
                row = record.model_dump()
                if max(row.get("end", row["start"]), row["start"]) > now:
                    raise ValueError("Outcomes cannot certify the future")
                saved = (
                    connection.execute(
                        sa.select(table).where(table.c.source_id == row["source_id"])
                    )
                    .mappings()
                    .one_or_none()
                )
                if saved:
                    if any(saved[key] != value for key, value in row.items()):
                        raise DomainError("outcome_conflict", "Outcome source is immutable", 409)
                    counts["unchanged"] += 1
                    continue
                if table is incident_starts:
                    certified = connection.scalar(
                        sa.select(sa.func.count())
                        .select_from(outcome_coverage)
                        .where(
                            outcome_coverage.c.service_id == row["service_id"],
                            outcome_coverage.c.start < row["start"],
                            outcome_coverage.c.end >= row["start"],
                        )
                    )
                    if certified:
                        raise ValueError(
                            "New incident contradicts an already certified complete registry"
                        )
                connection.execute(insert(table).values(**row))
                counts["inserted"] += 1
    return counts


def covered(start, end, intervals):
    """Union of open-left, closed-right certificates covers the full (start,end]."""
    cursor = start
    for left, right in sorted(intervals):
        if left > cursor:
            return False
        if right > cursor:
            cursor = right
        if cursor >= end:
            return True
    return False


def delayed_labels(predictions, incidents, coverage, cutoff):
    eligible, excluded = [], {"immature": 0, "uncertified": 0, "unavailable_prediction": 0}
    for row in predictions:
        end = row["timestamp"] + timedelta(minutes=10)
        if row["produced_at"] > cutoff:
            excluded["unavailable_prediction"] += 1
            continue
        if end > cutoff:
            excluded["immature"] += 1
            continue
        intervals = [
            (c["start"], c["end"])
            for c in coverage
            if c["service_id"] == row["service_id"] and c["recorded_at"] <= cutoff
        ]
        if not covered(row["timestamp"], end, intervals):
            excluded["uncertified"] += 1
            continue
        target = any(
            i["service_id"] == row["service_id"]
            and i["recorded_at"] <= cutoff
            and row["timestamp"] < i["start"] <= end
            for i in incidents
        )
        eligible.append({**row, "target": int(target)})
    return eligible, excluded


def metrics(rows, incidents):
    result = row_metrics(
        np.array([r["target"] for r in rows], dtype=int),
        [r["probability"] for r in rows],
        REFERENCE_THRESHOLD,
    )
    predictions = pd.DataFrame(
        [{**r, "run_id": "operational"} for r in rows],
        columns=["run_id", "service_id", "timestamp", "probability"],
    )
    truth = pd.DataFrame(
        [
            {
                "run_id": "operational",
                "service_id": r["service_id"],
                "incident_start": r["start"],
                "incident_id": r["source_id"],
                "incident_type": "confirmed",
            }
            for r in incidents
        ],
        columns=["run_id", "service_id", "incident_start", "incident_id", "incident_type"],
    )
    operational, _, _ = operational_metrics(predictions, truth, REFERENCE_THRESHOLD)
    return {
        **result,
        **operational,
        "alert_row_fraction": operational["alert_minutes"] / len(rows) if rows else None,
    }
