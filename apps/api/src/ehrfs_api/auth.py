"""Explicitly demo-only signed sessions and role enforcement."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Cookie, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from ehrfs.config import Settings

Role = Literal["engineer", "steward", "researcher", "operator"]


class Persona(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    display_name: str
    role: Role


PERSONAS: dict[str, Persona] = {
    "engineer": Persona(id="engineer@demo.local", display_name="Data Engineer", role="engineer"),
    "steward": Persona(
        id="steward@demo.local", display_name="Clinical Data Steward", role="steward"
    ),
    "researcher": Persona(id="researcher@demo.local", display_name="Researcher", role="researcher"),
    "operator": Persona(
        id="operator@demo.local", display_name="Platform Operator", role="operator"
    ),
}


@dataclass(frozen=True, slots=True)
class SessionToken:
    actor: Persona
    nonce: str
    expires_at: int


def _urlsafe(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _unurlsafe(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_session(
    persona: Persona,
    settings: Settings,
    *,
    now: int | None = None,
) -> tuple[str, str]:
    issued_at = int(time.time()) if now is None else now
    nonce = hashlib.sha256(f"{persona.id}:{issued_at}".encode()).hexdigest()[:24]
    payload = {
        "actor_id": persona.id,
        "role": persona.role,
        "nonce": nonce,
        "exp": issued_at + 8 * 60 * 60,
    }
    encoded = _urlsafe(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    signature = hmac.new(
        settings.session_secret.encode(), encoded.encode(), hashlib.sha256
    ).digest()
    token = f"{encoded}.{_urlsafe(signature)}"
    csrf = hmac.new(settings.csrf_secret.encode(), nonce.encode(), hashlib.sha256).hexdigest()
    return token, csrf


def parse_session(token: str, settings: Settings, *, now: int | None = None) -> SessionToken:
    try:
        encoded, supplied_signature = token.split(".", 1)
        expected = hmac.new(
            settings.session_secret.encode(), encoded.encode(), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(expected, _unurlsafe(supplied_signature)):
            raise HTTPException(status_code=401, detail="Invalid demo session")
        payload = json.loads(_unurlsafe(encoded))
        actor_id = str(payload["actor_id"])
        role = str(payload["role"])
        nonce = str(payload["nonce"])
        expires_at = int(payload["exp"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=401, detail="Invalid demo session") from error
    current_time = int(time.time()) if now is None else now
    if expires_at <= current_time:
        raise HTTPException(status_code=401, detail="Demo session expired")
    actor = next(
        (
            persona
            for persona in PERSONAS.values()
            if persona.id == actor_id and persona.role == role
        ),
        None,
    )
    if actor is None:
        raise HTTPException(status_code=401, detail="Unknown demo persona")
    return SessionToken(actor=actor, nonce=nonce, expires_at=expires_at)


def get_actor(
    request: Request,
    ehrfs_session: Annotated[str | None, Cookie()] = None,
) -> Persona:
    if ehrfs_session is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    settings: Settings = request.app.state.settings
    return parse_session(ehrfs_session, settings).actor


def require_roles(*roles: Role) -> Callable[..., Persona]:
    def dependency(actor: Annotated[Persona, Depends(get_actor)]) -> Persona:
        if actor.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient role")
        return actor

    return dependency


def validate_csrf(
    request: Request,
    x_csrf_token: Annotated[str | None, Header()] = None,
    ehrfs_session: Annotated[str | None, Cookie()] = None,
) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    if request.url.path == "/api/v1/session":
        return
    if ehrfs_session is None or x_csrf_token is None:
        raise HTTPException(status_code=403, detail="CSRF token required")
    settings: Settings = request.app.state.settings
    session = parse_session(ehrfs_session, settings)
    expected = hmac.new(
        settings.csrf_secret.encode(), session.nonce.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, x_csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
