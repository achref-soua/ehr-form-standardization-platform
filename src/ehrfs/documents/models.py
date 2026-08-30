"""OCR and rule-extraction contracts."""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import Field

from ehrfs.domain.enums import AnswerState, ExtractionMethod, FailureReason
from ehrfs.domain.models import DomainModel, EvidenceReference


class OcrSpan(DomainModel):
    text: str
    confidence: float = Field(ge=0, le=1)
    bounding_box: tuple[float, float, float, float]


class OcrPage(DomainModel):
    page: int = Field(ge=1)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    spans: tuple[OcrSpan, ...]
    model_version: str


class OcrExtraction(DomainModel):
    pages: tuple[OcrPage, ...]
    device: Literal["cpu", "gpu"]
    elapsed_ms: float = Field(ge=0)
    model_version: str
    image_checksum_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class OcrAdapter(Protocol):
    def extract(self, content: bytes, *, media_type: str) -> OcrExtraction: ...


class DocumentCandidate(DomainModel):
    concept: str
    substance: str | None = None
    reaction: str | None = None
    assertion: AnswerState
    confidence: float = Field(ge=0, le=1)
    method: ExtractionMethod
    evidence: EvidenceReference
    failures: tuple[FailureReason, ...] = ()


class ExtractedDocumentSpan(DomainModel):
    text: str
    evidence: EvidenceReference


class DocumentExtractionResult(DomainModel):
    checksum_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    method: ExtractionMethod | None
    spans: tuple[ExtractedDocumentSpan, ...]
    model_version: str | None = None
    device: Literal["cpu", "gpu"] | None = None
    elapsed_ms: float | None = Field(default=None, ge=0)
    deduplicated: bool = False
    abstained: bool = False
