"""Immutable research release manifests and membership."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from ehrfs.domain.models import DomainModel


class ResearchReleaseManifest(DomainModel):
    schema_version: Literal["1.0"] = "1.0"
    release_id: str
    parent_release_id: str | None = None
    source_manifest_checksums: tuple[str, ...]
    connector_version: str
    canonical_schema_version: str
    mapping_release_id: str
    rule_release_id: str
    vocabulary_release_id: str
    model_version: str | None = None
    container_image: str
    created_at: datetime
    output_checksum_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class ReleaseMembership(DomainModel):
    research_release_id: str
    clinical_event_id: UUID
    omop_table: str
    omop_fact_id: UUID
