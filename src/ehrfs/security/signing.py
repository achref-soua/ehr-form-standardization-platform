"""Detached Ed25519 signatures for immutable release content."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


@dataclass(frozen=True, slots=True)
class SignedPayload:
    signature_base64: str
    signing_key_id: str


class ReleaseSigner:
    def __init__(
        self,
        *,
        private_key: Ed25519PrivateKey | None,  # gitleaks:allow -- typed key object, not material
        public_key: Ed25519PublicKey,
    ) -> None:
        self._private_key = private_key
        self._public_key = public_key

    @classmethod
    def generate(cls) -> ReleaseSigner:
        private_key = Ed25519PrivateKey.generate()
        return cls(private_key=private_key, public_key=private_key.public_key())

    @classmethod
    def from_private_pem(cls, value: bytes, password: bytes | None = None) -> ReleaseSigner:
        private_key = serialization.load_pem_private_key(value, password=password)
        if not isinstance(private_key, Ed25519PrivateKey):
            msg = "Expected an Ed25519 private key"
            raise TypeError(msg)
        return cls(private_key=private_key, public_key=private_key.public_key())

    @classmethod
    def from_public_pem(cls, value: bytes) -> ReleaseSigner:
        public_key = serialization.load_pem_public_key(value)
        if not isinstance(public_key, Ed25519PublicKey):
            msg = "Expected an Ed25519 public key"
            raise TypeError(msg)
        return cls(private_key=None, public_key=public_key)

    @property
    def key_id(self) -> str:
        raw = self._public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return hashlib.sha256(raw).hexdigest()[:16]

    def private_pem(self) -> bytes:
        if self._private_key is None:
            msg = "This signer does not contain a private key"
            raise RuntimeError(msg)
        return self._private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

    def public_pem(self) -> bytes:
        return self._public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

    def sign(self, payload: bytes) -> SignedPayload:
        if self._private_key is None:
            msg = "A private key is required to sign a release"
            raise RuntimeError(msg)
        signature = self._private_key.sign(payload)
        return SignedPayload(base64.b64encode(signature).decode(), self.key_id)

    def verify(self, payload: bytes, signature_base64: str) -> bool:
        try:
            signature = base64.b64decode(signature_base64, validate=True)
            self._public_key.verify(signature, payload)
        except (InvalidSignature, ValueError):
            return False
        return True
