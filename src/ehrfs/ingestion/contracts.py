"""Typed connector boundary."""

from __future__ import annotations

from typing import Protocol

from ehrfs.domain.models import CanonicalAnswerEvent, FormDefinition


class SourceAdapter(Protocol):
    def parse_definition(self, payload: bytes) -> FormDefinition: ...

    def parse_response(
        self,
        definition: FormDefinition,
        payload: bytes,
        *,
        establishment_id: str,
        patient_pseudonym: str,
        evidence_object_key: str,
    ) -> tuple[CanonicalAnswerEvent, ...]: ...
