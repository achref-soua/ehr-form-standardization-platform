"""Versioned REST resources for the dashboard and external clients."""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import func, select
from sqlalchemy import text as sql_text

from ehrfs.domain.enums import RunStatus
from ehrfs.domain.identity import canonical_json_bytes, content_hash, sha256_hex
from ehrfs.federation.bundle import (
    SignedSiteSummary,
    SiteMetric,
    build_site_summary,
)
from ehrfs.mapping.models import MappingEntry, MappingReleaseArtifact, VocabularyRelease
from ehrfs.mapping.releases import create_mapping_release, verify_mapping_release
from ehrfs.orchestration.jobs import JobRepository
from ehrfs.security.scanning import scanner_for_upload
from ehrfs.security.signing import ReleaseSigner
from ehrfs.security.uploads import validate_upload
from ehrfs.storage.objects import ObjectStore
from ehrfs.storage.tables import (
    AuditEventRow,
    CatalogConceptRow,
    CoverageMetricRow,
    EstablishmentRow,
    FormVersionRow,
    LineageGraphRow,
    MappingDraftRow,
    MappingReleaseRow,
    OmopObservationRow,
    PipelineJobRow,
    QuarantineRow,
    ResearchReleaseRow,
    SourceSystemRow,
    WorkerHeartbeatRow,
)
from ehrfs_api.auth import (
    PERSONAS,
    Persona,
    create_session,
    get_actor,
    require_roles,
    validate_csrf,
)
from ehrfs_api.dependencies import DatabaseSession
from ehrfs_api.schemas import (
    CursorPage,
    EvidenceAccessRequest,
    MappingApprovalRequest,
    ReplayRequest,
    RunRequest,
    SessionRequest,
    SessionResponse,
    UploadValidationResponse,
)

router = APIRouter(prefix="/api/v1")
job_repository = JobRepository()
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)]


def _encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode()).decode().rstrip("=")


def _decode_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        value = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        offset = int(value)
    except (ValueError, UnicodeDecodeError) as error:
        raise HTTPException(status_code=422, detail="Invalid pagination cursor") from error
    if offset < 0:
        raise HTTPException(status_code=422, detail="Invalid pagination cursor")
    return offset


def _page(
    data: list[dict[str, Any]],
    *,
    total: int,
    offset: int,
    limit: int,
) -> CursorPage[dict[str, Any]]:
    next_cursor = _encode_cursor(offset + limit) if offset + limit < total else None
    return CursorPage(data=data, next_cursor=next_cursor, total=total)


@router.get("/session/personas")
def list_personas() -> list[dict[str, str]]:
    return [persona.model_dump() for persona in PERSONAS.values()]


@router.post("/session", response_model=SessionResponse)
def open_session(payload: SessionRequest, request: Request, response: Response) -> SessionResponse:
    settings = request.app.state.settings
    if not settings.demo_mode:
        raise HTTPException(status_code=404, detail="Demo authentication is disabled")
    persona = PERSONAS[payload.persona]
    token, csrf = create_session(persona, settings)
    response.set_cookie(
        "ehrfs_session",
        token,
        httponly=True,
        secure=settings.environment == "production",
        samesite="strict",
        max_age=8 * 60 * 60,
        path="/",
    )
    return SessionResponse(
        actor={"id": persona.id, "display_name": persona.display_name, "role": persona.role},
        csrf_token=csrf,
        expires_in_seconds=8 * 60 * 60,
    )


@router.get("/session/me")
def current_session(actor: Annotated[Persona, Depends(get_actor)]) -> dict[str, str]:
    return actor.model_dump()


@router.get("/establishments", response_model=CursorPage[dict[str, Any]])
def establishments(
    session: DatabaseSession,
    _actor: Annotated[Persona, Depends(get_actor)],
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> CursorPage[dict[str, Any]]:
    offset = _decode_cursor(cursor)
    total = session.scalar(select(func.count()).select_from(EstablishmentRow)) or 0
    rows = session.scalars(
        select(EstablishmentRow).order_by(EstablishmentRow.id).offset(offset).limit(limit)
    )
    data = [
        {"id": row.id, "name": row.name, "region": row.region, "active": row.active} for row in rows
    ]
    return _page(data, total=total, offset=offset, limit=limit)


@router.get("/sources")
def sources(
    session: DatabaseSession, _actor: Annotated[Persona, Depends(get_actor)]
) -> list[dict[str, Any]]:
    rows = session.scalars(select(SourceSystemRow).order_by(SourceSystemRow.establishment_id))
    return [
        {
            "id": str(row.id),
            "establishment_id": row.establishment_id,
            "source_key": row.source_key,
            "family": row.family,
            "version": row.version,
        }
        for row in rows
    ]


@router.get("/batches")
def batches(
    session: DatabaseSession, _actor: Annotated[Persona, Depends(get_actor)]
) -> list[dict[str, Any]]:
    rows = session.scalars(select(PipelineJobRow).order_by(PipelineJobRow.created_at.desc()))
    return [
        {
            "id": str(row.id),
            "batch_id": row.payload_json.get("batch_id"),
            "form_version": row.payload_json.get("form_version"),
            "status": row.status,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.get("/forms")
def forms(
    session: DatabaseSession, _actor: Annotated[Persona, Depends(get_actor)]
) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(FormVersionRow).order_by(FormVersionRow.form_id, FormVersionRow.version)
    )
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        record = grouped.setdefault(
            row.form_id,
            {"form_id": row.form_id, "title": row.title, "family": row.family, "versions": []},
        )
        record["versions"].append(row.version)
    return list(grouped.values())


@router.get("/form-versions")
def form_versions(
    session: DatabaseSession,
    _actor: Annotated[Persona, Depends(get_actor)],
) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(FormVersionRow).order_by(FormVersionRow.created_at, FormVersionRow.version)
    )
    return [
        {
            "id": str(row.id),
            "establishment_id": row.establishment_id,
            "form_id": row.form_id,
            "family": row.family,
            "version": row.version,
            "title": row.title,
            "source_fingerprint": row.source_fingerprint,
            "compatibility_fingerprint": row.compatibility_fingerprint,
            "mapping_status": row.mapping_status,
            "definition": row.definition_json,
        }
        for row in rows
    ]


@router.get("/form-versions/{form_version_id}")
def form_version(
    form_version_id: UUID,
    session: DatabaseSession,
    _actor: Annotated[Persona, Depends(get_actor)],
) -> dict[str, Any]:
    row = session.get(FormVersionRow, form_version_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Form version not found")
    return {
        "id": str(row.id),
        "version": row.version,
        "source_fingerprint": row.source_fingerprint,
        "compatibility_fingerprint": row.compatibility_fingerprint,
        "mapping_status": row.mapping_status,
        "definition": row.definition_json,
    }


@router.get("/fingerprints")
def fingerprints(
    session: DatabaseSession, _actor: Annotated[Persona, Depends(get_actor)]
) -> list[dict[str, Any]]:
    rows = session.scalars(select(FormVersionRow).order_by(FormVersionRow.version))
    return [
        {
            "form_id": row.form_id,
            "version": row.version,
            "source": row.source_fingerprint,
            "compatibility": row.compatibility_fingerprint,
            "released": row.mapping_status == "RELEASED",
        }
        for row in rows
    ]


@router.get("/mappings")
def mappings(
    session: DatabaseSession, _actor: Annotated[Persona, Depends(get_actor)]
) -> list[dict[str, Any]]:
    rows = session.execute(select(MappingDraftRow, FormVersionRow).join(FormVersionRow)).all()
    return [
        {
            "id": str(draft.id),
            "status": draft.status,
            "authored_by": draft.authored_by,
            "approved_by": draft.approved_by,
            "form_id": form.form_id,
            "form_version": form.version,
            "payload": draft.payload_json,
        }
        for draft, form in rows
    ]


@router.get("/mapping-releases")
def mapping_releases(
    session: DatabaseSession,
    _actor: Annotated[Persona, Depends(get_actor)],
) -> list[dict[str, Any]]:
    rows = session.scalars(select(MappingReleaseRow).order_by(MappingReleaseRow.approved_at.desc()))
    return [
        {
            "release_id": row.release_id,
            "parent_release_id": row.parent_release_id,
            "checksum_sha256": row.checksum_sha256,
            "signing_key_id": row.signing_key_id,
            "authored_by": row.authored_by,
            "approved_by": row.approved_by,
            "approved_at": row.approved_at,
        }
        for row in rows
    ]


@router.post("/mappings/{draft_id}/approve", dependencies=[Depends(validate_csrf)])
def approve_mapping(  # noqa: PLR0917 -- FastAPI injects explicit boundary dependencies
    draft_id: UUID,
    payload: MappingApprovalRequest,
    request: Request,
    session: DatabaseSession,
    actor: Annotated[Persona, Depends(require_roles("steward"))],
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    draft = session.get(MappingDraftRow, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Mapping draft not found")
    if draft.authored_by == actor.id:
        raise HTTPException(status_code=409, detail="Authors cannot approve their own mapping")
    request_checksum = content_hash(payload.model_dump(mode="json"))
    if draft.status == "APPROVED":
        prior_audit = session.scalar(
            select(AuditEventRow).where(
                AuditEventRow.action == "mapping.release.approved",
                AuditEventRow.metadata_json["draft_id"].as_string() == str(draft.id),
                AuditEventRow.metadata_json["idempotency_key"].as_string() == idempotency_key,
            )
        )
        if prior_audit is not None:
            if prior_audit.metadata_json.get("request_checksum") != request_checksum:
                raise HTTPException(
                    status_code=409, detail="Idempotency key was reused with a different request"
                )
            prior_release = session.get(MappingReleaseRow, prior_audit.resource_id)
            if prior_release is not None:
                return {
                    "release_id": prior_release.release_id,
                    "checksum_sha256": prior_release.checksum_sha256,
                    "verified": True,
                }
        raise HTTPException(status_code=409, detail="Mapping draft is already approved")
    signer: ReleaseSigner = request.app.state.release_signer
    try:
        entry = MappingEntry.model_validate(draft.payload_json["entry"])
        vocabulary = VocabularyRelease.model_validate(draft.payload_json["vocabulary_release"])
    except (KeyError, ValueError) as error:
        raise HTTPException(
            status_code=422, detail="Mapping draft is not release-complete"
        ) from error
    approved_at = datetime.now(UTC)
    artifact = create_mapping_release(
        parent_release_id="mapping_2026_08_v3",
        vocabulary_release=vocabulary,
        entries=(entry,),
        authored_by=draft.authored_by,
        approved_by=actor.id,
        approved_at=approved_at,
        signer=signer,
    )
    serialized = canonical_json_bytes(artifact.model_dump(mode="json"))
    checksum = sha256_hex(serialized)
    object_store = cast(ObjectStore, request.app.state.object_store)
    try:
        stored = object_store.put_immutable(
            bucket=request.app.state.settings.s3_mapping_bucket,
            namespace="mapping-releases",
            content=serialized,
            media_type="application/json",
        )
    except Exception as error:  # object-store failures must stop publication
        raise HTTPException(
            status_code=503, detail="Mapping artifact store is unavailable"
        ) from error
    session.add(
        MappingReleaseRow(
            release_id=artifact.release_id,
            parent_release_id="mapping_2026_08_v3",
            artifact_object_key=stored.key,
            checksum_sha256=checksum,
            signature_base64=artifact.signature_base64,
            signing_key_id=artifact.signing_key_id,
            authored_by=draft.authored_by,
            approved_by=actor.id,
            approved_at=approved_at,
        )
    )
    draft.status = "APPROVED"
    draft.approved_by = actor.id
    form = session.get(FormVersionRow, draft.form_version_id)
    if form is not None:
        form.mapping_status = "RELEASED"
    session.add(
        AuditEventRow(
            occurred_at=datetime.now(UTC),
            actor_id=actor.id,
            action="mapping.release.approved",
            resource_type="mapping_release",
            resource_id=artifact.release_id,
            correlation_id=request.state.correlation_id,
            metadata_json={
                "draft_id": str(draft.id),
                "idempotency_key": idempotency_key,
                "request_checksum": request_checksum,
                "review_comment": payload.comment,
            },
        )
    )
    return {
        "release_id": artifact.release_id,
        "checksum_sha256": checksum,
        "verified": True,
    }


@router.get("/mapping-releases/{release_id}/verify")
def verify_mapping_release_artifact(
    release_id: str,
    request: Request,
    session: DatabaseSession,
    _actor: Annotated[Persona, Depends(get_actor)],
) -> dict[str, Any]:
    release = session.get(MappingReleaseRow, release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="Mapping release not found")
    object_store = cast(ObjectStore, request.app.state.object_store)
    try:
        artifact = object_store.read(
            bucket=request.app.state.settings.s3_mapping_bucket,
            key=release.artifact_object_key,
        )
    except Exception:  # noqa: BLE001 -- unavailable evidence is an expected verification result
        return {
            "release_id": release_id,
            "verified": False,
            "reason": "Artifact unavailable",
            "checksum_sha256": release.checksum_sha256,
        }
    signer: ReleaseSigner = request.app.state.release_signer
    try:
        typed_artifact = MappingReleaseArtifact.model_validate_json(artifact)
    except ValueError:
        typed_artifact = None
    verified = bool(
        typed_artifact is not None
        and sha256_hex(artifact) == release.checksum_sha256
        and typed_artifact.release_id == release.release_id
        and typed_artifact.signature_base64 == release.signature_base64
        and typed_artifact.signing_key_id == release.signing_key_id
        and verify_mapping_release(typed_artifact, signer)
    )
    return {
        "release_id": release_id,
        "verified": verified,
        "reason": None if verified else "Checksum, key identity, or signature mismatch",
        "checksum_sha256": release.checksum_sha256,
        "signing_key_id": release.signing_key_id,
    }


@router.post("/evidence/access-url", dependencies=[Depends(validate_csrf)])
def evidence_access_url(
    payload: EvidenceAccessRequest,
    request: Request,
    session: DatabaseSession,
    actor: Annotated[Persona, Depends(get_actor)],
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    settings = request.app.state.settings
    allowed_buckets = {
        settings.s3_raw_bucket,
        settings.s3_document_bucket,
        settings.s3_mapping_bucket,
        settings.s3_research_bucket,
    }
    if payload.bucket not in allowed_buckets:
        raise HTTPException(status_code=422, detail="Evidence bucket is not allowed")
    object_store = cast(ObjectStore, request.app.state.object_store)
    url = object_store.signed_download_url(
        bucket=payload.bucket,
        key=payload.key,
        expires=timedelta(seconds=payload.expires_seconds),
    )
    session.add(
        AuditEventRow(
            occurred_at=datetime.now(UTC),
            actor_id=actor.id,
            action="evidence.access_url.created",
            resource_type="object",
            resource_id=f"{payload.bucket}/{payload.key}",
            correlation_id=request.state.correlation_id,
            metadata_json={
                "expires_seconds": payload.expires_seconds,
                "idempotency_key": idempotency_key,
            },
        )
    )
    return {"url": url, "expires_in_seconds": payload.expires_seconds}


@router.get("/pipeline-runs")
def pipeline_runs(
    session: DatabaseSession,
    _actor: Annotated[Persona, Depends(get_actor)],
) -> list[dict[str, Any]]:
    rows = session.scalars(select(PipelineJobRow).order_by(PipelineJobRow.created_at.desc()))
    return [
        {
            "id": str(row.id),
            "job_type": row.job_type,
            "status": row.status,
            "payload": row.payload_json,
            "attempts": row.attempts,
            "maximum_attempts": row.maximum_attempts,
            "created_at": row.created_at,
            "started_at": row.started_at,
            "finished_at": row.finished_at,
            "last_error": row.last_error,
            "correlation_id": row.correlation_id,
        }
        for row in rows
    ]


@router.post("/pipeline-runs", dependencies=[Depends(validate_csrf)])
def create_pipeline_run(
    payload: RunRequest,
    request: Request,
    session: DatabaseSession,
    actor: Annotated[Persona, Depends(require_roles("engineer", "operator"))],
    idempotency_key: IdempotencyKey,
) -> dict[str, str]:
    now = datetime.now(UTC)
    job_id = job_repository.enqueue(
        session,
        job_type="pipeline.run",
        payload=payload.model_dump(mode="json"),
        idempotency_key=f"api:pipeline:{idempotency_key}",
        correlation_id=request.state.correlation_id,
        now=now,
    )
    session.add(
        AuditEventRow(
            occurred_at=now,
            actor_id=actor.id,
            action="pipeline.run.queued",
            resource_type="pipeline_job",
            resource_id=str(job_id),
            correlation_id=request.state.correlation_id,
            metadata_json={"batch_id": payload.batch_id},
        )
    )
    return {"job_id": str(job_id), "status": RunStatus.QUEUED}


@router.get("/quarantine")
def quarantine(
    session: DatabaseSession, _actor: Annotated[Persona, Depends(get_actor)]
) -> list[dict[str, Any]]:
    rows = session.scalars(select(QuarantineRow).order_by(QuarantineRow.created_at.desc()))
    return [
        {
            "id": str(row.id),
            "job_id": str(row.job_id),
            "establishment_id": row.establishment_id,
            "form_id": row.form_id,
            "item_path": row.item_path,
            "reason": row.reason,
            "status": row.status,
            "evidence": row.evidence_json,
            "context": row.context_json,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.post("/replays", dependencies=[Depends(validate_csrf)])
def replay(
    payload: ReplayRequest,
    request: Request,
    session: DatabaseSession,
    actor: Annotated[Persona, Depends(require_roles("engineer", "operator"))],
    idempotency_key: IdempotencyKey,
) -> dict[str, str]:
    record = session.get(QuarantineRow, payload.quarantine_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Quarantine record not found")
    release = session.get(MappingReleaseRow, payload.mapping_release_id)
    if release is None:
        raise HTTPException(status_code=422, detail="Mapping release not found")
    now = datetime.now(UTC)
    job_id = job_repository.enqueue(
        session,
        job_type="pipeline.replay",
        payload={
            "quarantine_id": str(record.id),
            "mapping_release_id": release.release_id,
            "source_job_id": str(record.job_id),
        },
        idempotency_key=f"api:replay:{idempotency_key}",
        correlation_id=request.state.correlation_id,
        now=now,
    )
    record.status = "REPLAY_QUEUED"
    session.add(
        AuditEventRow(
            occurred_at=now,
            actor_id=actor.id,
            action="quarantine.replay.queued",
            resource_type="quarantine_record",
            resource_id=str(record.id),
            correlation_id=request.state.correlation_id,
            metadata_json={"job_id": str(job_id), "mapping_release_id": release.release_id},
        )
    )
    return {"job_id": str(job_id), "status": RunStatus.QUEUED}


@router.get("/documents")
def documents(_actor: Annotated[Persona, Depends(get_actor)]) -> list[dict[str, Any]]:
    return [
        {
            "id": "document-482",
            "title": "Synthetic allergy scan",
            "media_type": "image/png",
            "synthetic": True,
            "text": "Allergie à la pénicilline avec urticaire.",
            "model_version": "paddleocr-golden/1.0",
            "confidence": 0.97,
            "candidate": {
                "substance": "Penicillin",
                "reaction": "Urticaria",
                "assertion": "PRESENT",
                "status": "EVIDENCE_LINKED_CANDIDATE",
            },
            "bounding_boxes": [[54, 96, 612, 142]],
        }
    ]


@router.post(
    "/documents", response_model=UploadValidationResponse, dependencies=[Depends(validate_csrf)]
)
async def upload_document(  # noqa: PLR0917 - FastAPI injects the explicit HTTP contract.
    request: Request,
    session: DatabaseSession,
    actor: Annotated[Persona, Depends(require_roles("engineer", "steward"))],
    upload: Annotated[UploadFile, File()],
    idempotency_key: IdempotencyKey,
    synthetic_fixture: Annotated[bool, Header(alias="X-Synthetic-Fixture")] = False,
) -> UploadValidationResponse:
    content = await upload.read(request.app.state.settings.upload_max_bytes + 1)
    filename = validate_upload(
        content,
        filename=upload.filename or "upload",
        media_type=upload.content_type or "application/octet-stream",
        maximum_bytes=request.app.state.settings.upload_max_bytes,
    )
    scanner_for_upload(request.app.state.settings, synthetic_fixture=synthetic_fixture).scan(
        content
    )
    object_store = cast(ObjectStore, request.app.state.object_store)
    try:
        stored = object_store.put_immutable(
            bucket=request.app.state.settings.s3_document_bucket,
            namespace="documents",
            content=content,
            media_type=upload.content_type or "application/octet-stream",
        )
    except Exception as error:
        raise HTTPException(status_code=503, detail="Document store is unavailable") from error
    session.add(
        AuditEventRow(
            occurred_at=datetime.now(UTC),
            actor_id=actor.id,
            action="document.uploaded",
            resource_type="object",
            resource_id=f"{stored.bucket}/{stored.key}",
            correlation_id=request.state.correlation_id,
            metadata_json={
                "media_type": stored.media_type,
                "size_bytes": stored.size_bytes,
                "idempotency_key": idempotency_key,
                "synthetic_fixture": synthetic_fixture,
            },
        )
    )
    return UploadValidationResponse(
        filename=filename,
        media_type=upload.content_type or "application/octet-stream",
        size_bytes=len(content),
        checksum_sha256=sha256_hex(content),
        object_key=stored.key,
        accepted=True,
    )


@router.post("/ocr", dependencies=[Depends(validate_csrf)])
def request_ocr(
    request: Request,
    session: DatabaseSession,
    _actor: Annotated[Persona, Depends(require_roles("engineer", "steward"))],
    idempotency_key: IdempotencyKey,
) -> dict[str, str]:
    job_id = job_repository.enqueue(
        session,
        job_type="documents.ocr",
        payload={"document_id": "document-482", "mode": "local-only"},
        idempotency_key=f"api:ocr:{idempotency_key}",
        correlation_id=request.state.correlation_id,
        now=datetime.now(UTC),
    )
    return {"job_id": str(job_id), "status": RunStatus.QUEUED}


@router.get("/omop/releases")
def omop_releases(
    session: DatabaseSession,
    _actor: Annotated[Persona, Depends(get_actor)],
) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(ResearchReleaseRow).order_by(ResearchReleaseRow.created_at.desc())
    )
    return [
        {
            "release_id": row.release_id,
            "parent_release_id": row.parent_release_id,
            "mapping_release_id": row.mapping_release_id,
            "checksum_sha256": row.checksum_sha256,
            "published_count": row.published_count,
            "quarantined_count": row.quarantined_count,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.get("/omop/releases/{release_id}/verify")
def verify_research_release_artifact(
    release_id: str,
    request: Request,
    session: DatabaseSession,
    _actor: Annotated[Persona, Depends(get_actor)],
) -> dict[str, Any]:
    release = session.get(ResearchReleaseRow, release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="Research release not found")
    object_store = cast(ObjectStore, request.app.state.object_store)
    try:
        artifact = object_store.read(
            bucket=request.app.state.settings.s3_research_bucket,
            key=release.artifact_object_key,
        )
    except Exception:  # noqa: BLE001 -- verification reports unavailable evidence safely
        return {
            "release_id": release_id,
            "verified": False,
            "reason": "Artifact unavailable",
            "checksum_sha256": release.checksum_sha256,
        }
    verified = sha256_hex(artifact) == release.checksum_sha256
    return {
        "release_id": release_id,
        "verified": verified,
        "reason": None if verified else "Artifact checksum mismatch",
        "checksum_sha256": release.checksum_sha256,
    }


@router.get("/omop/events")
def omop_events(
    session: DatabaseSession, _actor: Annotated[Persona, Depends(get_actor)]
) -> list[dict[str, Any]]:
    rows = session.scalars(select(OmopObservationRow).order_by(OmopObservationRow.observation_id))
    return [
        {
            "table": "observation",
            "id": row.observation_id,
            "person_id": row.person_id,
            "concept_id": row.observation_concept_id,
            "date": row.observation_date,
            "datetime": row.observation_datetime,
            "value_as_string": row.value_as_string,
            "source_value": row.observation_source_value,
            "research_release_id": "release_2026_08",
        }
        for row in rows
    ]


@router.get("/catalog/concepts")
def catalog_concepts(
    session: DatabaseSession,
    _actor: Annotated[Persona, Depends(get_actor)],
    query: str | None = None,
) -> list[dict[str, Any]]:
    statement = select(CatalogConceptRow)
    if query:
        statement = statement.where(CatalogConceptRow.display_name.ilike(f"%{query}%"))
    rows = session.scalars(statement.order_by(CatalogConceptRow.display_name))
    return [
        {
            "concept_key": row.concept_key,
            "display_name": row.display_name,
            "definition": row.definition,
            "vocabulary_id": row.vocabulary_id,
            "concept_code": row.concept_code,
            "limitations": row.limitations,
            "updated_at": row.updated_at,
        }
        for row in rows
    ]


@router.get("/catalog/coverage")
def catalog_coverage(
    session: DatabaseSession,
    _actor: Annotated[Persona, Depends(get_actor)],
    concept_key: str = "allergy-history",
) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(CoverageMetricRow)
        .where(CoverageMetricRow.concept_key == concept_key)
        .order_by(CoverageMetricRow.establishment_id)
    )
    return [
        {
            "establishment_id": row.establishment_id,
            "period_start": row.period_start,
            "period_end": row.period_end,
            "eligible_count": row.eligible_count,
            "recorded_count": row.recorded_count,
            "usable_count": row.usable_count,
            "positive_count": row.positive_count,
            "completion": row.completion,
            "usable_coverage": row.usable_coverage,
            "prevalence": row.prevalence,
            "method": row.method,
            "quality_status": row.quality_status,
            "research_release_id": row.research_release_id,
        }
        for row in rows
    ]


@router.get("/catalog/releases/compare")
def compare_catalog_releases(
    session: DatabaseSession,
    _actor: Annotated[Persona, Depends(get_actor)],
    concept_key: str = "allergy-history",
) -> list[dict[str, Any]]:
    rows = session.execute(
        select(ResearchReleaseRow, CoverageMetricRow)
        .join(
            CoverageMetricRow,
            CoverageMetricRow.research_release_id == ResearchReleaseRow.release_id,
        )
        .where(CoverageMetricRow.concept_key == concept_key)
        .order_by(ResearchReleaseRow.created_at, CoverageMetricRow.establishment_id)
    )
    releases: dict[str, dict[str, Any]] = {}
    for release, metric in rows:
        summary = releases.setdefault(
            release.release_id,
            {
                "release_id": release.release_id,
                "parent_release_id": release.parent_release_id,
                "published_count": release.published_count,
                "quarantined_count": release.quarantined_count,
                "created_at": release.created_at,
                "sites": [],
            },
        )
        summary["sites"].append(
            {
                "establishment_id": metric.establishment_id,
                "recorded_count": metric.recorded_count,
                "usable_count": metric.usable_count,
                "positive_count": metric.positive_count,
            }
        )
    return list(releases.values())


@router.post("/site-summaries/export", dependencies=[Depends(validate_csrf)])
def export_site_summary(
    request: Request,
    session: DatabaseSession,
    actor: Annotated[Persona, Depends(require_roles("operator"))],
    idempotency_key: IdempotencyKey,
    establishment_id: str = "site-a",
) -> SignedSiteSummary:
    latest_release = session.scalar(
        select(ResearchReleaseRow).order_by(ResearchReleaseRow.created_at.desc()).limit(1)
    )
    if latest_release is None:
        raise HTTPException(status_code=404, detail="No research release is available")
    rows = session.scalars(
        select(CoverageMetricRow).where(
            CoverageMetricRow.research_release_id == latest_release.release_id,
            CoverageMetricRow.establishment_id == establishment_id,
        )
    )
    metrics = tuple(
        SiteMetric(
            concept_key=row.concept_key,
            period_start=row.period_start,
            period_end=row.period_end,
            eligible_count=row.eligible_count,
            recorded_count=row.recorded_count,
            usable_count=row.usable_count,
            positive_count=row.positive_count,
        )
        for row in rows
    )
    if not metrics:
        raise HTTPException(status_code=404, detail="No aggregate metrics exist for this site")
    signer: ReleaseSigner = request.app.state.release_signer
    signed = build_site_summary(
        establishment_id=establishment_id,
        mapping_release_ids=(latest_release.mapping_release_id,),
        research_release_id=latest_release.release_id,
        generated_at=latest_release.created_at,
        metrics=metrics,
        threshold=request.app.state.settings.small_cell_threshold,
        signer=signer,
    )
    session.add(
        AuditEventRow(
            occurred_at=datetime.now(UTC),
            actor_id=actor.id,
            action="site_summary.exported",
            resource_type="site_summary",
            resource_id=f"{establishment_id}:{latest_release.release_id}",
            correlation_id=request.state.correlation_id,
            metadata_json={"metric_count": len(metrics), "idempotency_key": idempotency_key},
        )
    )
    return signed


@router.post("/site-summaries/import", dependencies=[Depends(validate_csrf)])
def import_site_summary(
    payload: SignedSiteSummary,
    request: Request,
    session: DatabaseSession,
    actor: Annotated[Persona, Depends(require_roles("operator"))],
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    bundle_payload = payload.bundle.model_dump(mode="json")
    serialized = canonical_json_bytes(bundle_payload)
    signer: ReleaseSigner = request.app.state.release_signer
    verified = (
        payload.payload_checksum_sha256 == content_hash(bundle_payload)
        and payload.signing_key_id == signer.key_id
        and signer.verify(serialized, payload.signature_base64)
    )
    if not verified:
        raise HTTPException(status_code=422, detail="Site summary signature is invalid")
    session.add(
        AuditEventRow(
            occurred_at=datetime.now(UTC),
            actor_id=actor.id,
            action="site_summary.imported",
            resource_type="site_summary",
            resource_id=(f"{payload.bundle.establishment_id}:{payload.bundle.research_release_id}"),
            correlation_id=request.state.correlation_id,
            metadata_json={
                "metric_count": len(payload.bundle.metrics),
                "idempotency_key": idempotency_key,
            },
        )
    )
    return {
        "accepted": True,
        "establishment_id": payload.bundle.establishment_id,
        "research_release_id": payload.bundle.research_release_id,
        "metric_count": len(payload.bundle.metrics),
    }


@router.get("/lineage")
def lineage(
    session: DatabaseSession,
    _actor: Annotated[Persona, Depends(get_actor)],
    root: str = "omop:observation:1",
) -> dict[str, Any]:
    graph = session.get(LineageGraphRow, root)
    if graph is None:
        raise HTTPException(status_code=404, detail="Lineage graph not found")
    return graph.graph_json


@router.get("/health")
def health(request: Request, session: DatabaseSession) -> dict[str, Any]:
    latest_worker = session.scalar(
        select(WorkerHeartbeatRow).order_by(WorkerHeartbeatRow.heartbeat_at.desc()).limit(1)
    )
    worker_status = "not observed"
    if latest_worker is not None:
        age = datetime.now(UTC) - latest_worker.heartbeat_at
        worker_status = (
            "ready" if latest_worker.status == "READY" and age < timedelta(seconds=10) else "stale"
        )
    return {
        "status": "healthy",
        "version": "0.1.0",
        "environment": request.app.state.settings.environment,
        "deployment_mode": request.app.state.settings.deployment_mode,
        "demo_mode": request.app.state.settings.demo_mode,
        "time": datetime.now(UTC),
        "components": {
            "api": "ready",
            "database": "ready",
            "object_store": "configured",
            "worker": worker_status,
            "ocr": "optional-profile",
        },
    }


@router.get("/health/live")
def liveness() -> dict[str, str]:
    return {"status": "alive", "version": "0.1.0"}


@router.get("/health/ready")
def readiness(request: Request, session: DatabaseSession) -> dict[str, Any]:
    try:
        session.execute(sql_text("SELECT 1"))
        database = "ready"
    except Exception as error:
        raise HTTPException(status_code=503, detail="Database readiness check failed") from error
    object_store = cast(ObjectStore, request.app.state.object_store)
    try:
        object_store.ready(bucket=request.app.state.settings.s3_raw_bucket)
        storage = "ready"
    except Exception as error:
        raise HTTPException(
            status_code=503, detail="Object-store readiness check failed"
        ) from error
    return {"status": "ready", "components": {"database": database, "object_store": storage}}


@router.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/audit")
def audit_events(
    session: DatabaseSession,
    _actor: Annotated[Persona, Depends(require_roles("operator", "steward"))],
) -> list[dict[str, Any]]:
    rows = session.scalars(select(AuditEventRow).order_by(AuditEventRow.occurred_at.desc()))
    return [
        {
            "id": str(row.id),
            "occurred_at": row.occurred_at,
            "actor_id": row.actor_id,
            "action": row.action,
            "resource_type": row.resource_type,
            "resource_id": row.resource_id,
            "correlation_id": row.correlation_id,
            "metadata": row.metadata_json,
        }
        for row in rows
    ]
