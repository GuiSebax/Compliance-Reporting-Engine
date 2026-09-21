"""FastAPI application entrypoint / app factory."""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.core.config import get_settings
from app.domain.exceptions import DomainError
from app.infrastructure.logging import configure_logging, get_logger
from app.infrastructure.storage import s3_client

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if settings.s3_endpoint_url:
        # Only auto-provision the bucket for a local/demo endpoint
        # (LocalStack); a real AWS bucket is provisioned out-of-band.
        s3_client.ensure_bucket_exists()
    logger.info("application_startup", environment=settings.environment)
    yield
    logger.info("application_shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Compliance Reporting Engine",
        description=(
            "Auditable batch processing engine for periodic financial "
            "compliance reports: ingestion, versioned rule engine, "
            "aggregation, and traceable report export."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # demo-friendly default; scope to the real frontend origin in prod
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next):
        request_id = str(uuid.uuid4())
        start = time.perf_counter()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            response = await call_next(request)
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            logger.info(
                "http_request",
                method=request.method,
                path=request.url.path,
                duration_ms=duration_ms,
            )
            structlog.contextvars.unbind_contextvars("request_id")
        response.headers["X-Request-ID"] = request_id
        return response

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError):
        from fastapi.responses import JSONResponse

        logger.warning("domain_error", error=str(exc), path=request.url.path)
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    app.include_router(api_router)

    return app


app = create_app()
