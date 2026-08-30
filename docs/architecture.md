# Architecture

## Runtime boundaries

The platform is a modular Python monolith with independent process entry points. FastAPI owns the
HTTP boundary; the worker claims PostgreSQL jobs through leases and `FOR UPDATE SKIP LOCKED`; the
CLI calls the same services; Airflow may schedule API work but contains no mapping, clinical, or
quality logic. This keeps the bounded deployment understandable while allowing every process to
scale or restart independently.

PostgreSQL contains control-plane metadata, durable jobs, audit events, release membership, and an
official OMOP 5.4.2 schema. The demonstration publishes only its supported concept domains into
`observation`, `measurement`, `condition_occurrence`, `note`, and `note_nlp`; it does not alter
standard CDM tables with release columns. MinIO keeps raw evidence, canonical Parquet, mapping
releases, and research release manifests in separate versioned buckets.

## Semantic flow

1. A source adapter validates the declared format and rejects ambiguous semantics. FHIR R4 is a
   documented subset; generic JSON/XML inputs must declare `ehrfs-structured/1.0`; EAV inputs use
   an explicit typed contract. Arbitrary vendor payloads are never guessed into that contract.
2. A complete fingerprint identifies the source definition; a compatibility fingerprint selects
   mappings without ignoring meaning-bearing changes.
3. Canonicalization preserves typed value, answer state, repeat instance, correction/void link,
   and an exact JSON Pointer, XML locator, text span, or page box. It never turns absence into a
   negative fact. A correction creates a new event and marks its referenced predecessor
   `SUPERSEDED` only in a new release view.
4. A released mapping is resolved by source override, exact fingerprint, or exact family/item.
5. Whitelisted transformations and quality rules publish, quarantine, or abstain.
6. Domain metadata selects the OMOP target table. Release membership remains outside standard
   OMOP tables.
7. Catalog metrics are calculated for a named research release and lineage connects every metric
   and fact back to evidence.

## Deployment modes

In `central` mode the establishment uses a site-local HMAC key before any raw archival and the
central pipeline handles pseudonymous patient-level events. In `site` mode patient-level output
does not leave the establishment. Only signed aggregate bundles can be imported centrally; their
schema cannot contain patient identifiers or answer rows and small cells are suppressed.

## Trust boundaries

- Browser to API: signed HttpOnly session, strict SameSite cookie, CSRF token, RBAC, correlation ID.
- API/worker to PostgreSQL: separate least-privilege application roles.
- API/worker to MinIO: bucket-scoped credentials in production; content-addressed immutable keys.
- Documents: MIME/signature checks, in-memory ZIP inspection, ClamAV boundary, native PDF/CDA text
  first, and local HTTP OCR only for relevant image-only evidence.
- Mapping/research publication: durable artifact first, database pointer second, checksum and
  Ed25519 verification at read time.

## Deliberate omissions

There is no vector database, distributed event bus, or generative publishing path. Lexical
suggestions may help a steward find terminology candidates, but only deterministic released
artifacts can affect runtime facts. The official CDM schema is installed, while the bounded
publisher and checks are not presented as a replacement for a complete production ETL or an OHDSI
Data Quality Dashboard assessment.

## Scale-validation boundary

The live scenario validates the whole semantic and evidence chain on a small deterministic fixture.
The separate 100-million-event harness validates bounded canonical Parquet work units, memory,
deterministic checksums, and duplicate detection; it does not traverse FastAPI, PostgreSQL, MinIO,
quality publication, and OMOP for every event.

For production bulk loads, a parent batch coordinator freezes the manifests and semantic release
bindings, fans out idempotent 50,000-event partition jobs, and waits for all expected checksums. A
retryable finalizer then verifies completeness and uniqueness, bulk-loads eligible OMOP staging
rows, calculates catalog/lineage outputs, and atomically exposes one research release. See
[ADR 0009](adr/0009-scale-validation-and-bulk-orchestration.md).
