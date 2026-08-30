# Ten-minute demonstration

## Before the meeting

From the repository root:

```bash
cp .env.example .env  # once, if .env does not exist
make showcase-up
make showcase-check
```

`showcase-up` starts the complete CPU profile, waits for readiness, and resets only the synthetic
scenario. Keep these tabs open:

| Surface         | URL                             | Purpose                           |
| --------------- | ------------------------------- | --------------------------------- |
| Web application | <http://localhost:3000>         | Guided product flow               |
| OpenAPI         | <http://localhost:8000/docs>    | Typed service contract            |
| Grafana         | <http://localhost:3001>         | Provisioned operational dashboard |
| Prometheus      | <http://localhost:9090>         | Live metrics and targets          |
| Airflow         | <http://localhost:8088>         | Optional scheduler adapter        |
| MinIO           | <http://localhost:9001>         | Evidence/release object store     |
| OCR health      | <http://localhost:8081/healthz> | Isolated local CPU inference      |

Grafana's synthetic local credentials are `ehrfs` / `ehrfs-local-only`. MinIO credentials are in
the local `.env`. These values are demo-only and are rejected as production configuration.

Run `make showcase-scale` once before presenting to rehearse the bounded one-million-event data
path. The reviewed full proof can be repeated with
`SHOWCASE_EVENTS=100000000 make showcase-scale`; it writes a measured JSON report under
`artifacts/benchmarks/`.

## 0:00–1:00 — architecture

Open Command center and the French case-study PDF. Explain deterministic design-time/runtime
separation, canonical versus OMOP responsibility, and why PostgreSQL leases keep core durable
without Airflow.

Point to the live published-event count, which comes from the current research release. Then show
the separately labeled 100-million-event evidence. State the boundary plainly: the former is the
complete correctness path; the latter is a canonical/Parquet scale and memory proof.

## 1:00–3:00 — structured semantics

Open Source explorer and Form registry. Compare allergy versions 3 and 4, both fingerprints,
explicit negative/unknown states, hidden conditional answers, repeated blood-pressure pairs, and
the corrected weight lifecycle.

## 3:00–5:00 — governed mapping

As Engineer, inspect the version-4 draft and test vectors. Switch to Clinical steward, approve it,
and verify the immutable artifact checksum and signature. Point out that the application never
mutates Git.

## 5:00–7:00 — controlled failure and replay

Open Quarantine, show `UNKNOWN_FORM_VERSION` with source evidence, enqueue replay with the new
release, then compare the parent and child research releases. The original release remains intact.

## 7:00–8:00 — document evidence

Open Document lab. Show the committed golden evidence available in core, then the optional local
OCR profile: native-text-first routing, boxes, model/device version, confidence, deterministic
French negation/uncertainty, and abstention.

## 8:00–10:00 — research fitness

Open OMOP explorer, follow Lineage back to the source pointer, and finish in Research catalog.
Compare completion, usable coverage, prevalence, method, site, period, and limitations. Close by
stating that coverage is not semantic equivalence and that the test vocabulary is non-clinical.

## Defensible architecture discussion

The current live path proves the semantic model, immutable artifacts, quality gates, leased jobs,
replay, release membership, and evidence lineage. The measured scale path proves that canonical
work stays bounded at 50,000 events, is deterministic, and does not duplicate publication.

For a real bulk deployment, describe the next boundary from ADR 0009: one parent batch freezes all
manifests and semantic versions; leased workers produce idempotent partition artifacts and OMOP
staging rows; one retryable finalizer verifies all expected checksums and commits a single immutable
research release. Do not propose one release per response.

Do not claim HDS certification, clinical validation, licensed-vocabulary standardization, or
measured end-to-end 100-million-event throughput. A production qualification would still need the
target infrastructure, representative source mix, concurrent workers, database/object-store load,
fault injection, soak, recovery objectives, and security/legal review. This boundary is a strength:
the evidence says exactly what was tested.

## Reset and stop

After a rehearsal, `make showcase-reset` restores the opening synthetic state. `make down` stops
services without deleting volumes or evidence.
