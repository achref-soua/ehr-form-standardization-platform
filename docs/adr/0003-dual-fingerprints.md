# ADR 0003: Complete and mapping-compatibility fingerprints

Status: Accepted — 2026-08-29

## Decision

Calculate a complete source-definition fingerprint and a compatibility fingerprint covering paths,
labels, types, values, units, repeats, conditions, calculations, hierarchy, and source-defined
semantic order. Preserve FHIR Questionnaire order; normalize only formats whose order is declared
irrelevant. Runtime accepts only fingerprints bound to a released mapping.

## Consequences

Cosmetic metadata can be distinguished from mapping-relevant change without ignoring semantic
drift. Unknown versions fail closed and enter quarantine.
