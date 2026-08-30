"""Application factory with security, correlation, and observability middleware."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session, sessionmaker
from starlette.middleware.base import RequestResponseEndpoint

from ehrfs.config import Settings, get_settings
from ehrfs.demo import ensure_demo_artifacts, seed_demo
from ehrfs.domain.errors import DomainError
from ehrfs.observability import API_LATENCY, API_REQUESTS, configure_logging, configure_tracing
from ehrfs.security.signing import ReleaseSigner
from ehrfs.storage.database import create_engine, create_schema
from ehrfs.storage.objects import S3ObjectStore
from ehrfs_api.routes import router
from ehrfs_api.schemas import ProblemDetail

logger = structlog.get_logger()


def _load_or_create_signer(settings: Settings) -> ReleaseSigner:
    private_path: Path = settings.signing_private_key_path
    if private_path.exists():
        return ReleaseSigner.from_private_pem(private_path.read_bytes())
    if not settings.demo_mode:
        msg = "A release-signing private key is required outside demo mode"
        raise RuntimeError(msg)
    return ReleaseSigner.generate()


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)
    engine = create_engine(resolved_settings)
    factory = sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        if resolved_settings.auto_create_schema:
            create_schema(engine)
        signer = _load_or_create_signer(resolved_settings)
        application.state.release_signer = signer
        with Session(engine) as session:
            seed_demo(session)
            if resolved_settings.demo_mode:
                ensure_demo_artifacts(
                    session,
                    application.state.object_store,
                    signer,
                    raw_bucket=resolved_settings.s3_raw_bucket,
                    mapping_bucket=resolved_settings.s3_mapping_bucket,
                    research_bucket=resolved_settings.s3_research_bucket,
                )
            session.commit()
        yield
        application.state.tracer_provider.shutdown()
        engine.dispose()

    application = FastAPI(
        title="EHR Form Standardization Platform API",
        version="0.1.0",
        description=(
            "Deterministic, evidence-linked reference implementation using synthetic data. "
            "Not a certified clinical system."
        ),
        lifespan=lifespan,
        openapi_url="/api/v1/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
    )
    application.state.settings = resolved_settings
    application.state.session_factory = factory
    application.state.object_store = S3ObjectStore(resolved_settings)
    application.state.tracer_provider = configure_tracing(application, engine, resolved_settings)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[str(resolved_settings.web_origin).rstrip("/")],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Idempotency-Key", "X-Correlation-ID", "X-CSRF-Token"],
    )

    @application.middleware("http")
    async def request_context(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        correlation_id = request.headers.get("X-Correlation-ID", str(uuid4()))
        request.state.correlation_id = correlation_id
        started = perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        metric_path = getattr(route, "path", request.url.path)
        API_LATENCY.labels(metric_path, request.method).observe(perf_counter() - started)
        API_REQUESTS.labels(metric_path, request.method, str(response.status_code)).inc()
        response.headers["X-Correlation-ID"] = correlation_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'"
        )
        return response

    @application.exception_handler(DomainError)
    async def domain_error_handler(request: Request, error: DomainError) -> JSONResponse:
        problem = ProblemDetail(
            type=f"https://ehrfs.local/problems/{error.code.lower()}",
            title=error.code.replace("_", " ").title(),
            status=error.status_code,
            detail=error.message,
            instance=str(request.url.path),
            code=error.code,
            correlation_id=request.state.correlation_id,
        )
        return JSONResponse(
            problem.model_dump(),
            status_code=error.status_code,
            media_type="application/problem+json",
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        problem = ProblemDetail(
            type="https://ehrfs.local/problems/validation-error",
            title="Validation Error",
            status=422,
            detail=str(error),
            instance=str(request.url.path),
            code="VALIDATION_ERROR",
            correlation_id=request.state.correlation_id,
        )
        return JSONResponse(
            problem.model_dump(),
            status_code=422,
            media_type="application/problem+json",
        )

    @application.exception_handler(HTTPException)
    async def http_error_handler(request: Request, error: HTTPException) -> JSONResponse:
        problem = ProblemDetail(
            type=f"https://ehrfs.local/problems/http-{error.status_code}",
            title={
                401: "Authentication Required",
                403: "Access Denied",
                404: "Resource Not Found",
                409: "Conflict",
                422: "Request Rejected",
            }.get(error.status_code, "Request Failed"),
            status=error.status_code,
            detail=str(error.detail),
            instance=str(request.url.path),
            code=f"HTTP_{error.status_code}",
            correlation_id=request.state.correlation_id,
        )
        return JSONResponse(
            problem.model_dump(),
            status_code=error.status_code,
            media_type="application/problem+json",
            headers=error.headers,
        )

    application.include_router(router)
    return application


app = create_app()
