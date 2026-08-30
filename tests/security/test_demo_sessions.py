from __future__ import annotations

import pytest
from fastapi import HTTPException

from ehrfs.config import Settings
from ehrfs_api.auth import PERSONAS, create_session, parse_session


def _settings() -> Settings:
    return Settings(
        environment="test",
        session_secret="session-secret-for-tests-000000000",
        csrf_secret="csrf-secret-for-tests-000000000000",
        pseudonymization_key="pseudo-secret-for-tests",
        s3_secret_key="s3-secret-for-tests",
    )


def test_signed_session_round_trip_and_expiry() -> None:
    token, csrf = create_session(PERSONAS["steward"], _settings(), now=100)

    parsed = parse_session(token, _settings(), now=101)

    assert parsed.actor.role == "steward"
    assert len(csrf) == 64
    with pytest.raises(HTTPException, match="Demo session expired"):
        parse_session(token, _settings(), now=100 + 8 * 60 * 60)


def test_tampered_session_is_rejected() -> None:
    token, _ = create_session(PERSONAS["engineer"], _settings(), now=100)
    payload, signature = token.split(".")
    tampered = f"{payload}.{signature[:-1]}A"

    with pytest.raises(HTTPException, match="Invalid demo session"):
        parse_session(tampered, _settings(), now=101)
