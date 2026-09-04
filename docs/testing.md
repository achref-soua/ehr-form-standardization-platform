# Verification strategy

## Local contracts

`make ci` is the required pull-request check. It verifies locks, formatting, linting, strict
typing, unit/property/security/document tests, coverage, frontend accessibility components,
OpenAPI drift, the production builds, dependency audits, the exact eight-page PDF, and the public
repository boundary. Security checks include local Semgrep rules, secret scanning, and fail-closed
Trivy scans of the built API, worker, and web images; container CI also emits BuildKit SBOM and
provenance attestations.

`make verify-all` additionally exercises PostgreSQL 18, MinIO, the browser workflow at
1440×900 and 390×844, deterministic replay, zero-survivor mutation testing, the full Airflow and
observability profile, ClamAV, OCR CPU/GPU profiles, backup/restore, regenerated screenshots and
PDF, and the measured 100-million-event performance harness. GPU verification is fail-closed: an
unavailable or misconfigured NVIDIA runtime fails the target rather than being silently skipped.
Hardware-dependent checks write measured reports under `artifacts/`; reviewed benchmark reports
under `docs/benchmarks/` identify the exact environment and command.

Scale evidence is deliberately layered. The browser scenario is a live end-to-end correctness
proof. `make showcase-scale` defaults to a one-million-event validation of the bounded canonical
path; `SHOWCASE_EVENTS=100000000 make showcase-scale` reruns the full measured data-plane proof.
Neither command claims end-to-end production throughput. That claim would require representative
source traffic through the target PostgreSQL, MinIO, worker, quality, OMOP, catalog, and lineage
deployment under concurrency, failure injection, and soak.

Browser acceptance writes diagnostic captures to Playwright's ignored test-output directory.
Only `make screenshots` resets the synthetic demo and regenerates the reviewed gallery under
`docs/assets/generated/`, so an ordinary `make ci` never rewrites committed visual assets. The
health capture keeps the live response but normalizes its timestamp and operational identifiers
after rendering; production UI and API responses remain unchanged.

## Scenario matrix

| Scenario                      | Expected invariant                                                           |
| ----------------------------- | ---------------------------------------------------------------------------- |
| Structured allergy            | Explicit positive/negative/unknown states remain distinct                    |
| Hidden conditional field      | Hidden is not unanswered and produces no invented value                      |
| Unknown version               | No compatible released mapping means quarantine                              |
| Changed value set             | Compatibility fingerprint changes                                            |
| Repeated blood pressure       | Systolic/diastolic pair and group instance remain linked                     |
| Corrected weight              | New event supersedes old; prior release stays reproducible                   |
| JSON/XML contract             | Versioned shape, typed scalar, locator, condition and repeat checks          |
| Hostile ZIP                   | Traversal, links, nesting, encryption, size and ratio fail before extraction |
| Invalid unit                  | Bounded conversion rejects and quarantines                                   |
| Structured/narrative conflict | Rule emits conflict and abstains from publication                            |
| Low OCR confidence            | Candidate is retained as evidence or quarantined, never promoted             |
| Maker/checker                 | Author cannot approve own mapping                                            |
| Controlled replay             | New mapping and research releases resolve the record                         |
| Catalog coverage              | Completion, usable coverage, and prevalence keep their denominators          |
| Site summary                  | Patient/answer fields are schema-impossible and small cells suppress         |
| Lineage                       | Raw object → canonical event → mapping → quality → OMOP → catalog            |

## Coverage and mutation policy

Critical canonical-state, fingerprint, mapping-resolution, conversion, quality-decision, coverage,
release-identity, and lineage modules require 100% statements and branches. The gate parses the
fresh coverage JSON and fails when any critical file or summary is absent. Repository Python
coverage must be at least 95%; frontend statements and branches must be at least 90%. Mutation
testing targets only critical semantics and must kill at least 90%, with no surviving high-risk
mutation. A bug fix must add a regression test.

## Determinism

The determinism check runs identical manifests and release inputs twice, sorts unordered tabular
definitions before hashing, and compares source-manifest, canonical, quality, OMOP, lineage, and
catalog checksums. Timestamps and UUIDv7 identifiers belong only to the operational plane and are
excluded from semantic identities.
