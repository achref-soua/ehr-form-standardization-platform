# ADR 0004: Canonical source and OMOP projection

Status: Accepted — 2026-08-29

## Decision

Canonical answer events are the lossless semantic source. Raw objects, canonical Parquet, and OMOP
remain separate. OMOP 5.4 table selection follows concept domain. Release membership and lineage
use control-plane tables instead of custom columns on standard OMOP tables.

## Consequences

Source states and evidence survive even when OMOP cannot represent them directly. Research releases
can change membership without mutating older releases. The bounded subset does not claim a full CDM
or Data Quality Dashboard deployment.
