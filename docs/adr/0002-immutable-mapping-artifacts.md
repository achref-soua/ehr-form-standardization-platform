# ADR 0002: PostgreSQL drafts and immutable mapping releases

Status: Accepted — 2026-08-29

## Decision

Editable drafts live in PostgreSQL. A different checker must approve a tested, vocabulary-bound
draft. Approval writes canonical JSON to MinIO under its SHA-256 identity, then records the
detached Ed25519 signature and pointer in PostgreSQL. The application can export files for human
review but never changes Git.

## Consequences

Publication stops during object-store outage, release identity is content-derived, and verification
does not depend on repository write access. Key rotation requires explicit key identity and trust
policy management.
