# ADR 0006: Central and site-local deployment modes

Status: Accepted — 2026-08-29

## Decision

Central mode pseudonymizes with an establishment-local HMAC key before archival and processes
patient-level data centrally. Site mode retains patient-level data locally and exports only signed,
schema-bounded aggregate catalog/quality bundles with configurable small-cell suppression.

## Consequences

The same semantics work under different governance constraints. Aggregate bundles reduce but do
not eliminate disclosure risk; site identities and counts still require governance.
