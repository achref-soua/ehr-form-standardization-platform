"""Metrics, tracing, and structured redaction at process boundaries."""

from __future__ import annotations

import logging
from collections.abc import Mapping, MutableMapping
from typing import Any, cast

import structlog
from fastapi import FastAPI
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import Counter, Gauge, Histogram
from sqlalchemy import Engine

from ehrfs.config import Settings

REDACTED = "[REDACTED]"
SENSITIVE_FRAGMENTS = frozenset(
    {
        "answer",
        "authorization",
        "clinical_text",
        "cookie",
        "patient",
        "person_source_value",
        "pseudonym",
        "secret",
        "session",
        "token",
    }
)

API_REQUESTS = Counter(
    "ehrfs_api_requests_total",
    "API requests by route, method, and response status",
    ("route", "method", "status"),
)
API_LATENCY = Histogram(
    "ehrfs_api_request_duration_seconds",
    "API request duration by route and method",
    ("route", "method"),
)
PIPELINE_EVENTS = Counter(
    "ehrfs_pipeline_events_total",
    "Pipeline outcomes without patient-level labels",
    ("stage", "outcome", "failure_code"),
)
WORKER_AVAILABLE = Gauge(
    "ehrfs_worker_available",
    "Whether a durable worker heartbeat is available",
)
CATALOG_FRESHNESS = Gauge(
    "ehrfs_catalog_freshness_seconds",
    "Seconds since the latest catalog update",
)
OCR_DURATION = Histogram(
    "ehrfs_ocr_duration_seconds",
    "Local OCR inference duration",
    ("device", "model"),
)
OCR_CONFIDENCE = Histogram(
    "ehrfs_ocr_span_confidence",
    "Local OCR evidence span confidence",
    ("device",),
    buckets=(0.5, 0.7, 0.8, 0.85, 0.9, 0.95, 0.98, 0.99, 1.0),
)


def _sensitive(key: object) -> bool:
    normalized = str(key).casefold()
    return any(fragment in normalized for fragment in SENSITIVE_FRAGMENTS)


def redact(value: Any) -> Any:
    """Recursively remove values whose keys can contain identity or clinical data."""
    if isinstance(value, Mapping):
        return {
            str(key): REDACTED if _sensitive(key) else redact(item) for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value


def _redact_event(
    _logger: Any, _method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    return cast(MutableMapping[str, Any], redact(event_dict))


def configure_logging(level: str) -> None:
    logging.basicConfig(format="%(message)s", level=level.upper())
    structlog.configure(
        processors=(
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redact_event,
            structlog.processors.JSONRenderer(sort_keys=True),
        ),
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def configure_tracing(application: FastAPI, engine: Engine, settings: Settings) -> TracerProvider:
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": "ehrfs-api",
                "service.version": "0.1.0",
                "deployment.environment.name": settings.environment,
            }
        )
    )
    if settings.otel_exporter_otlp_endpoint:
        exporter = OTLPSpanExporter(
            endpoint=settings.otel_exporter_otlp_endpoint,
            insecure=settings.environment != "production",
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))
    FastAPIInstrumentor.instrument_app(
        application,
        tracer_provider=provider,
        excluded_urls="/api/v1/health,/api/v1/metrics",
    )
    sqlalchemy_instrumentor = SQLAlchemyInstrumentor()
    if not sqlalchemy_instrumentor.is_instrumented_by_opentelemetry:
        sqlalchemy_instrumentor.instrument(engine=engine, tracer_provider=provider)
    return provider
