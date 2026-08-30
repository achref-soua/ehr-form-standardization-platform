# ADR 0007: Terminology licensing boundary

Status: Accepted — 2026-08-29

## Decision

Support importing a pinned Athena snapshot, record its release identity, and never redistribute
restricted terminology. Automated tests use an explicitly non-clinical project vocabulary.

## Consequences

The repository demonstrates OMOP domain routing and vocabulary binding without licensing claims.
A demonstration may call output clinically standardized only after loading and verifying a
compatible licensed vocabulary release.
