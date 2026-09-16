"""Application factory. Liveness survives dependency failure; readiness proves serving state."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

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
            repository = Repository(engine, artifact)
            repository.check_database()
            repository.register_model()
            app.state.repository = repository
        except Exception:
            logger.exception("Serving dependencies failed initialisation")
        yield
        if engine is not None:
            engine.dispose()

    app = FastAPI(
        title="Reliability Intelligence — local advisory inference",
        version="0.2.0",
        lifespan=lifespan,
    )

    @app.exception_handler(DomainError)
    async def domain_error(request, error):
        return JSONResponse(
            status_code=error.status,
            content={"error": {"code": error.code, "message": error.message, **error.context}},
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, error):
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
    def ingest(payload: Ingest):
        return repository().ingest([row.model_dump() for row in payload.samples])

    @app.post("/predictions", response_model=Prediction, status_code=201)
    def predict(payload: Predict, response: Response):
        result, created = repository().predict(payload.service_id, payload.timestamp)
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
