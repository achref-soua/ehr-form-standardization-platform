# Operations and runbooks

## Failed batch

Find the run by correlation ID, inspect its failure code without logging clinical payloads, and
confirm whether the job has retries remaining. Correct infrastructure or release configuration,
then enqueue with a new idempotency key. Never edit a completed output in place.

## Unknown form version

Keep the source object immutable and the record quarantined. Compare both fingerprints, inspect
meaning-bearing differences, author mapping tests, obtain a different checker, publish the signed
artifact, and replay into a new research release.

## Mapping correction and replay

Create a child mapping release; do not modify the old JSON. Resolve selected quarantine records or
source batches and create a child research release. Verify both artifact checksums, compare catalog
metrics, and retain prior release membership.

## Database migration failure

Stop API and workers, preserve database and object snapshots, inspect the Alembic version and the
failed statement, and restore into an isolated instance before trying a corrected forward
migration. Never stamp a production database without verifying schema state.

## Object-store unavailability

Readiness must report degraded and mapping/research publication must stop before committing a
database pointer. Restore MinIO connectivity, verify bucket versioning and credentials, then retry
with the same idempotency key.

## OCR failure or low confidence

Core structured processing remains available. Check `/readyz`, local model volume capacity, image
checksum, media/pixel limits, and the recorded Paddle versions. A low-confidence span remains an
evidence-linked candidate or quarantine item; operators must not lower the threshold to force a
fact through.

## Low disk space

Pause ingestion, identify growth in PostgreSQL, MinIO, model, and generated-artifact volumes, and
take a verified backup. Use `make clean-preview` only for host build artifacts. Never delete source
or release objects merely to recover space.

## Backup and restore

Run `scripts/backup.sh <directory>` to create a PostgreSQL custom dump, MinIO object archive, and
checksum manifest. Run `scripts/restore.sh <directory>` only into an empty recovery environment.
The verification script restores to isolated names and compares counts and object checksums before
declaring success.

## Demo reset

`make reset-demo` deletes and recreates only rows bearing deterministic demonstration identities.
It does not remove databases, buckets, volumes, keys, or user-provided uploads. Re-run browser
screenshots after reset if UI fixtures changed.

## Health and alerts

The API exposes liveness/readiness, build metadata, dependency state, Prometheus request latency
and status metrics, pipeline outcomes, catalog freshness, and OCR distributions. Alert on absent
worker heartbeat, job failure growth, quarantine-rate spikes, object-store readiness, catalog
staleness, OCR abstention, and disk pressure. Labels must never include identifiers or raw text.
