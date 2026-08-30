"""Exact-only runtime mapping resolution."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from ehrfs.domain.errors import DomainError
from ehrfs.domain.models import CanonicalAnswerEvent
from ehrfs.mapping.models import MappingEntry, MappingReleaseArtifact


class ResolutionLevel(IntEnum):
    SITE_OVERRIDE = 1
    SOURCE_FINGERPRINT = 2
    COMPATIBILITY_FINGERPRINT = 3


@dataclass(frozen=True, slots=True)
class ResolvedMapping:
    entry: MappingEntry
    level: ResolutionLevel
    release_id: str


class MappingResolver:
    def __init__(self, artifact: MappingReleaseArtifact) -> None:
        if not artifact.has_valid_checksum():
            raise DomainError("INVALID_MAPPING_CHECKSUM", "Mapping release checksum is invalid")
        self._artifact = artifact

    def resolve(self, event: CanonicalAnswerEvent) -> ResolvedMapping | None:
        candidates: list[tuple[ResolutionLevel, MappingEntry]] = []
        for entry in self._artifact.entries:
            scope = entry.scope
            if scope.item_path != event.item_path:
                continue
            if scope.establishment_id is not None:
                if scope.establishment_id != event.establishment_id:
                    continue
                if scope.source_fingerprint != event.source_fingerprint:
                    continue
                candidates.append((ResolutionLevel.SITE_OVERRIDE, entry))
                continue
            if scope.source_fingerprint == event.source_fingerprint:
                candidates.append((ResolutionLevel.SOURCE_FINGERPRINT, entry))
                continue
            if scope.compatibility_fingerprint == event.compatibility_fingerprint:
                candidates.append((ResolutionLevel.COMPATIBILITY_FINGERPRINT, entry))

        if not candidates:
            return None
        candidates.sort(key=lambda candidate: candidate[0])
        best_level = candidates[0][0]
        best = [entry for level, entry in candidates if level == best_level]
        if len(best) != 1:
            raise DomainError(
                "AMBIGUOUS_MAPPING",
                f"Multiple mappings resolve at level {best_level.name}",
            )
        return ResolvedMapping(best[0], best_level, self._artifact.release_id)
