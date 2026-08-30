"""Measure the live ClamAV profile with clean and standard test payloads."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from ehrfs.domain.errors import DomainError
from ehrfs.security.scanning import ClamAvScanner

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = ROOT / "data/fixtures/ocr/allergy-clean.png"
DEFAULT_OUTPUT = ROOT / "artifacts/benchmarks/clamav.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3310)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()

    scanner = ClamAvScanner(arguments.host, arguments.port, timeout_seconds=30)
    clean = scanner.scan(arguments.fixture.read_bytes())
    # Construct the standard harmless EICAR antivirus test signature at runtime
    # so repository scanners do not mistake source code for a malicious fixture.
    eicar = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$" + b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
    detected = False
    try:
        scanner.scan(eicar)
    except DomainError as error:
        if error.code != "MALWARE_DETECTED":
            raise
        detected = True

    payload = {
        "measured_at": datetime.now(UTC).isoformat(),
        "host": arguments.host,
        "port": arguments.port,
        "clean_scan": asdict(clean),
        "eicar_detected": detected,
        "measured": True,
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    arguments.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if clean.clean and detected else 1


if __name__ == "__main__":
    sys.exit(main())
