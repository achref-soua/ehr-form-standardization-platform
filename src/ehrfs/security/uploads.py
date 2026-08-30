"""Upload validation independent from the HTTP framework."""

from __future__ import annotations

import re
from json import JSONDecodeError, loads
from pathlib import PurePath

from defusedxml.ElementTree import ParseError, fromstring

from ehrfs.domain.errors import DomainError

ALLOWED_MEDIA_TYPES = frozenset(
    {
        "application/fhir+json",
        "application/json",
        "application/pdf",
        "application/xml",
        "image/jpeg",
        "image/png",
        "text/csv",
        "text/xml",
    }
)
SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
JSON_MEDIA_TYPES = frozenset({"application/fhir+json", "application/json"})
XML_MEDIA_TYPES = frozenset({"application/xml", "text/xml"})


def sniff_media_type(content: bytes) -> str:
    """Identify only the bounded formats accepted by this application."""
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    stripped = content.lstrip()
    if stripped.startswith((b"{", b"[")):
        try:
            loads(content)
        except (JSONDecodeError, UnicodeDecodeError) as error:
            raise DomainError("MALFORMED_JSON", "The upload is not valid JSON", 422) from error
        return "application/json"
    if stripped.startswith(b"<"):
        try:
            fromstring(content)
        except (ParseError, ValueError) as error:
            raise DomainError("MALFORMED_XML", "The upload is not valid XML", 422) from error
        return "application/xml"
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise DomainError(
            "UNKNOWN_FILE_SIGNATURE", "Upload signature is not allowed", 415
        ) from error
    if "\n" in text and any(separator in text.partition("\n")[0] for separator in (",", ";", "\t")):
        return "text/csv"
    raise DomainError("UNKNOWN_FILE_SIGNATURE", "Upload signature is not allowed", 415)


def normalize_filename(filename: str) -> str:
    basename = PurePath(filename.replace("\\", "/")).name
    normalized = SAFE_NAME.sub("-", basename).strip(".-")
    if not normalized or normalized in {".", ".."}:
        raise DomainError("INVALID_FILENAME", "Upload filename is empty or unsafe")
    return normalized[:180]


def validate_upload(
    content: bytes,
    *,
    filename: str,
    media_type: str,
    maximum_bytes: int,
) -> str:
    if media_type not in ALLOWED_MEDIA_TYPES:
        raise DomainError("UNSUPPORTED_MEDIA_TYPE", f"Unsupported media type: {media_type}", 415)
    if not content:
        raise DomainError("EMPTY_UPLOAD", "Upload content is empty")
    if len(content) > maximum_bytes:
        raise DomainError("UPLOAD_TOO_LARGE", "Upload exceeds the configured size limit", 413)
    detected = sniff_media_type(content)
    compatible = (
        detected == media_type
        or (detected == "application/json" and media_type in JSON_MEDIA_TYPES)
        or (detected == "application/xml" and media_type in XML_MEDIA_TYPES)
    )
    if not compatible:
        raise DomainError(
            "MEDIA_TYPE_MISMATCH",
            f"Declared media type {media_type} does not match the file signature",
            415,
        )
    return normalize_filename(filename)
