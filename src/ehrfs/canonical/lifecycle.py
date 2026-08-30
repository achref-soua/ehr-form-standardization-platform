"""Resolve immutable correction and void chains without mutating prior releases."""

from __future__ import annotations

from uuid import UUID

from ehrfs.domain.enums import AnswerState, LifecycleStatus
from ehrfs.domain.errors import DomainError
from ehrfs.domain.models import CanonicalAnswerEvent


def resolve_lifecycle(
    events: tuple[CanonicalAnswerEvent, ...],
) -> tuple[CanonicalAnswerEvent, ...]:
    """Mark superseded facts in one batch while retaining every source event."""
    by_id = {event.event_id: event for event in events}
    if len(by_id) != len(events):
        raise DomainError(
            "DUPLICATE_EVENT_ID", "Lifecycle input contains duplicate event identities"
        )

    superseded: set[UUID] = set()
    links: dict[UUID, UUID] = {}
    for event in events:
        for lifecycle in event.lifecycle:
            target_id = lifecycle.supersedes_event_id
            if lifecycle.status not in {LifecycleStatus.CORRECTED, LifecycleStatus.VOIDED}:
                continue
            if target_id is None or target_id not in by_id:
                raise DomainError(
                    "INVALID_SUPERSESSION",
                    "Correction or void references an event outside the source batch",
                )
            target = by_id[target_id]
            if target.event_id == event.event_id:
                raise DomainError("INVALID_SUPERSESSION", "An event cannot supersede itself")
            if (
                target.patient_pseudonym,
                target.form_id,
                target.item_path,
                target.group_instance,
            ) != (
                event.patient_pseudonym,
                event.form_id,
                event.item_path,
                event.group_instance,
            ):
                raise DomainError(
                    "INVALID_SUPERSESSION",
                    "Supersession must remain within one patient, form item, and repeat instance",
                )
            if target_id in superseded:
                raise DomainError(
                    "AMBIGUOUS_SUPERSESSION",
                    "One source event cannot be superseded by multiple current events",
                )
            superseded.add(target_id)
            links[event.event_id] = target_id

    for origin in links:
        visited: set[UUID] = set()
        cursor: UUID | None = origin
        while cursor in links:
            if cursor in visited:
                raise DomainError("CYCLIC_SUPERSESSION", "Lifecycle supersession contains a cycle")
            visited.add(cursor)
            cursor = links[cursor]

    return tuple(
        event.model_copy(update={"state": AnswerState.SUPERSEDED, "value": None})
        if event.event_id in superseded
        else event
        for event in events
    )
