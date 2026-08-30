"""Native-text, local-OCR, and deterministic document evidence services."""

from ehrfs.documents.assertion import extract_allergy_candidate
from ehrfs.documents.models import (
    DocumentCandidate,
    DocumentExtractionResult,
    ExtractedDocumentSpan,
    OcrExtraction,
    OcrPage,
    OcrSpan,
)
from ehrfs.documents.ocr import (
    DocumentExtractionRouter,
    HttpOcrAdapter,
    NativePdfPage,
    extract_document_text,
    extract_native_pdf_text,
)
from ehrfs.documents.reconciliation import reconcile_structured_and_narrative

__all__ = [
    "DocumentCandidate",
    "DocumentExtractionResult",
    "DocumentExtractionRouter",
    "ExtractedDocumentSpan",
    "HttpOcrAdapter",
    "NativePdfPage",
    "OcrExtraction",
    "OcrPage",
    "OcrSpan",
    "extract_allergy_candidate",
    "extract_document_text",
    "extract_native_pdf_text",
    "reconcile_structured_and_narrative",
]
