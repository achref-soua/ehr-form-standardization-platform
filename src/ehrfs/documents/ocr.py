"""Local OCR client and native-PDF-first extraction policy."""

from __future__ import annotations

from io import BytesIO
from typing import Final

import httpx
from pydantic import Field
from pypdf import PdfReader

from ehrfs.documents.models import (
    DocumentExtractionResult,
    ExtractedDocumentSpan,
    OcrAdapter,
    OcrExtraction,
)
from ehrfs.domain.enums import ExtractionMethod
from ehrfs.domain.errors import DomainError
from ehrfs.domain.identity import sha256_hex
from ehrfs.domain.models import DomainModel, EvidenceReference

OCR_MEDIA_TYPES: Final = frozenset({"image/png", "image/jpeg", "image/tiff", "application/pdf"})
NATIVE_TEXT_MINIMUM_CHARACTERS: Final = 40
OCR_FAILURE_MESSAGE = "The local OCR process rejected or could not process the document"
INVALID_PDF_MESSAGE = "The PDF is encrypted, malformed, or unsafe to extract"


class NativePdfPage(DomainModel):
    page: int = Field(ge=1)
    text: str


def _reject_encrypted(reader: PdfReader) -> None:
    if reader.is_encrypted:
        raise DomainError("ENCRYPTED_DOCUMENT", INVALID_PDF_MESSAGE)


def extract_native_pdf_text(content: bytes) -> tuple[NativePdfPage, ...]:
    """Extract embedded PDF text without rendering or invoking OCR."""
    try:
        reader = PdfReader(BytesIO(content), strict=True)
        _reject_encrypted(reader)
        return tuple(
            NativePdfPage(page=index, text=(page.extract_text() or "").strip())
            for index, page in enumerate(reader.pages, start=1)
        )
    except DomainError:
        raise
    except Exception as error:
        raise DomainError("INVALID_PDF", INVALID_PDF_MESSAGE) from error


def has_usable_native_text(
    pages: tuple[NativePdfPage, ...],
    *,
    minimum_characters: int = NATIVE_TEXT_MINIMUM_CHARACTERS,
) -> bool:
    return sum(len(page.text) for page in pages) >= minimum_characters


def extract_document_text(
    content: bytes,
    *,
    media_type: str,
    object_key: str,
    ocr: OcrAdapter,
    relevant: bool = True,
    native_text_minimum_characters: int = NATIVE_TEXT_MINIMUM_CHARACTERS,
) -> DocumentExtractionResult:
    """Extract native PDF text first, otherwise call only the injected local OCR adapter."""
    checksum = sha256_hex(content)
    if not content:
        raise DomainError("EMPTY_DOCUMENT", "Document content is empty")
    if media_type not in OCR_MEDIA_TYPES:
        raise DomainError(
            "UNSUPPORTED_DOCUMENT_MEDIA_TYPE", f"Documents do not accept {media_type}"
        )
    if media_type == "application/pdf":
        native_pages = extract_native_pdf_text(content)
        if has_usable_native_text(
            native_pages,
            minimum_characters=native_text_minimum_characters,
        ):
            spans = tuple(
                ExtractedDocumentSpan(
                    text=page.text,
                    evidence=EvidenceReference(
                        object_key=object_key,
                        checksum_sha256=checksum,
                        media_type=media_type,
                        page=page.page,
                        text_span_start=0,
                        text_span_end=len(page.text),
                        source_locator=f"pdf:page:{page.page}",
                        extraction_method=ExtractionMethod.NATIVE_TEXT,
                        extractor_version="pypdf/6",
                    ),
                )
                for page in native_pages
                if page.text
            )
            return DocumentExtractionResult(
                checksum_sha256=checksum,
                method=ExtractionMethod.NATIVE_TEXT,
                spans=spans,
                model_version="pypdf/6",
            )
    if not relevant:
        return DocumentExtractionResult(
            checksum_sha256=checksum,
            method=None,
            spans=(),
            abstained=True,
        )
    extraction = ocr.extract(content, media_type=media_type)
    spans = tuple(
        ExtractedDocumentSpan(
            text=span.text,
            evidence=EvidenceReference(
                object_key=object_key,
                checksum_sha256=checksum,
                media_type=media_type,
                page=page.page,
                bounding_box=span.bounding_box,
                source_locator=f"ocr:page:{page.page}:span:{index}",
                extraction_method=ExtractionMethod.OCR_RULES,
                extractor_version=page.model_version,
                confidence=span.confidence,
            ),
        )
        for page in extraction.pages
        for index, span in enumerate(page.spans)
    )
    return DocumentExtractionResult(
        checksum_sha256=checksum,
        method=ExtractionMethod.OCR_RULES,
        spans=spans,
        model_version=extraction.model_version,
        device=extraction.device,
        elapsed_ms=extraction.elapsed_ms,
    )


class DocumentExtractionRouter:
    """Per-worker cache; durable object identity supplies cross-worker deduplication."""

    def __init__(self, ocr: OcrAdapter) -> None:
        self._ocr = ocr
        self._results: dict[str, DocumentExtractionResult] = {}

    def extract(
        self,
        content: bytes,
        *,
        media_type: str,
        object_key: str,
        relevant: bool = True,
    ) -> DocumentExtractionResult:
        checksum = sha256_hex(content)
        previous = self._results.get(checksum)
        if previous is not None:
            return previous.model_copy(update={"deduplicated": True})
        result = extract_document_text(
            content,
            media_type=media_type,
            object_key=object_key,
            ocr=self._ocr,
            relevant=relevant,
        )
        self._results[checksum] = result
        return result


class HttpOcrAdapter(OcrAdapter):
    """Calls only the configured, self-hosted OCR process over HTTP."""

    def __init__(
        self,
        endpoint: str,
        *,
        timeout_seconds: float = 120,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    def extract(self, content: bytes, *, media_type: str) -> OcrExtraction:
        if media_type not in OCR_MEDIA_TYPES:
            raise DomainError("UNSUPPORTED_OCR_MEDIA_TYPE", f"OCR does not accept {media_type}")
        try:
            with httpx.Client(
                timeout=self._timeout_seconds,
                transport=self._transport,
                trust_env=False,
            ) as client:
                response = client.post(
                    f"{self._endpoint}/v1/ocr",
                    files={"upload": ("evidence", content, media_type)},
                    headers={"X-Content-SHA256": sha256_hex(content)},
                )
                response.raise_for_status()
            extraction = OcrExtraction.model_validate(response.json())
        except (httpx.HTTPError, ValueError) as error:
            raise DomainError("OCR_PROCESS_FAILURE", OCR_FAILURE_MESSAGE) from error
        if extraction.image_checksum_sha256 != sha256_hex(content):
            raise DomainError("OCR_CHECKSUM_MISMATCH", OCR_FAILURE_MESSAGE)
        return extraction
