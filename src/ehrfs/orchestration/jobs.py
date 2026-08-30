"""PostgreSQL leased queue used by core and Airflow profiles."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import Select, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from ehrfs.domain.enums import RunStatus
from ehrfs.domain.errors import ConflictError
from ehrfs.storage.tables import PipelineJobRow


@dataclass(frozen=True, slots=True)
class DurableJob:
    id: UUID
    job_type: str
    payload: dict[str, Any]
    correlation_id: str
    attempts: int
    maximum_attempts: int
    leased_until: datetime
    created_at: datetime


class JobRepository:
    def enqueue(
        self,
        session: Session,
        *,
        job_type: str,
        payload: dict[str, Any],
        idempotency_key: str,
        correlation_id: str,
        now: datetime,
        maximum_attempts: int = 3,
    ) -> UUID:
        statement = (
            insert(PipelineJobRow)
            .values(
                job_type=job_type,
                status=RunStatus.QUEUED,
                idempotency_key=idempotency_key,
                payload_json=payload,
                correlation_id=correlation_id,
                attempts=0,
                maximum_attempts=maximum_attempts,
                available_at=now,
                created_at=now,
            )
            .on_conflict_do_update(
                constraint="uq_pipeline_job_idempotency",
                set_={"idempotency_key": idempotency_key},
                where=(
                    (PipelineJobRow.job_type == job_type) & (PipelineJobRow.payload_json == payload)
                ),
            )
            .returning(PipelineJobRow.id)
        )
        job_id = session.execute(statement).scalar_one_or_none()
        if job_id is None:
            raise ConflictError(
                "IDEMPOTENCY_KEY_REUSED",
                "Idempotency key was reused with a different job type or payload",
            )
        return job_id

    def _claim_query(self, *, now: datetime) -> Select[tuple[PipelineJobRow]]:
        return (
            select(PipelineJobRow)
            .where(
                PipelineJobRow.status == RunStatus.QUEUED,
                PipelineJobRow.available_at <= now,
                PipelineJobRow.attempts < PipelineJobRow.maximum_attempts,
            )
            .order_by(PipelineJobRow.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )

    def claim(
        self,
        session: Session,
        *,
        worker_id: str,
        now: datetime,
        lease_seconds: int,
    ) -> DurableJob | None:
        row = session.execute(self._claim_query(now=now)).scalar_one_or_none()
        if row is None:
            return None
        leased_until = now + timedelta(seconds=lease_seconds)
        row.status = RunStatus.RUNNING
        row.leased_by = worker_id
        row.leased_until = leased_until
        row.heartbeat_at = now
        row.started_at = row.started_at or now
        row.attempts += 1
        session.flush()
        return DurableJob(
            id=row.id,
            job_type=row.job_type,
            payload=row.payload_json,
            correlation_id=row.correlation_id,
            attempts=row.attempts,
            maximum_attempts=row.maximum_attempts,
            leased_until=leased_until,
            created_at=row.created_at,
        )

    def heartbeat(
        self,
        session: Session,
        *,
        job_id: UUID,
        worker_id: str,
        now: datetime,
        lease_seconds: int,
    ) -> bool:
        result = cast(
            CursorResult[Any],
            session.execute(
                update(PipelineJobRow)
                .where(
                    PipelineJobRow.id == job_id,
                    PipelineJobRow.status == RunStatus.RUNNING,
                    PipelineJobRow.leased_by == worker_id,
                    PipelineJobRow.leased_until > now,
                )
                .values(
                    heartbeat_at=now,
                    leased_until=now + timedelta(seconds=lease_seconds),
                )
            ),
        )
        return bool(result.rowcount)

    def complete(
        self,
        session: Session,
        *,
        job_id: UUID,
        worker_id: str,
        now: datetime,
    ) -> bool:
        result = cast(
            CursorResult[Any],
            session.execute(
                update(PipelineJobRow)
                .where(
                    PipelineJobRow.id == job_id,
                    PipelineJobRow.status == RunStatus.RUNNING,
                    PipelineJobRow.leased_by == worker_id,
                    PipelineJobRow.leased_until > now,
                )
                .values(
                    status=RunStatus.SUCCEEDED,
                    finished_at=now,
                    leased_until=None,
                    leased_by=None,
                )
            ),
        )
        return bool(result.rowcount)

    def fail(
        self,
        session: Session,
        *,
        job_id: UUID,
        worker_id: str,
        now: datetime,
        error: str,
        retry_delay_seconds: int,
    ) -> bool:
        row = session.execute(
            select(PipelineJobRow).where(
                PipelineJobRow.id == job_id,
                PipelineJobRow.status == RunStatus.RUNNING,
                PipelineJobRow.leased_by == worker_id,
            )
        ).scalar_one_or_none()
        if row is None:
            return False
        retryable = row.attempts < row.maximum_attempts
        row.status = RunStatus.QUEUED if retryable else RunStatus.FAILED
        row.available_at = now + timedelta(seconds=retry_delay_seconds)
        row.finished_at = None if retryable else now
        row.leased_until = None
        row.leased_by = None
        row.last_error = error[:4000]
        session.flush()
        return True

    def recover_expired(self, session: Session, *, now: datetime) -> int:
        result = cast(
            CursorResult[Any],
            session.execute(
                update(PipelineJobRow)
                .where(
                    PipelineJobRow.status == RunStatus.RUNNING,
                    PipelineJobRow.leased_until <= now,
                )
                .values(
                    status=RunStatus.QUEUED,
                    leased_until=None,
                    leased_by=None,
                    available_at=now,
                    last_error="Worker lease expired; job returned to queue",
                )
            ),
        )
        return int(result.rowcount or 0)
