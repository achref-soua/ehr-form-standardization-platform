# Scope and limitations

This repository is a production-shaped demonstration built from synthetic and public data. It is
not HDS-certified, not a medical device, not a clinical decision-support system, and not validated
against EHR Form Standardization or Softway Medical systems.

The FHIR adapter implements a documented R4 subset and abstains on unsupported extensions. Generic
JSON/XML adapters accept only the public `ehrfs-structured/1.0` shape; they are not universal EHR
parsers. The CDA path extracts bounded narrative sections rather than claiming full CDA
conformance. ZIP inspection is intentionally limited to non-encrypted, non-nested archives and
never extracts members to disk.

The official OMOP 5.4.2 schema is present, but the publisher is bounded to five domains and the
bundled non-clinical vocabulary is suitable only for tests. A real claim of OMOP standardization
requires a compatible licensed Athena snapshot plus wider conformance and data-quality work. OCR
and text rules produce evidence-linked candidates and may abstain; they do not bypass quality
gates or replace structured facts when confidence is low.

The 100-million-event result measures bounded canonical Parquet generation, not end-to-end service
capacity. The live pipeline is a correctness and controls demonstration; it has not been qualified
with representative production concurrency, source distributions, infrastructure, or operating
conditions. See ADR 0009 for the intended coordinated bulk-publication boundary.

Pseudonymization is not anonymization. A real health-data warehouse requires a legal basis,
governance, retention policy, rights process, security assessment, and applicable CNIL/HDS steps.
