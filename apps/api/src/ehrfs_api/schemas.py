"""Stable HTTP request and response contracts."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CursorPage[T](ApiModel):
    data: list[T]
    next_cursor: str | None = None
    total: int = Field(ge=0)


class ProblemDetail(ApiModel):
    type: str
    title: str
    status: int
    detail: str
    instance: str
    code: str
    correlation_id: str


class SessionRequest(ApiModel):
    persona: Literal["engineer", "steward", "researcher", "operator"]


class SessionResponse(ApiModel):
    actor: dict[str, str]
    csrf_token: str
    expires_in_seconds: int


class RunRequest(ApiModel):
    batch_id: str = Field(min_length=1, max_length=200)
    form_version: str = Field(min_length=1, max_length=100)
    form_id: str | None = Field(default=None, max_length=200)
    establishment_id: str | None = Field(default=None, max_length=100)
    source_system_id: str | None = Field(default=None, max_length=200)
    response_object_key: str | None = Field(default=None, max_length=1000)
    patient_pseudonym: str | None = Field(default=None, max_length=200)
    mapping_release_id: str | None = None


class ReplayRequest(ApiModel):
    quarantine_id: UUID
    mapping_release_id: str


class MappingApprovalRequest(ApiModel):
    comment: str = Field(min_length=3, max_length=1000)


class UploadValidationResponse(ApiModel):
    filename: str
    media_type: str
    size_bytes: int
    checksum_sha256: str
    object_key: str
    accepted: bool


class EvidenceAccessRequest(ApiModel):
    bucket: str = Field(min_length=1, max_length=100)
    key: str = Field(min_length=1, max_length=1000)
    expires_seconds: int = Field(default=300, ge=1, le=900)


class JsonObject(ApiModel):
    data: dict[str, Any]
