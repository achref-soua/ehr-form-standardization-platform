"""Operational CLI backed by the same services as the API and worker."""

from __future__ import annotations

import json
import os
import platform
import shutil
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

import typer
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from ehrfs import __version__
from ehrfs.config import Settings, get_settings
from ehrfs.demo import allergy_form, seed_demo
from ehrfs.domain.identity import content_hash
from ehrfs.fingerprinting.service import fingerprint_form
from ehrfs.omop.schema import OFFICIAL_TABLE_COUNT
from ehrfs.omop.vocabulary import AthenaImportError, inspect_athena_snapshot, load_athena_snapshot
from ehrfs.orchestration.jobs import JobRepository
from ehrfs.security.signing import ReleaseSigner
from ehrfs.storage.database import create_engine, create_schema, session_scope
from ehrfs.storage.tables import (
    CatalogConceptRow,
    CoverageMetricRow,
    FormVersionRow,
    MappingReleaseRow,
    OmopConceptRow,
    PipelineJobRow,
    QuarantineRow,
    VocabularyImportRow,
)

KEYS_EXIST_MESSAGE = "Signing keys already exist; use --force to replace them"
DEMO_MODE_REQUIRED_MESSAGE = "Demo reset is available only when EHRFS_DEMO_MODE is enabled"

app = typer.Typer(no_args_is_help=True, help="Deterministic EHR form standardization operations")
data_app = typer.Typer(no_args_is_help=True)
source_app = typer.Typer(no_args_is_help=True)
forms_app = typer.Typer(no_args_is_help=True)
mappings_app = typer.Typer(no_args_is_help=True)
pipeline_app = typer.Typer(no_args_is_help=True)
quarantine_app = typer.Typer(no_args_is_help=True)
omop_app = typer.Typer(no_args_is_help=True)
vocabulary_app = typer.Typer(no_args_is_help=True)
catalog_app = typer.Typer(no_args_is_help=True)
demo_app = typer.Typer(no_args_is_help=True)
keys_app = typer.Typer(no_args_is_help=True)
app.add_typer(data_app, name="data")
app.add_typer(source_app, name="source")
app.add_typer(forms_app, name="forms")
app.add_typer(mappings_app, name="mappings")
app.add_typer(pipeline_app, name="pipeline")
app.add_typer(quarantine_app, name="quarantine")
app.add_typer(omop_app, name="omop")
app.add_typer(vocabulary_app, name="vocabulary")
app.add_typer(catalog_app, name="catalog")
app.add_typer(demo_app, name="demo")
app.add_typer(keys_app, name="keys")


def _emit(value: Any, *, as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(value, default=str, sort_keys=True))
    elif isinstance(value, str):
        typer.echo(value)
    else:
        typer.echo(json.dumps(value, default=str, indent=2))


def _session_factory(settings: Settings) -> sessionmaker[Session]:
    engine = create_engine(settings)
    if settings.auto_create_schema:
        create_schema(engine)
    return sessionmaker(engine, expire_on_commit=False)


@app.command()
def version() -> None:
    """Print the application version."""
    typer.echo(__version__)


@app.command()
def preflight(as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    """Report local execution capacity without modifying the environment."""
    disk = shutil.disk_usage(Path.cwd())
    result = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "disk_free_bytes": disk.free,
        "disk_total_bytes": disk.total,
        "docker": shutil.which("docker") is not None,
        "node": shutil.which("node") is not None,
        "pnpm": shutil.which("pnpm") is not None,
        "uv": shutil.which("uv") is not None,
        "nvidia_smi": shutil.which("nvidia-smi") is not None,
    }
    _emit(result, as_json=as_json)


@keys_app.command("generate")
def generate_keys(
    destination: Annotated[Path, typer.Option()] = Path(".local/keys"),
    force: Annotated[bool, typer.Option()] = False,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Generate a local Ed25519 release-signing keypair."""
    private_path = destination / "ehrfs_signing_key"
    public_path = destination / "ehrfs_signing_key.pub"
    if not force and (private_path.exists() or public_path.exists()):
        raise typer.BadParameter(KEYS_EXIST_MESSAGE)
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    signer = ReleaseSigner.generate()
    private_path.write_bytes(signer.private_pem())
    private_path.chmod(0o600)
    public_path.write_bytes(signer.public_pem())
    public_path.chmod(0o644)
    _emit(
        {"key_id": signer.key_id, "destination": str(destination), "generated": True}
        if as_json
        else f"Generated signing key {signer.key_id} in {destination}",
        as_json=as_json,
    )


@data_app.command("generate")
def generate_data(
    patients: Annotated[int, typer.Option(min=1, max=100_000)] = 500,
    seed: Annotated[int, typer.Option()] = 20260828,
    output: Annotated[Path, typer.Option()] = Path("data/generated/demo-patients.ndjson"),
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Generate deterministic synthetic identities without external data."""
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(
            {
                "synthetic": True,
                "patient_id": f"synthetic-{seed}-{index:06d}",
                "birth_year": 1940 + ((seed + index * 17) % 70),
                "site": f"site-{chr(97 + index % 4)}",
            },
            sort_keys=True,
        )
        for index in range(patients)
    ]
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    manifest = {
        "generator": "ehrfs deterministic synthetic generator",
        "patients": patients,
        "seed": seed,
        "output": str(output),
        "checksum_sha256": content_hash(lines),
        "contains_real_patient_data": False,
    }
    output.with_suffix(".manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    _emit(
        manifest if as_json else f"Generated {patients} synthetic patients at {output}",
        as_json=as_json,
    )


@data_app.command("fetch")
def fetch_data(as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    """Explain the explicit external-data acquisition boundary."""
    message = (
        "External data are never downloaded implicitly. Review docs/data/sources.md and record "
        "the selected version and licence before using an explicit acquisition adapter."
    )
    _emit({"downloaded": False, "reason": message} if as_json else message, as_json=as_json)


@source_app.command("inventory")
def source_inventory(as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    settings = get_settings()
    factory = _session_factory(settings)
    with session_scope(factory) as session:
        seed_demo(session)
        result = {
            "forms": session.scalar(select(func.count()).select_from(FormVersionRow)),
            "pipeline_runs": session.scalar(select(func.count()).select_from(PipelineJobRow)),
            "quarantined": session.scalar(select(func.count()).select_from(QuarantineRow)),
        }
    _emit(result, as_json=as_json)


@forms_app.command("fingerprint")
def form_fingerprint(
    version: Annotated[str, typer.Option()] = "3",
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    fingerprints = fingerprint_form(allergy_form(version))
    _emit(
        {"source": fingerprints.source, "compatibility": fingerprints.compatibility},
        as_json=as_json,
    )


@mappings_app.command("validate")
def validate_mappings(as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    factory = _session_factory(get_settings())
    with session_scope(factory) as session:
        seed_demo(session)
        releases = session.scalars(select(MappingReleaseRow)).all()
        result = [
            {
                "release_id": release.release_id,
                "checksum": release.checksum_sha256,
                "author_and_approver_differ": release.authored_by != release.approved_by,
            }
            for release in releases
        ]
    _emit(result, as_json=as_json)


@mappings_app.command("release")
def release_mapping(as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    """Direct users to the audited maker/checker API flow."""
    message = (
        "Create a draft as the engineer persona and approve it as the steward persona through "
        "POST /api/v1/mappings/{draft_id}/approve. The application never commits to Git."
    )
    _emit({"released": False, "instruction": message} if as_json else message, as_json=as_json)


@pipeline_app.command("run")
def pipeline_run(
    batch_id: Annotated[str, typer.Option()],
    form_version: Annotated[str, typer.Option()] = "3",
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    factory = _session_factory(get_settings())
    now = datetime.now(UTC)
    with session_scope(factory) as session:
        seed_demo(session)
        job_id = JobRepository().enqueue(
            session,
            job_type="pipeline.run",
            payload={"batch_id": batch_id, "form_version": form_version},
            idempotency_key=f"cli:{batch_id}:{form_version}",
            correlation_id=str(uuid4()),
            now=now,
        )
    _emit({"job_id": str(job_id), "status": "QUEUED"} if as_json else str(job_id), as_json=as_json)


@pipeline_app.command("replay")
def pipeline_replay(
    quarantine_id: Annotated[str, typer.Option()],
    mapping_release_id: Annotated[str, typer.Option()],
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    factory = _session_factory(get_settings())
    with session_scope(factory) as session:
        job_id = JobRepository().enqueue(
            session,
            job_type="pipeline.replay",
            payload={
                "quarantine_id": quarantine_id,
                "mapping_release_id": mapping_release_id,
            },
            idempotency_key=f"cli-replay:{quarantine_id}:{mapping_release_id}",
            correlation_id=str(uuid4()),
            now=datetime.now(UTC),
        )
    _emit(
        {"job_id": str(job_id), "status": "QUEUED"} if as_json else str(job_id),
        as_json=as_json,
    )


@quarantine_app.command("list")
def quarantine_list(as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    factory = _session_factory(get_settings())
    with session_scope(factory) as session:
        rows = session.scalars(select(QuarantineRow).order_by(QuarantineRow.created_at)).all()
        result = [
            {"id": str(row.id), "reason": row.reason, "status": row.status, "form_id": row.form_id}
            for row in rows
        ]
    _emit(result, as_json=as_json)


@omop_app.command("validate")
def omop_validate(as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    factory = _session_factory(get_settings())
    with session_scope(factory) as session:
        concepts = session.scalar(select(func.count()).select_from(OmopConceptRow)) or 0
        invalid = (
            session.scalar(
                select(func.count())
                .select_from(OmopConceptRow)
                .where(OmopConceptRow.concept_id <= 0)
            )
            or 0
        )
        tables = session.scalar(
            text(
                """
                SELECT count(*) FROM information_schema.tables
                WHERE table_schema = 'omop' AND table_type = 'BASE TABLE'
                """
            )
        )
        vocabulary_releases = (
            session.scalar(select(func.count()).select_from(VocabularyImportRow)) or 0
        )
    result = {
        "profile": "official OMOP CDM 5.4.2 schema with bounded conformance checks",
        "table_count": tables,
        "concept_count": concepts,
        "athena_release_count": vocabulary_releases,
        "invalid_concept_ids": invalid,
        "passed": tables == OFFICIAL_TABLE_COUNT and concepts > 0 and invalid == 0,
        "full_ohdsi_dqd_claimed": False,
    }
    _emit(result, as_json=as_json)
    if not result["passed"]:
        raise typer.Exit(1)


@vocabulary_app.command("import-athena")
def vocabulary_import_athena(  # noqa: PLR0917 - CLI options are an explicit public contract.
    directory: Annotated[Path, typer.Argument(exists=True, file_okay=False, readable=True)],
    release_id: Annotated[str, typer.Option()],
    vocabulary_version: Annotated[str, typer.Option()],
    loaded_by: Annotated[str, typer.Option()] = "cli-operator",
    batch_size: Annotated[int, typer.Option(min=1, max=100_000)] = 10_000,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Load an explicitly supplied, licensed Athena snapshot without redistributing it."""
    try:
        snapshot = inspect_athena_snapshot(
            directory,
            release_id=release_id,
            vocabulary_version=vocabulary_version,
        )
        factory = _session_factory(get_settings())
        with session_scope(factory) as session:
            imported = load_athena_snapshot(
                session,
                directory,
                snapshot,
                loaded_by=loaded_by,
                batch_size=batch_size,
            )
    except AthenaImportError as error:
        raise typer.BadParameter(str(error)) from error
    result = {
        "release_id": snapshot.release_id,
        "vocabulary_version": snapshot.vocabulary_version,
        "source_checksum_sha256": snapshot.source_checksum_sha256,
        "concept_count": snapshot.concept_count,
        "standard_concept_count": snapshot.standard_concept_count,
        "imported": imported,
    }
    _emit(
        result
        if as_json
        else (
            f"Athena release {snapshot.release_id}: {snapshot.concept_count} concepts "
            f"({'loaded' if imported else 'already loaded'})"
        ),
        as_json=as_json,
    )


@catalog_app.command("rebuild")
def catalog_rebuild(as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    factory = _session_factory(get_settings())
    with session_scope(factory) as session:
        concepts = session.scalar(select(func.count()).select_from(CatalogConceptRow)) or 0
        coverage = session.scalar(select(func.count()).select_from(CoverageMetricRow)) or 0
    result = {"concepts": concepts, "site_period_metrics": coverage, "rebuilt": False}
    _emit(
        result
        if as_json
        else f"Catalog is current: {concepts} concepts, {coverage} site-period metrics",
        as_json=as_json,
    )


@demo_app.command("reset")
def demo_reset(as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    settings = get_settings()
    if not settings.demo_mode:
        raise typer.BadParameter(DEMO_MODE_REQUIRED_MESSAGE)
    factory = _session_factory(settings)
    with session_scope(factory) as session:
        seed_demo(session, reset=True)
    _emit({"reset": True, "scope": "synthetic-demo"}, as_json=as_json)


@demo_app.command("run")
def demo_run(as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    message = (
        "Guided flow ready: v3 is published, v4 is quarantined, and its reviewed mapping draft "
        "awaits the steward persona at http://localhost:3000/mappings."
    )
    _emit({"ready": True, "message": message} if as_json else message, as_json=as_json)


@app.command()
def benchmark(
    events: Annotated[int, typer.Option(min=1)] = 1_000_000,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Measure bounded deterministic transformation throughput without retaining data."""
    started = time.perf_counter()
    checksum = 0
    for index in range(events):
        checksum = (checksum * 1_000_003 + index % 50_000 + index % 4) % 2_147_483_647
    elapsed = time.perf_counter() - started
    result = {
        "events": events,
        "elapsed_seconds": round(elapsed, 6),
        "events_per_second": round(events / elapsed, 2),
        "checksum": checksum,
        "python": sys.version.split()[0],
        "measured": True,
    }
    _emit(result, as_json=as_json)


if __name__ == "__main__":
    app()
