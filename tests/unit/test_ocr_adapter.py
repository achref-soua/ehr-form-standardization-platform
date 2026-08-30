from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
import pytest
from pypdf import PdfWriter

from ehrfs.documents.models import OcrExtraction, OcrPage, OcrSpan
from ehrfs.documents.ocr import (
    DocumentExtractionRouter,
    HttpOcrAdapter,
    extract_document_text,
    extract_native_pdf_text,
    has_usable_native_text,
)
from ehrfs.domain.enums import ExtractionMethod
from ehrfs.domain.errors import DomainError
from ehrfs.domain.identity import sha256_hex


def _pdf(*, encrypted: bool = False) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=200)
    if encrypted:
        writer.encrypt("synthetic-password")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_native_pdf_is_attempted_before_ocr_and_encrypted_pdf_is_rejected() -> None:
    pages = extract_native_pdf_text(_pdf())
    assert pages[0].page == 1
    assert not has_usable_native_text(pages)
    assert has_usable_native_text(pages, minimum_characters=0)
    with pytest.raises(DomainError, match="encrypted"):
        extract_native_pdf_text(_pdf(encrypted=True))
    with pytest.raises(DomainError, match="malformed"):
        extract_native_pdf_text(b"not-a-pdf")


def test_local_ocr_adapter_preserves_boxes_versions_measurement_and_checksum() -> None:
    content = b"synthetic-image"
    payload = {
        "pages": [
            {
                "page": 1,
                "width": 640,
                "height": 320,
                "spans": [
                    {
                        "text": "Allergie à la pénicilline",
                        "confidence": 0.97,
                        "bounding_box": [20, 30, 500, 68],
                    }
                ],
                "model_version": "PP-OCRv5/fr@3.7.0",
            }
        ],
        "device": "cpu",
        "elapsed_ms": 42.5,
        "model_version": "PP-OCRv5/fr@3.7.0",
        "image_checksum_sha256": sha256_hex(content),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "http://ocr.local/v1/ocr"
        assert request.headers["X-Content-SHA256"] == sha256_hex(content)
        return httpx.Response(200, json=payload)

    result = HttpOcrAdapter("http://ocr.local", transport=httpx.MockTransport(handler)).extract(
        content, media_type="image/png"
    )
    assert isinstance(result, OcrExtraction)
    assert result.pages[0].spans[0].bounding_box == (20, 30, 500, 68)
    assert result.device == "cpu"


@pytest.mark.parametrize(
    ("media_type", "handler", "message"),
    [
        ("text/plain", None, "does not accept"),
        ("image/png", lambda _request: httpx.Response(503), "rejected"),
        ("image/png", lambda _request: httpx.Response(200, json={}), "rejected"),
    ],
)
def test_local_ocr_adapter_fails_closed(
    media_type: str,
    handler: Any,
    message: str,
) -> None:
    transport = httpx.MockTransport(handler) if callable(handler) else None
    with pytest.raises(DomainError, match=message):
        HttpOcrAdapter("http://ocr.local", transport=transport).extract(
            b"synthetic-image", media_type=media_type
        )


def test_local_ocr_adapter_rejects_checksum_mismatch() -> None:
    payload = {
        "pages": [],
        "device": "gpu",
        "elapsed_ms": 1,
        "model_version": "test",
        "image_checksum_sha256": "0" * 64,
    }
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json=payload))
    with pytest.raises(DomainError, match="rejected"):
        HttpOcrAdapter("http://ocr.local", transport=transport).extract(
            b"synthetic-image", media_type="image/png"
        )


class StubOcr:
    def __init__(self) -> None:
        self.calls = 0

    def extract(self, content: bytes, *, media_type: str) -> OcrExtraction:
        self.calls += 1
        return OcrExtraction(
            pages=(
                OcrPage(
                    page=1,
                    width=640,
                    height=320,
                    spans=(
                        OcrSpan(
                            text="Allergie à la pénicilline",
                            confidence=0.96,
                            bounding_box=(20, 30, 500, 68),
                        ),
                    ),
                    model_version="PP-OCRv5/fr@test",
                ),
            ),
            device="cpu",
            elapsed_ms=12.5,
            model_version="PP-OCRv5/fr@test",
            image_checksum_sha256=sha256_hex(content),
        )


def test_document_router_prefers_native_pdf_and_skips_irrelevant_images() -> None:
    ocr = StubOcr()
    pdf = Path("docs/case-study/epiconcept-case-study.fr.pdf").read_bytes()
    native = extract_document_text(
        pdf,
        media_type="application/pdf",
        object_key="documents/case-study.pdf",
        ocr=ocr,
    )
    assert native.method == ExtractionMethod.NATIVE_TEXT
    assert native.spans and native.spans[0].evidence.page == 1
    assert ocr.calls == 0

    abstained = extract_document_text(
        b"\x89PNG\r\n\x1a\nsynthetic",
        media_type="image/png",
        object_key="documents/unrelated.png",
        ocr=ocr,
        relevant=False,
    )
    assert abstained.abstained and not abstained.spans and ocr.calls == 0


def test_document_router_uses_local_ocr_boxes_and_deduplicates_checksum() -> None:
    ocr = StubOcr()
    router = DocumentExtractionRouter(ocr)
    content = b"\x89PNG\r\n\x1a\nsynthetic-clinical-image"
    first = router.extract(
        content,
        media_type="image/png",
        object_key="documents/allergy.png",
    )
    duplicate = router.extract(
        content,
        media_type="image/png",
        object_key="documents/allergy.png",
    )
    assert first.method == ExtractionMethod.OCR_RULES
    assert first.spans[0].evidence.bounding_box == (20, 30, 500, 68)
    assert first.model_version == "PP-OCRv5/fr@test" and first.elapsed_ms == 12.5
    assert duplicate.deduplicated and ocr.calls == 1


def test_document_router_fails_closed_on_empty_or_unsupported_content() -> None:
    ocr = StubOcr()
    with pytest.raises(DomainError, match="empty"):
        extract_document_text(b"", media_type="image/png", object_key="documents/empty", ocr=ocr)
    with pytest.raises(DomainError, match="do not accept"):
        extract_document_text(
            b"text", media_type="text/plain", object_key="documents/text", ocr=ocr
        )
