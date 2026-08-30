"""ClamAV streaming boundary with a narrowly gated synthetic-fixture no-op."""

from __future__ import annotations

import socket
import struct
from dataclasses import dataclass
from typing import Protocol

from ehrfs.config import Settings
from ehrfs.domain.errors import DomainError

CHUNK_BYTES = 64 * 1024
MAXIMUM_RESPONSE_BYTES = 4096


@dataclass(frozen=True, slots=True)
class ScanResult:
    scanner: str
    clean: bool
    detail: str


class MalwareScanner(Protocol):
    def scan(self, content: bytes) -> ScanResult: ...


class DemoFixtureScanner:
    def scan(self, content: bytes) -> ScanResult:
        if not content:
            raise DomainError("EMPTY_UPLOAD", "Cannot scan an empty upload")
        return ScanResult(scanner="demo-noop", clean=True, detail="generated synthetic fixture")


class ClamAvScanner:
    def __init__(self, host: str, port: int, *, timeout_seconds: float = 10) -> None:
        self._host = host
        self._port = port
        self._timeout_seconds = timeout_seconds

    def scan(self, content: bytes) -> ScanResult:
        try:
            with socket.create_connection(
                (self._host, self._port), timeout=self._timeout_seconds
            ) as connection:
                connection.settimeout(self._timeout_seconds)
                connection.sendall(b"zINSTREAM\0")
                for offset in range(0, len(content), CHUNK_BYTES):
                    chunk = content[offset : offset + CHUNK_BYTES]
                    connection.sendall(struct.pack("!I", len(chunk)))
                    connection.sendall(chunk)
                connection.sendall(struct.pack("!I", 0))
                response = connection.recv(MAXIMUM_RESPONSE_BYTES).rstrip(b"\0").decode()
        except (OSError, UnicodeDecodeError) as error:
            raise DomainError(
                "MALWARE_SCANNER_UNAVAILABLE", "The malware scanner is unavailable", 503
            ) from error
        if response.endswith(" OK"):
            return ScanResult(scanner="clamav", clean=True, detail="clean")
        if response.endswith(" FOUND"):
            raise DomainError(
                "MALWARE_DETECTED", "The upload was rejected by malware scanning", 422
            )
        raise DomainError(
            "MALWARE_SCANNER_ERROR", "The malware scanner returned an invalid response", 503
        )


def scanner_for_upload(settings: Settings, *, synthetic_fixture: bool) -> MalwareScanner:
    if settings.malware_scanner == "demo-noop" or (
        settings.malware_scanner == "auto" and synthetic_fixture
    ):
        if not settings.demo_mode or not synthetic_fixture:
            raise DomainError(
                "MALWARE_SCANNER_REQUIRED",
                "No-op scanning is limited to explicit generated fixtures in demo mode",
                503,
            )
        return DemoFixtureScanner()
    return ClamAvScanner(settings.clamav_host, settings.clamav_port)
