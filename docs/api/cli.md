# CLI reference

Run commands as `uv run ehrfs …`. `--help` is available at every group. Read commands support
`--json`; mutation commands return stable identifiers and exit non-zero on validation or runtime
failure.

| Command | Purpose |
| --- | --- |
| `preflight` | Read-only host/runtime capacity report |
| `data fetch` | Explain the explicit external acquisition boundary |
| `data generate` | Write deterministic synthetic identities and manifest |
| `source inventory` | Count discovered forms, jobs, and quarantine records |
| `forms fingerprint` | Calculate both definition fingerprints |
| `mappings validate` | Validate releases and maker/checker separation |
| `mappings release` | Point to the audited API approval boundary |
| `pipeline run` | Enqueue an idempotent durable batch job that writes raw, canonical, quality, OMOP, lineage, catalog, and release artifacts |
| `pipeline replay` | Enqueue a controlled quarantine replay |
| `quarantine list` | List reason/status without disclosing identity |
| `omop validate` | Verify the 39-table OMOP 5.4.2 shape and bounded conformance checks |
| `vocabulary import-athena DIR` | Validate and atomically load a licensed Athena snapshot |
| `catalog rebuild` | Verify catalog materialization state |
| `demo reset`, `demo run` | Reset or describe the guided flow |
| `benchmark` | Run the bounded streaming checksum harness |

Structured operational logs include correlation, job, batch, site, stage, release, outcome, and
failure code when available. Patient identifiers and clinical text are recursively redacted.
