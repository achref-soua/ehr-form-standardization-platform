# ADR 0009: Scale validation boundary and bulk orchestration

Status: Accepted — 2026-08-30

## Context

The bounded live scenario exercises the complete evidence path from immutable raw input through
canonical answers, mapping and quality decisions, OMOP projection, release membership, catalog
metrics, and lineage. The measured 100-million-event harness exercises a different concern:
bounded canonical Parquet serialization, stable partitioning, deterministic checksums, memory use,
and duplicate-publication detection.

Treating either result as proof of the other would hide important database, object-store, queue,
network, and coordination costs. Creating one research release for every source response would
also make release finalization increasingly expensive and is not the intended bulk design.

## Decision

Keep three validation levels explicit:

1. The live synthetic scenario validates end-to-end semantics and control-plane behavior.
2. The 100-million-event harness validates the bounded canonical data-plane algorithm on the
   recorded machine. It is not an API/PostgreSQL/MinIO/OMOP load test.
3. A production qualification must use representative source distributions and the target
   infrastructure, with multi-worker load, fault injection, soak, recovery, and security tests.

Production bulk ingestion will retain the existing leased PostgreSQL queue but add a parent batch
coordinator. The coordinator freezes source manifests and all semantic release bindings, creates
bounded partition jobs, and records expected partition identities. Workers write content-addressed
raw/canonical/quality outputs and partition-scoped OMOP staging rows idempotently. A finalizer runs
only after every expected partition is terminal, verifies counts and checksums, rejects duplicate
clinical-event identities, bulk-loads eligible OMOP rows, calculates catalog and lineage outputs,
and commits one immutable research-release manifest as the publication barrier.

The finalizer is retryable and cannot expose a partially published research release. Replays create
a new parent batch and release; they never rewrite prior artifacts or memberships.

## Consequences

The demonstration can show real end-to-end behavior and measured large-volume data-plane evidence
without claiming an unmeasured production throughput. The future bulk path scales work units and
publication independently, preserves the existing determinism and evidence contracts, and avoids a
distributed event platform until measured queue contention or latency demonstrates that need.

Production qualification remains environment-specific. It must report source mix, concurrency,
database/object-store sizing, queue latency, end-to-end throughput, p95/p99 latency, error and retry
rates, recovery point/time, and cost; extrapolation from the canonical harness is prohibited.
