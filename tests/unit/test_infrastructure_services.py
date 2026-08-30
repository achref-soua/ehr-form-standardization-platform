from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import polars as pl
import pytest
from botocore.exceptions import ClientError
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker
from testcontainers.community.postgres import PostgresContainer

from ehrfs.config import Settings
from ehrfs.demo import (
    DEMO_MAPPING_V3,
    demo_mapping_artifact,
    ensure_demo_artifacts,
    reset_demo,
    seed_demo,
)
from ehrfs.domain.enums import AnswerState
from ehrfs.domain.errors import DomainError
from ehrfs.domain.identity import deterministic_uuid, sha256_hex
from ehrfs.domain.models import CanonicalAnswerEvent, EvidenceReference
from ehrfs.ingestion.cda import extract_cda_sections
from ehrfs.lineage.graph import LineageEdge, LineageGraph, LineageNode
from ehrfs.mapping.models import UnitRule
from ehrfs.omop.publisher import OmopFact, OmopTable
from ehrfs.omop.vocabulary import FILE_COLUMNS, inspect_athena_snapshot, load_athena_snapshot
from ehrfs.orchestration import worker
from ehrfs.orchestration.jobs import DurableJob, JobRepository
from ehrfs.security.signing import ReleaseSigner
from ehrfs.standardization.conversion import convert_unit, normalize_source_value
from ehrfs.storage.database import create_engine, create_schema, session_scope
from ehrfs.storage.objects import S3ObjectStore, StoredObject
from ehrfs.storage.parquet import CanonicalParquetWriter
from ehrfs.storage.tables import (
    FormVersionRow,
    MappingReleaseRow,
    OmopConceptRow,
    OmopConditionOccurrenceRow,
    OmopMeasurementRow,
    OmopNoteNlpRow,
    OmopNoteRow,
    OmopObservationRow,
    PipelineJobRow,
    QuarantineRow,
    VocabularyImportRow,
)

POSTGRES_IMAGE = (
    "postgres:18-bookworm@sha256:1c59e2c3c818eaa0f0628f695b36e7c9e362d6b219b36a54a32df645cbd7e1af"
)


@pytest.fixture(scope="module")
def postgres_settings() -> Iterator[Settings]:
    with PostgresContainer(image=POSTGRES_IMAGE, driver="psycopg") as postgres:
        yield Settings(
            environment="test",
            database_url=postgres.get_connection_url(),
            database_sslmode="disable",
            session_secret="test-session-secret-with-at-least-32-bytes",
            csrf_secret="test-csrf-secret-with-at-least-32-bytes",  # gitleaks:allow
            pseudonymization_key="test-pseudonym-secret-with-at-least-32-bytes",  # gitleaks:allow
        )


def _factory(settings: Settings) -> sessionmaker[Session]:
    engine = create_engine(settings)
    create_schema(engine)
    return sessionmaker(engine, expire_on_commit=False)


def _event(evidence: EvidenceReference, fixed_time: datetime, index: int) -> CanonicalAnswerEvent:
    return CanonicalAnswerEvent(
        event_id=deterministic_uuid("parquet", str(index)),
        establishment_id="site-a",
        patient_pseudonym=f"patient-{index}",
        encounter_pseudonym=f"encounter-{index}",
        form_id="form",
        form_version="1",
        source_fingerprint="a" * 64,
        compatibility_fingerprint="b" * 64,
        item_path="Q1",
        group_instance="group-0",
        state=AnswerState.PRESENT,
        value=f"value-{index}",
        raw_value={"value": index},
        unit="kg",
        authored_at=fixed_time,
        evidence=(evidence,),
    )


def test_cda_lineage_conversion_and_parquet(
    tmp_path: Path,
    evidence: EvidenceReference,
    fixed_time: datetime,
) -> None:
    cda = b"""<ClinicalDocument xmlns='urn:hl7-org:v3'><component><section>
      <title> Allergies </title><text>Penicilline <content>urticaire</content></text>
      </section><section><text>Sans titre</text></section><section />
      </component></ClinicalDocument>"""
    sections = extract_cda_sections(cda)
    assert sections[0].title == "Allergies"
    assert sections[0].text == "Penicilline urticaire"
    assert sections[1].title == "Untitled section"
    with pytest.raises(DomainError, match="well-formed XML"):
        extract_cda_sections(b"<broken")

    nodes = (
        LineageNode(node_id="raw", kind="raw", label="Raw"),
        LineageNode(node_id="canonical", kind="canonical", label="Canonical"),
    )
    graph = LineageGraph(
        nodes=nodes,
        edges=(LineageEdge(source_node_id="raw", target_node_id="canonical", relation="maps"),),
    )
    assert graph.nodes[0].node_id == "raw"
    with pytest.raises(ValidationError, match="unique"):
        LineageGraph(nodes=(nodes[0], nodes[0]), edges=())
    with pytest.raises(ValidationError, match="existing"):
        LineageGraph(
            nodes=nodes,
            edges=(LineageEdge(source_node_id="missing", target_node_id="raw", relation="bad"),),
        )
    with pytest.raises(ValidationError, match="acyclic"):
        LineageGraph(
            nodes=nodes,
            edges=(
                LineageEdge(source_node_id="raw", target_node_id="canonical", relation="next"),
                LineageEdge(source_node_id="canonical", target_node_id="raw", relation="back"),
            ),
        )
    diamond = LineageGraph(
        nodes=(
            LineageNode(node_id="left", kind="raw", label="Left"),
            LineageNode(node_id="right", kind="raw", label="Right"),
            LineageNode(node_id="joined", kind="canonical", label="Joined"),
        ),
        edges=(
            LineageEdge(source_node_id="left", target_node_id="joined", relation="feeds"),
            LineageEdge(source_node_id="right", target_node_id="joined", relation="feeds"),
        ),
    )
    assert len(diamond.edges) == 2

    assert normalize_source_value(True) == "true"
    assert normalize_source_value(False) == "false"
    assert normalize_source_value(" padded ") == "padded"
    rule = UnitRule(source_unit="g", target_unit="kg", multiplier="0.001")
    assert convert_unit(2500, rule).as_tuple().exponent == -1
    with pytest.raises(TypeError, match="Boolean"):
        convert_unit(True, rule)
    with pytest.raises(ValueError, match="finite"):
        convert_unit("not-a-number", rule)
    with pytest.raises(ValueError, match="non-finite"):
        convert_unit("Infinity", rule)

    with pytest.raises(ValueError, match="at least one"):
        CanonicalParquetWriter(tmp_path, partition_rows=0)
    writer = CanonicalParquetWriter(tmp_path, partition_rows=2)
    partitions = writer.write(
        (_event(evidence, fixed_time, index) for index in range(3)),
        establishment_id="site-a",
        batch_id="batch-a",
        fingerprint="fingerprint-a",
    )
    assert [partition.row_count for partition in partitions] == [2, 1]
    assert all(len(partition.checksum_sha256) == 64 for partition in partitions)
    frame = pl.read_parquet(partitions[0].path)
    assert frame["patient_pseudonym"].to_list() == ["patient-0", "patient-1"]
    assert (
        writer.write((), establishment_id="site-a", batch_id="empty", fingerprint="fingerprint-a")
        == ()
    )


def test_signer_round_trip_and_key_type_rejection() -> None:
    payload = b"immutable release"
    signer = ReleaseSigner.generate()
    signed = signer.sign(payload)
    private = ReleaseSigner.from_private_pem(signer.private_pem())
    public = ReleaseSigner.from_public_pem(signer.public_pem())
    assert private.key_id == public.key_id == signed.signing_key_id
    assert public.verify(payload, signed.signature_base64)
    assert not public.verify(payload + b"tampered", signed.signature_base64)
    assert not public.verify(payload, "not-base64")
    with pytest.raises(RuntimeError, match="private key"):
        public.private_pem()
    with pytest.raises(RuntimeError, match="private key"):
        public.sign(payload)

    private_rsa = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_rsa_pem = private_rsa.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_rsa_pem = private_rsa.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    with pytest.raises(TypeError, match="Ed25519 private"):
        ReleaseSigner.from_private_pem(private_rsa_pem)
    with pytest.raises(TypeError, match="Ed25519 public"):
        ReleaseSigner.from_public_pem(public_rsa_pem)


class FakeS3Client:
    def __init__(self) -> None:
        self.bucket_exists = False
        self.object_exists = False
        self.error_code = "404"
        self.created: list[str] = []
        self.put: dict[str, Any] | None = None

    def head_bucket(self, **kwargs: Any) -> dict[str, Any]:
        if not self.bucket_exists:
            raise ClientError({"Error": {"Code": self.error_code}}, "HeadBucket")
        return {"Bucket": kwargs["Bucket"]}

    def create_bucket(self, **kwargs: Any) -> None:
        self.created.append(str(kwargs["Bucket"]))
        self.bucket_exists = True

    def put_bucket_versioning(self, **kwargs: Any) -> None:
        assert kwargs["VersioningConfiguration"]["Status"] == "Enabled"

    def head_object(self, **_kwargs: Any) -> dict[str, Any]:
        if not self.object_exists:
            raise ClientError({"Error": {"Code": self.error_code}}, "HeadObject")
        return {"ContentLength": 5, "ContentType": "text/plain"}

    def put_object(self, **kwargs: Any) -> None:
        self.put = kwargs
        self.object_exists = True

    def get_object(self, **_kwargs: Any) -> dict[str, Any]:
        return {"Body": BytesIO(b"value")}

    def generate_presigned_url(self, *_args: Any, **kwargs: Any) -> str:
        return f"https://signed.invalid/{kwargs['ExpiresIn']}"


def test_s3_content_addressing_and_presigned_bounds() -> None:
    settings = Settings()
    client = FakeS3Client()
    store = S3ObjectStore(settings, client=cast(Any, client))
    store.ensure_bucket("raw")
    assert client.created == ["raw"]
    store.ensure_bucket("raw")

    stored = store.put_immutable(
        bucket="raw", namespace="batch-a", content=b"value", media_type="text/plain"
    )
    assert client.put is not None
    assert client.put["Metadata"]["sha256"] == stored.checksum_sha256
    existing = store.put_immutable(
        bucket="raw", namespace="batch-a", content=b"value", media_type="text/plain"
    )
    assert existing == stored
    assert store.read(bucket="raw", key=stored.key) == b"value"
    assert store.signed_download_url(
        bucket="raw", key=stored.key, expires=timedelta(seconds=900)
    ).endswith("/900")
    for seconds in (0, 901):
        with pytest.raises(ValueError, match="between 1 and 900"):
            store.signed_download_url(
                bucket="raw", key=stored.key, expires=timedelta(seconds=seconds)
            )

    failing = FakeS3Client()
    failing.error_code = "AccessDenied"
    failing_store = S3ObjectStore(settings, client=cast(Any, failing))
    with pytest.raises(ClientError):
        failing_store.ensure_bucket("raw")
    with pytest.raises(ClientError):
        failing_store.put_immutable(
            bucket="raw", namespace="batch", content=b"value", media_type="text/plain"
        )


@pytest.mark.integration
def test_job_leases_retry_terminal_failure_and_recovery(postgres_settings: Settings) -> None:
    factory = _factory(postgres_settings)
    repository = JobRepository()
    now = datetime(2026, 8, 29, 10, 0, tzinfo=UTC)
    with session_scope(factory) as session:
        reset_demo(session)
        job_id = repository.enqueue(
            session,
            job_type="pipeline.run",
            payload={"form_version": "3"},
            idempotency_key="job-lease-test",
            correlation_id="correlation",
            now=now,
        )
        duplicate = repository.enqueue(
            session,
            job_type="pipeline.run",
            payload={"form_version": "3"},
            idempotency_key="job-lease-test",
            correlation_id="different",
            now=now,
        )
        assert duplicate == job_id
        with pytest.raises(DomainError, match="different job type or payload"):
            repository.enqueue(
                session,
                job_type="pipeline.run",
                payload={"form_version": "different"},
                idempotency_key="job-lease-test",
                correlation_id="different",
                now=now,
            )

    with session_scope(factory) as session:
        claimed = repository.claim(session, worker_id="worker-a", now=now, lease_seconds=60)
        assert claimed is not None
        assert claimed.id == job_id
        assert repository.claim(session, worker_id="worker-b", now=now, lease_seconds=60) is None
        assert not repository.heartbeat(
            session, job_id=job_id, worker_id="wrong", now=now, lease_seconds=60
        )
        assert repository.heartbeat(
            session,
            job_id=job_id,
            worker_id="worker-a",
            now=now + timedelta(seconds=1),
            lease_seconds=60,
        )
        assert not repository.complete(
            session, job_id=job_id, worker_id="wrong", now=now + timedelta(seconds=2)
        )
        assert repository.fail(
            session,
            job_id=job_id,
            worker_id="worker-a",
            now=now + timedelta(seconds=2),
            error="retryable",
            retry_delay_seconds=2,
        )
        assert not repository.fail(
            session,
            job_id=job_id,
            worker_id="worker-a",
            now=now,
            error="not leased",
            retry_delay_seconds=0,
        )

    with session_scope(factory) as session:
        retry = repository.claim(
            session, worker_id="worker-a", now=now + timedelta(seconds=4), lease_seconds=60
        )
        assert retry is not None and retry.attempts == 2
        assert repository.complete(
            session, job_id=job_id, worker_id="worker-a", now=now + timedelta(seconds=5)
        )

        terminal_id = repository.enqueue(
            session,
            job_type="bad",
            payload={},
            idempotency_key="terminal-failure",
            correlation_id="terminal",
            now=now,
            maximum_attempts=1,
        )
        terminal = repository.claim(
            session, worker_id="worker-a", now=now + timedelta(seconds=5), lease_seconds=1
        )
        assert terminal is not None and terminal.id == terminal_id
        assert repository.recover_expired(session, now=now + timedelta(seconds=7)) == 1
        terminal = repository.claim(
            session, worker_id="worker-a", now=now + timedelta(seconds=7), lease_seconds=1
        )
        assert terminal is None
        row = session.get(PipelineJobRow, terminal_id)
        assert row is not None
        row.status = "RUNNING"
        row.leased_by = "worker-a"
        assert repository.fail(
            session,
            job_id=terminal_id,
            worker_id="worker-a",
            now=now + timedelta(seconds=8),
            error="x" * 5000,
            retry_delay_seconds=0,
        )
        assert row.status == "FAILED"
        assert len(row.last_error or "") == 4000


def _durable_job(session: Session, job_type: str, payload: dict[str, Any]) -> DurableJob:
    job_id = uuid4()
    created_at = datetime(2026, 8, 29, 10, 0, tzinfo=UTC)
    leased_until = datetime(2026, 8, 29, 10, 1, tzinfo=UTC)
    session.add(
        PipelineJobRow(
            id=job_id,
            job_type=job_type,
            status="RUNNING",
            idempotency_key=f"worker-test-{job_id}",
            payload_json=payload,
            correlation_id="worker-test",
            attempts=1,
            maximum_attempts=3,
            available_at=created_at,
            leased_until=leased_until,
            leased_by="worker-test",
            heartbeat_at=created_at,
            created_at=created_at,
            started_at=created_at,
        )
    )
    session.flush()
    return DurableJob(
        id=job_id,
        job_type=job_type,
        payload=payload,
        correlation_id="worker-test",
        attempts=1,
        maximum_attempts=3,
        leased_until=leased_until,
        created_at=created_at,
    )


class MemoryObjectStore:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    def put_immutable(
        self, *, bucket: str, namespace: str, content: bytes, media_type: str
    ) -> StoredObject:
        checksum = sha256_hex(content)
        key = f"{namespace}/{checksum[:2]}/{checksum}"
        self.objects[(bucket, key)] = content
        return StoredObject(bucket, key, checksum, len(content), media_type)

    def read(self, *, bucket: str, key: str) -> bytes:
        return self.objects[(bucket, key)]


@pytest.mark.integration
def test_worker_processes_supported_jobs_and_rejects_ambiguity(
    postgres_settings: Settings,
) -> None:
    factory = _factory(postgres_settings)
    release_store = MemoryObjectStore()
    signer = ReleaseSigner.generate()
    pipeline_settings = postgres_settings.model_copy(
        update={
            "demo_mode": True,
            "pseudonymization_key": "pipeline-test-pseudonymization-key-32-bytes",
        }
    )
    now = datetime(2026, 8, 29, 10, 0, tzinfo=UTC)
    with session_scope(factory) as session:
        seed_demo(session, reset=True)
        ensure_demo_artifacts(
            session,
            cast(Any, release_store),
            signer,
            raw_bucket=pipeline_settings.s3_raw_bucket,
            mapping_bucket=pipeline_settings.s3_mapping_bucket,
            research_bucket=pipeline_settings.s3_research_bucket,
        )
        quarantine = session.scalar(select(QuarantineRow))
        assert quarantine is not None
        worker._process(session, _durable_job(session, "documents.ocr", {}), now=now)
        worker._process(
            session,
            _durable_job(session, "pipeline.run", {"form_version": "3", "batch_id": "worker-v3"}),
            now=now,
            object_store=cast(Any, release_store),
            settings=pipeline_settings,
            signer=signer,
        )
        before_v4 = session.scalar(select(func.count()).select_from(QuarantineRow)) or 0
        worker._process(
            session,
            _durable_job(session, "pipeline.run", {"form_version": "4", "batch_id": "worker-v4"}),
            now=now,
            object_store=cast(Any, release_store),
            settings=pipeline_settings,
            signer=signer,
        )
        after_v4 = session.scalar(select(func.count()).select_from(QuarantineRow)) or 0
        assert after_v4 == before_v4 + 1
        with pytest.raises(ValueError, match="Unsupported"):
            worker._process(session, _durable_job(session, "unexpected", {}), now=now)
        with pytest.raises(ValueError, match="unknown quarantine"):
            worker._process(
                session,
                _durable_job(
                    session,
                    "pipeline.replay",
                    {
                        "quarantine_id": str(uuid4()),
                        "mapping_release_id": "mapping_2026_08_v3",
                    },
                ),
                now=now,
            )
        worker._process(
            session,
            _durable_job(
                session,
                "pipeline.replay",
                {
                    "quarantine_id": str(quarantine.id),
                    "mapping_release_id": "mapping_2026_08_v3",
                },
            ),
            now=now,
            object_store=cast(Any, release_store),
        )
        assert quarantine.status == "RESOLVED"

    with session_scope(factory) as session:
        repository = JobRepository()
        run_id = repository.enqueue(
            session,
            job_type="documents.ocr",
            payload={"document_id": "document-482"},
            idempotency_key="run-worker-once",
            correlation_id="once",
            now=now,
        )
    worker.STOP_REQUESTED = False
    assert worker.run_worker(postgres_settings, once=True) == 1
    with session_scope(factory) as session:
        row = session.get(PipelineJobRow, run_id)
        assert row is not None and row.status == "SUCCEEDED"


@pytest.mark.integration
def test_worker_persists_every_supported_omop_domain(postgres_settings: Settings) -> None:
    factory = _factory(postgres_settings)
    occurred_at = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    tables: tuple[OmopTable, ...] = (
        "observation",
        "measurement",
        "condition_occurrence",
        "note",
        "note_nlp",
    )
    with session_scope(factory) as session:
        person_id = worker._person_id(session, "p-domain-routing")
        identifiers: dict[str, int] = {}
        for table in tables:
            fact = OmopFact(
                fact_id=deterministic_uuid("domain-routing", table),
                table=table,
                person_source_value="p-domain-routing",
                concept_id=2_000_001,
                event_date=occurred_at.date(),
                event_datetime=occurred_at,
                value_as_number=(Decimal("72.5") if table == "measurement" else None),
                value_as_string=(
                    "Evidence-linked synthetic narrative"
                    if table in {"observation", "note", "note_nlp"}
                    else None
                ),
                unit_source_value="kg" if table == "measurement" else None,
                source_value=f"synthetic-{table}",
                clinical_event_id=deterministic_uuid("clinical-domain-routing", table),
            )
            identifiers[table] = worker._persist_omop_fact(session, fact, person_id=person_id)
        session.flush()
        assert session.get(OmopObservationRow, identifiers["observation"]) is not None
        assert session.get(OmopMeasurementRow, identifiers["measurement"]) is not None
        assert (
            session.get(OmopConditionOccurrenceRow, identifiers["condition_occurrence"]) is not None
        )
        assert session.get(OmopNoteRow, identifiers["note"]) is not None
        note_nlp = session.get(OmopNoteNlpRow, identifiers["note_nlp"])
        assert note_nlp is not None and session.get(OmopNoteRow, note_nlp.note_id) is not None
    worker._request_stop(15, SimpleNamespace())
    assert worker.STOP_REQUESTED
    worker.STOP_REQUESTED = False


@pytest.mark.integration
def test_worker_signer_mapping_selection_and_lease_fail_closed(
    postgres_settings: Settings,
    tmp_path: Path,
) -> None:
    signer = ReleaseSigner.generate()
    private_key = tmp_path / "worker-signing-key.pem"
    private_key.write_bytes(signer.private_pem())
    loaded = worker._load_signer(
        postgres_settings.model_copy(update={"signing_private_key_path": private_key})
    )
    assert loaded.key_id == signer.key_id
    generated = worker._load_signer(
        postgres_settings.model_copy(update={"signing_private_key_path": tmp_path / "missing"})
    )
    assert generated.key_id
    with pytest.raises(RuntimeError, match="signing key"):
        worker._load_signer(
            postgres_settings.model_copy(
                update={
                    "demo_mode": False,
                    "auto_create_schema": False,
                    "signing_private_key_path": tmp_path / "missing-production",
                }
            )
        )
    with pytest.raises(RuntimeError, match="before test-stage"):
        worker._require_active_lease(False, "test-stage")
    worker._require_active_lease(True, "test-stage")
    assert worker._source_text(None, 10) is None

    factory = _factory(postgres_settings)
    store = MemoryObjectStore()
    with session_scope(factory) as session:
        seed_demo(session, reset=True)
        ensure_demo_artifacts(
            session,
            cast(Any, store),
            signer,
            raw_bucket=postgres_settings.s3_raw_bucket,
            mapping_bucket=postgres_settings.s3_mapping_bucket,
            research_bucket=postgres_settings.s3_research_bucket,
        )
        form = session.scalar(select(FormVersionRow).where(FormVersionRow.version == "3"))
        assert form is not None
        assert (
            worker._released_mapping_for_form(
                session,
                cast(Any, store),
                bucket=postgres_settings.s3_mapping_bucket,
                form=form,
                signer=signer,
                requested_release_id=DEMO_MAPPING_V3,
            )
            is not None
        )
        release = session.get(MappingReleaseRow, DEMO_MAPPING_V3)
        assert release is not None
        original_key = release.artifact_object_key
        release.artifact_object_key = "missing-object"
        assert (
            worker._released_mapping_for_form(
                session,
                cast(Any, store),
                bucket=postgres_settings.s3_mapping_bucket,
                form=form,
                signer=signer,
                requested_release_id=None,
            )
            is None
        )
        invalid = demo_mapping_artifact(signer).model_copy(update={"signature_base64": "bad"})
        stored_invalid = store.put_immutable(
            bucket=postgres_settings.s3_mapping_bucket,
            namespace="test/invalid-mapping",
            content=invalid.model_dump_json().encode(),
            media_type="application/json",
        )
        release.artifact_object_key = stored_invalid.key
        assert (
            worker._released_mapping_for_form(
                session,
                cast(Any, store),
                bucket=postgres_settings.s3_mapping_bucket,
                form=form,
                signer=signer,
                requested_release_id=None,
            )
            is None
        )
        release.artifact_object_key = original_key
        first_person = worker._person_id(session, "p-existing-person")
        assert worker._person_id(session, "p-existing-person") == first_person


@pytest.mark.integration
def test_worker_unknown_and_ambiguous_forms_create_explicit_failures(
    postgres_settings: Settings,
) -> None:
    factory = _factory(postgres_settings)
    store = MemoryObjectStore()
    now = datetime(2026, 8, 30, 14, 0, tzinfo=UTC)
    with session_scope(factory) as session:
        seed_demo(session, reset=True)
        unknown = _durable_job(
            session,
            "pipeline.run",
            {
                "form_version": "999",
                "form_id": "MISSING",
                "establishment_id": "site-missing",
                "batch_id": "unknown-explicit",
            },
        )
        with pytest.raises(RuntimeError, match="immutable object storage"):
            worker._process(session, unknown, now=now)
        worker._process(session, unknown, now=now, object_store=cast(Any, store))
        session.flush()
        explicit = session.scalar(select(QuarantineRow).where(QuarantineRow.job_id == unknown.id))
        assert explicit is not None and explicit.form_id == "MISSING"

        form = session.scalar(select(FormVersionRow).where(FormVersionRow.version == "3"))
        assert form is not None
        duplicate = FormVersionRow(
            establishment_id="site-b",
            form_id=form.form_id,
            family=form.family,
            version=form.version,
            title=form.title,
            source_fingerprint="f" * 64,
            compatibility_fingerprint="e" * 64,
            mapping_status="RELEASED",
            definition_json=form.definition_json,
            created_at=now,
        )
        session.add(duplicate)
        session.flush()
        ambiguous = _durable_job(
            session, "pipeline.run", {"form_version": "3", "batch_id": "ambiguous"}
        )
        with pytest.raises(ValueError, match="AMBIGUOUS_FORM_VERSION"):
            worker._process(session, ambiguous, now=now, object_store=cast(Any, store))

        scoped = _durable_job(
            session,
            "pipeline.run",
            {
                "form_version": "3",
                "form_id": form.form_id,
                "establishment_id": form.establishment_id,
            },
        )
        with pytest.raises(RuntimeError, match="Pipeline execution requires"):
            worker._process(session, scoped, now=now)


def test_session_scope_rolls_back_and_closes(postgres_settings: Settings) -> None:
    factory = _factory(postgres_settings)
    with pytest.raises(RuntimeError, match="rollback"), session_scope(factory) as session:
        session.add(
            PipelineJobRow(
                job_type="test",
                status="QUEUED",
                idempotency_key="rollback-test",
                payload_json={},
                correlation_id="rollback",
                attempts=0,
                maximum_attempts=1,
                available_at=datetime.now(UTC),
                created_at=datetime.now(UTC),
            )
        )
        raise RuntimeError("rollback")
    with session_scope(factory) as session:
        assert (
            session.scalar(
                select(PipelineJobRow).where(PipelineJobRow.idempotency_key == "rollback-test")
            )
            is None
        )


def _write_athena_fixture(root: Path) -> None:
    rows: dict[str, list[tuple[str, ...]]] = {
        "DOMAIN.csv": [("Observation", "Observation", "9200001")],
        "VOCABULARY.csv": [("EHRFS_TEST", "Test vocabulary", "project", "1", "9200002")],
        "CONCEPT_CLASS.csv": [("Test", "Test class", "9200003")],
        "CONCEPT.csv": [
            (
                "9200010",
                "Integration standard concept",
                "Observation",
                "EHRFS_TEST",
                "Test",
                "S",
                "INTEGRATION-1",
                "2026-01-01",
                "2099-12-31",
                "",
            )
        ],
    }
    root.mkdir()
    for name, values in rows.items():
        lines = ["\t".join(FILE_COLUMNS[name]), *("\t".join(row) for row in values)]
        (root / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.mark.integration
def test_official_omop_schema_and_atomic_athena_import(
    postgres_settings: Settings,
    tmp_path: Path,
) -> None:
    factory = _factory(postgres_settings)
    source = tmp_path / "athena"
    _write_athena_fixture(source)
    snapshot = inspect_athena_snapshot(
        source,
        release_id="athena-integration-1",
        vocabulary_version="integration-1",
    )

    with session_scope(factory) as session:
        table_count = session.scalar(
            text(
                """
                SELECT count(*) FROM information_schema.tables
                WHERE table_schema = 'omop' AND table_type = 'BASE TABLE'
                """
            )
        )
        assert table_count == 39
        assert load_athena_snapshot(
            session,
            source,
            snapshot,
            loaded_by="integration-test",
            loaded_at=datetime(2026, 8, 29, 12, 0, tzinfo=UTC),
            batch_size=1,
        )

    with session_scope(factory) as session:
        concept_count = session.scalar(select(func.count()).select_from(OmopConceptRow)) or 0
        assert concept_count >= 1
        imported = session.get(VocabularyImportRow, "athena-integration-1")
        assert imported is not None
        assert imported.standard_concept_count == 1
        assert not load_athena_snapshot(
            session,
            source,
            snapshot,
            loaded_by="integration-test",
        )
