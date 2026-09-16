"""Application factory. Liveness survives dependency failure; readiness proves serving state."""

import logging
from contextlib import asynccontextmanager
from time import perf_counter
from typing import Literal

from fastapi import FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy.exc import SQLAlchemyError

from reliability_intelligence.monitoring.snapshots import history as snapshot_history
from reliability_intelligence.serving.artifact import load_artifact
from reliability_intelligence.serving.contracts import (
    Ingest,
    IngestResult,
    Minute,
    Predict,
    Prediction,
    Service,
    Settings,
)
from reliability_intelligence.serving.database import make_engine
from reliability_intelligence.serving.metrics import ApplicationMetrics, route_label
from reliability_intelligence.serving.repository import DomainError, Repository

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.repository = None
        app.state.startup_error = "configuration_unready"
        engine = None
        try:
            configured = settings or Settings.from_env()
            app.state.startup_error = "model_unready"
            artifact = load_artifact(configured.model_directory)
            app.state.startup_error = "database_unready"
            engine = make_engine(configured.database_url.get_secret_value())
            if configured.monitoring_reference is not None:
                app.state.startup_error = "reference_unready"
                from reliability_intelligence.monitoring.reference import load_reference

                load_reference(configured.monitoring_reference, artifact.metadata["id"])
            app.state.startup_error = "database_unready"
            repository = Repository(engine, artifact)
            repository.check_database()
            repository.register_model()
            app.state.repository = repository
        except Exception:
            dependency = (
                "model"
                if app.state.startup_error == "model_unready"
                else "database"
                if app.state.startup_error == "database_unready"
                else "other"
            )
            app.state.metrics.failures.labels(dependency).inc()
            logger.exception("Serving dependencies failed initialisation")
        yield
        if engine is not None:
            engine.dispose()

    app = FastAPI(
        title="Reliability Intelligence — local advisory inference",
        version="0.2.0",
        lifespan=lifespan,
    )

    app.state.metrics = ApplicationMetrics()
    metrics = app.state.metrics

    @app.middleware("http")
    async def observe(request, call_next):
        started = perf_counter()
        response = await call_next(request)
        route = route_label(request)
        method = (
            request.method
            if request.method in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
            else "OTHER"
        )
        metrics.http.labels(method, route, f"{response.status_code // 100}xx").inc()
        metrics.duration.labels(method, route).observe(perf_counter() - started)
        if response.status_code >= 400:
            metrics.rejections.labels(route).inc()
        if route == "/health/ready":
            metrics.readiness.set(int(response.status_code == 200))
        return response

    @app.get("/metrics", include_in_schema=False)
    def prometheus_metrics():
        return Response(
            generate_latest(metrics.registry), headers={"Content-Type": CONTENT_TYPE_LATEST}
        )

    @app.get("/monitoring/{kind}")
    def monitoring_history(
        kind: Literal["drift", "delayed"],
        start: Minute | None = None,
        end: Minute | None = None,
        limit: int = Query(100, ge=1, le=1000),
    ):
        if start is not None and end is not None and start >= end:
            raise DomainError("invalid_range", "start must precede end")
        return snapshot_history(repository().engine, kind, start, end, limit)

    @app.exception_handler(DomainError)
    async def domain_error(request, error):
        if error.status == 503:
            dependency = (
                "model"
                if error.code in {"inference_failed", "model_unready", "model_metadata_conflict"}
                else "database"
                if error.code in {"schema_unready", "database_unready"}
                else "other"
            )
            metrics.failures.labels(dependency).inc()
        if error.code == "incomplete_history":
            metrics.predictions.labels("incomplete_history").inc()
        if route_label(request) == "/telemetry":
            metrics.telemetry.labels("rejected").inc(getattr(request.state, "telemetry_rows", 0))
        return JSONResponse(
            status_code=error.status,
            content={"error": {"code": error.code, "message": error.message, **error.context}},
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, error):
        metrics.failures.labels("database").inc()
        if route_label(request) == "/telemetry":
            metrics.telemetry.labels("rejected").inc(getattr(request.state, "telemetry_rows", 0))
        logger.exception("Database request failed", exc_info=error)
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "database_unavailable",
                    "message": "Database operation failed; retry later",
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        if route_label(request) == "/telemetry" and isinstance(error.body, dict):
            samples = error.body.get("samples")
            if isinstance(samples, list):
                metrics.telemetry.labels("rejected").inc(len(samples))
        # Never echo untrusted input, non-JSON NaN values, or internal exception contexts.
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_request",
                    "message": "Request does not match the API contract",
                    "fields": [list(item["loc"]) for item in error.errors()],
                }
            },
        )

    def repository():
        if app.state.repository is None:
            raise DomainError(
                app.state.startup_error,
                "Serving dependencies are not ready; inspect server logs and restart after repair",
                503,
            )
        return app.state.repository

    @app.get("/health/live")
    def live():
        return {"status": "alive"}

    @app.get("/health/ready")
    def ready():
        repo = repository()
        repo.check_database()
        return {"status": "ready", "model_id": repo.artifact.metadata["id"]}

    @app.post("/telemetry", response_model=IngestResult)
    def ingest(payload: Ingest, request: Request):
        request.state.telemetry_rows = len(payload.samples)
        result = repository().ingest([row.model_dump() for row in payload.samples])
        for outcome in ("inserted", "unchanged"):
            metrics.telemetry.labels(outcome).inc(result[outcome])
        return result

    @app.post("/predictions", response_model=Prediction, status_code=201)
    def predict(payload: Predict, response: Response):
        with metrics.inference.time():
            result, created = repository().predict(payload.service_id, payload.timestamp)
        metrics.predictions.labels("created" if created else "reused").inc()
        response.status_code = 201 if created else 200
        return result

    @app.get("/predictions", response_model=list[Prediction])
    def history(
        service_id: Service | None = None,
        start: Minute | None = None,
        end: Minute | None = None,
        limit: int = Query(100, ge=1, le=1000),
    ):
        if start is not None and end is not None and start >= end:
            raise DomainError("invalid_range", "start must be earlier than exclusive end")
        return repository().history(service_id, start, end, limit)

    return app
