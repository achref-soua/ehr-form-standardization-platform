# Data and licence registry

| Asset | Source/version | Licence | Repository policy |
| --- | --- | --- | --- |
| Deterministic form fixtures | Project-owned, schema 1.0 | Apache-2.0 | Small fixtures committed |
| Synthetic OCR documents | Project generator, seed `20260828` | Apache-2.0 | Images, degradation manifest, and golden evidence committed |
| Synthea | v4.0.0 pinned container, seed `20260828` | Apache-2.0 | Generated 500-patient output ignored; compact measured manifest retained |
| FHIR R4 examples | Project-authored compatible structures | Apache-2.0 | No private EHR schema |
| OMOP CDM 5.4.2 DDL | OHDSI release v5.4.2 | Apache-2.0 | Official PostgreSQL DDL, keys, indices, and constraint source vendored with checksums |
| Athena vocabulary | User-provided pinned snapshot | OHDSI/Athena terms | Local chunked import; restricted terminology never committed |
| PaddleOCR models | Downloaded by isolated profile | Apache-2.0/model-specific notice | Weights stay in an ignored Docker volume |
| Project logo | Project-authored SVG | Apache-2.0 | Original geometric wordmark used by the app and documentation |

Every generated bulk-data manifest records source URL, version or image digest, licence, seeds,
generator settings, output checksum, and a `contains_real_patient_data=false` assertion. Fetching
external data is always explicit; `ehrfs data fetch` never downloads silently.

The measured 500-living-patient generation is recorded in
[`data/manifests/synthea-500.json`](../../data/manifests/synthea-500.json). Synthea preserves the
seeded clinical population, while parallel bulk-file ordering and generated run metadata can vary;
the recorded dataset checksum therefore identifies that exact run.

The test vocabulary uses concept IDs in a project-owned non-clinical namespace. It proves routing,
release, and lineage mechanics only. Load and bind a compatible licensed Athena release before
describing results as clinically standardized concepts.

Import a licensed export explicitly with:

```bash
uv run ehrfs vocabulary import-athena /secure/path/to/athena \
  --release-id athena-2026-08 --vocabulary-version "Athena 2026-08-01"
```

The importer requires `DOMAIN.csv`, `VOCABULARY.csv`, `CONCEPT_CLASS.csv`, and `CONCEPT.csv`,
rejects symlinks and schema drift, validates every row, loads bounded batches in one transaction,
and records the aggregate source checksum. It never downloads or commits terminology.
