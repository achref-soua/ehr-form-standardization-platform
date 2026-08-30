"""Structured errors shared by API and CLI boundaries."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class DomainError(Exception):
    code: str
    message: str
    status_code: int = 422

    def __str__(self) -> str:
        return self.message


class NotFoundError(DomainError):
    def __init__(self, resource: str, identifier: str) -> None:
        super().__init__(
            code="NOT_FOUND",
            message=f"{resource} '{identifier}' was not found",
            status_code=404,
        )


class ConflictError(DomainError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code=code, message=message, status_code=409)
