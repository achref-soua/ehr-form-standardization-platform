# ADR 0005: PostgreSQL durable core orchestration

Status: Accepted — 2026-08-29

## Decision

Use PostgreSQL jobs with idempotency keys, `SKIP LOCKED` claims, leases, heartbeats, bounded retries,
and expired-lease recovery. Airflow is optional and schedules through the application boundary.

## Consequences

Core runs survive API and worker restarts without an Airflow dependency. PostgreSQL is appropriate
for this bounded workload; a distributed event platform would add operational cost without solving
a demonstrated requirement.
