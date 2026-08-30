from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pytest

from ehrfs.config import Settings
from ehrfs.domain.errors import DomainError
from ehrfs.domain.identity import canonical_json_bytes
from ehrfs.federation.bundle import SiteMetric, build_site_summary
from ehrfs.security.pseudonymization import pseudonymize
from ehrfs.security.scanning import ClamAvScanner, DemoFixtureScanner, scanner_for_upload
from ehrfs.security.signing import ReleaseSigner
from ehrfs.security.uploads import sniff_media_type, validate_upload


def test_pseudonymization_is_deterministic_and_namespaced() -> None:
    key = b"x" * 32
    first = pseudonymize("patient-1", key=key, namespace="site-a")
    assert first == pseudonymize("patient-1", key=key, namespace="site-a")
    assert first != pseudonymize("patient-1", key=key, namespace="site-b")
    assert "patient-1" not in first


def test_short_pseudonymization_key_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least 32 bytes"):
        pseudonymize("patient", key=b"short", namespace="site")


def test_site_bundle_suppresses_small_cells(fixed_time: datetime) -> None:
    signer = ReleaseSigner.generate()
    summary = build_site_summary(
        establishment_id="site-a",
        mapping_release_ids=("mapping-1",),
        research_release_id="release-1",
        generated_at=fixed_time,
        metrics=(
            SiteMetric(
                concept_key="allergy-history",
                period_start=date(2026, 1, 1),
                period_end=date(2026, 12, 31),
                recorded_count=9,
                usable_count=8,
                positive_count=2,
            ),
        ),
        threshold=10,
        signer=signer,
    )
    assert summary.bundle.metrics[0].suppressed
    assert summary.bundle.metrics[0].recorded_count == 0
    assert signer.verify(
        canonical_json_bytes(summary.bundle.model_dump(mode="json")),
        summary.signature_base64,
    )


@pytest.mark.parametrize(
    ("content", "media_type"),
    [
        (b"%PDF-1.7\n", "application/pdf"),
        (b"\x89PNG\r\n\x1a\nfixture", "image/png"),
        (b"\xff\xd8\xfffixture", "image/jpeg"),
        (b'{"resourceType":"Questionnaire"}', "application/json"),
        (b"<?xml version='1.0'?><root />", "application/xml"),
        (b"item,value\nQ1,yes\n", "text/csv"),
    ],
)
def test_upload_signature_detection(content: bytes, media_type: str) -> None:
    assert sniff_media_type(content) == media_type


def test_upload_rejects_malformed_or_mismatched_content() -> None:
    for content, message in (
        (b"{broken", "valid JSON"),
        (b"<broken", "valid XML"),
        (b"\x00\xff", "signature"),
        (b"plain text", "signature"),
    ):
        with pytest.raises(DomainError, match=message):
            sniff_media_type(content)
    with pytest.raises(DomainError, match="does not match"):
        validate_upload(
            b"%PDF-1.7\n", filename="scan.png", media_type="image/png", maximum_bytes=100
        )


class _FakeClamConnection:
    def __init__(self, response: bytes) -> None:
        self.response = response
        self.sent = bytearray()

    def __enter__(self) -> _FakeClamConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def settimeout(self, _timeout: float) -> None:
        return None

    def sendall(self, content: bytes) -> None:
        self.sent.extend(content)

    def recv(self, _maximum: int) -> bytes:
        return self.response


@pytest.mark.parametrize(
    ("response", "message"),
    [(b"stream: Eicar-Test-Signature FOUND\0", "malware"), (b"invalid\0", "invalid response")],
)
def test_clamav_rejects_findings_and_invalid_responses(
    monkeypatch: pytest.MonkeyPatch, response: bytes, message: str
) -> None:
    connection = _FakeClamConnection(response)
    monkeypatch.setattr(
        "ehrfs.security.scanning.socket.create_connection", lambda *_args, **_kwargs: connection
    )
    with pytest.raises(DomainError, match=message):
        ClamAvScanner("clamav", 3310).scan(b"synthetic")


def test_clamav_stream_and_demo_scanner_boundaries(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _FakeClamConnection(b"stream: OK\0")
    monkeypatch.setattr(
        "ehrfs.security.scanning.socket.create_connection", lambda *_args, **_kwargs: connection
    )
    result = ClamAvScanner("clamav", 3310).scan(b"synthetic")
    assert result.clean and connection.sent.startswith(b"zINSTREAM\0")

    demo = Settings(malware_scanner="auto")
    assert isinstance(scanner_for_upload(demo, synthetic_fixture=True), DemoFixtureScanner)
    assert scanner_for_upload(demo, synthetic_fixture=True).scan(b"fixture").clean
    with pytest.raises(DomainError, match="empty"):
        DemoFixtureScanner().scan(b"")
    with pytest.raises(DomainError, match="No-op"):
        scanner_for_upload(
            demo.model_copy(update={"demo_mode": False, "malware_scanner": "demo-noop"}),
            synthetic_fixture=True,
        )

    def unavailable(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("unavailable")

    monkeypatch.setattr("ehrfs.security.scanning.socket.create_connection", unavailable)
    with pytest.raises(DomainError, match="unavailable"):
        ClamAvScanner("clamav", 3310).scan(b"synthetic")
