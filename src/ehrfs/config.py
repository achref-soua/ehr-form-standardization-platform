"""Validated runtime configuration."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import AnyHttpUrl, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="EHRFS_",
        extra="ignore",
        case_sensitive=False,
    )

    environment: Literal["development", "test", "production"] = "development"
    deployment_mode: Literal["central", "site"] = "central"
    demo_mode: bool = True
    auto_create_schema: bool = True
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"  # noqa: S104
    api_port: int = Field(default=8000, ge=1, le=65535)
    web_origin: AnyHttpUrl = AnyHttpUrl("http://localhost:3000")
    database_url: str = "postgresql+psycopg://ehrfs_app:ehrfs_app@localhost:5432/ehrfs"
    database_sslmode: Literal[
        "disable", "allow", "prefer", "require", "verify-ca", "verify-full"
    ] = "disable"
    s3_endpoint: AnyHttpUrl = AnyHttpUrl("http://localhost:9000")
    s3_region: str = "eu-west-3"
    s3_access_key: str = "ehrfs-local"
    s3_secret_key: str = "change-me-local-only"
    s3_use_ssl: bool = False
    s3_raw_bucket: str = "ehrfs-raw"
    s3_canonical_bucket: str = "ehrfs-canonical"
    s3_document_bucket: str = "ehrfs-documents"
    s3_mapping_bucket: str = "ehrfs-mapping-releases"
    s3_research_bucket: str = "ehrfs-research-releases"
    signing_private_key_path: Path = Path(".local/keys/ehrfs_signing_key")
    signing_public_key_path: Path = Path(".local/keys/ehrfs_signing_key.pub")
    session_secret: str = "replace-with-at-least-32-random-characters"
    csrf_secret: str = "replace-with-at-least-32-random-characters"
    pseudonymization_key: str = "replace-with-a-site-local-secret"
    job_lease_seconds: int = Field(default=60, ge=15, le=3600)
    job_heartbeat_seconds: int = Field(default=15, ge=5, le=300)
    partition_rows: int = Field(default=50_000, ge=100, le=1_000_000)
    upload_max_bytes: int = Field(default=25 * 1024 * 1024, ge=1024)
    small_cell_threshold: int = Field(default=10, ge=1)
    otel_exporter_otlp_endpoint: str | None = None
    ocr_endpoint: AnyHttpUrl = AnyHttpUrl("http://localhost:8081")
    ocr_confidence_threshold: float = Field(default=0.85, ge=0, le=1)
    clamav_host: str = "localhost"
    clamav_port: int = Field(default=3310, ge=1, le=65535)
    malware_scanner: Literal["auto", "clamav", "demo-noop"] = "auto"

    @model_validator(mode="after")
    def validate_security_defaults(self) -> Self:
        if not self.demo_mode:
            placeholders = {
                self.session_secret,
                self.csrf_secret,
                self.pseudonymization_key,
                self.s3_secret_key,
            }
            if any("replace" in value or "change-me" in value for value in placeholders):
                msg = "Placeholder secrets are allowed only when demo mode is enabled"
                raise ValueError(msg)
        if self.job_heartbeat_seconds >= self.job_lease_seconds:
            msg = "Job heartbeat must be shorter than the lease"
            raise ValueError(msg)
        if not self.demo_mode and self.auto_create_schema:
            msg = "Automatic schema creation is allowed only in demo mode"
            raise ValueError(msg)
        if not self.demo_mode and self.malware_scanner == "demo-noop":
            msg = "The no-op malware scanner is allowed only in demo mode"
            raise ValueError(msg)
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
