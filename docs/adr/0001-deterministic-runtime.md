# ADR 0001: Deterministic clinical runtime

Status: Accepted — 2026-08-29

## Decision

Only versioned declarative mappings, whitelisted transformations, and deterministic quality rules
may publish facts. Terminology search and optional models may suggest evidence-linked candidates,
but cannot approve mappings or publish facts.

## Consequences

Identical manifests and release inputs have comparable checksums. Ambiguity produces an explicit
failure or abstention, increasing steward work but preventing silent semantic invention. No vector
database, distributed event platform, or generative runtime is required for the bounded problem.
