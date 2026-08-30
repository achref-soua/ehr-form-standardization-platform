"""Site-local deterministic pseudonymization."""

import hashlib
import hmac

MINIMUM_KEY_BYTES = 32


def pseudonymize(identifier: str, *, key: bytes, namespace: str) -> str:
    if len(key) < MINIMUM_KEY_BYTES:
        msg = "Pseudonymization keys must contain at least 32 bytes"
        raise ValueError(msg)
    normalized = identifier.strip().encode()
    if not normalized:
        msg = "Cannot pseudonymize an empty identifier"
        raise ValueError(msg)
    digest = hmac.new(key, namespace.encode() + b"\x00" + normalized, hashlib.sha256).hexdigest()
    return f"p_{digest[:32]}"
