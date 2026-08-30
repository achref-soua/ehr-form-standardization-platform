"""Deterministic identity helpers."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID, uuid5

EHRFS_NAMESPACE = UUID("575746d8-d046-4ccb-a27e-ab5a47554315")


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize release content identically across processes and runs."""
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def content_hash(value: Any) -> str:
    return sha256_hex(canonical_json_bytes(value))


def deterministic_uuid(kind: str, *parts: str) -> UUID:
    material = "\x1f".join((kind, *parts))
    return uuid5(EHRFS_NAMESPACE, material)
