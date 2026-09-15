"""Typed API boundary, reusing the authoritative operational metric validator."""

import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

import pandas as pd
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, SecretStr, field_validator

from reliability_intelligence.schemas import TELEMETRY_COLUMNS, validate_telemetry

SERVICES = ("api-gateway", "auth-service", "catalog-service", "search-service")
Service = Literal["api-gateway", "auth-service", "catalog-service", "search-service"]


def utc_time(value):
    if not isinstance(value, (str, datetime)):
        raise ValueError("Use an ISO-8601 UTC timestamp")
    if isinstance(value, str) and not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:00(?:\.0{1,6})?(?:Z|\+00:00)", value
    ):
        raise ValueError("Use a whole-minute ISO-8601 UTC timestamp")
    try:
        parsed = (
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            if isinstance(value, str)
            else value
        )
    except ValueError as error:
        raise ValueError("Use an ISO-8601 UTC timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("Timestamp must have explicit UTC offset")
    if not 2000 <= parsed.year <= 2100 or parsed.second or parsed.microsecond:
        raise ValueError("Timestamp must be a whole UTC minute in years 2000 through 2100")
    return parsed.astimezone(UTC)


Minute = Annotated[datetime, BeforeValidator(utc_time)]
Metric = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=0)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Settings(StrictModel):
    database_url: SecretStr
    model_directory: Path

    @field_validator("database_url")
    @classmethod
    def postgres_only(cls, value):
        if not value.get_secret_value().startswith("postgresql+psycopg://"):
            raise ValueError("Use a postgresql+psycopg:// database URL")
        return value

    @classmethod
    def from_env(cls):
        return cls(
            database_url=os.environ["RIP_DATABASE_URL"], model_directory=os.environ["RIP_MODEL_DIR"]
        )


class Telemetry(StrictModel):
    timestamp: Minute
    service_id: Service
    request_rate_rps: Metric
    latency_p50_ms: Metric
    latency_p95_ms: Metric
    error_rate: Metric
    cpu_utilisation_pct: Metric
    memory_utilisation_pct: Metric
    dependency_latency_ms: Metric


class Ingest(StrictModel):
    samples: list[Telemetry] = Field(min_length=1, max_length=1000)


class IngestResult(StrictModel):
    inserted: int
    unchanged: int


class Predict(StrictModel):
    service_id: Service
    timestamp: Minute


class Prediction(StrictModel):
    id: UUID
    service_id: Service
    timestamp: datetime
    produced_at: datetime
    available_as_of: datetime
    model_id: str
    model_name: str
    model_sha256: str
    feature_version: str
    threshold: float
    probability: float
    decision: Literal["elevated-risk", "not-elevated-risk"]
    window_start: datetime
    window_end: datetime


def telemetry_frame(records: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(records, columns=TELEMETRY_COLUMNS)
    frame.timestamp = pd.to_datetime(frame.timestamp, utc=True)
    frame.service_id = frame.service_id.astype("string")
    for name in TELEMETRY_COLUMNS[2:]:
        frame[name] = frame[name].astype("float64")
    validate_telemetry(frame)
    return frame
