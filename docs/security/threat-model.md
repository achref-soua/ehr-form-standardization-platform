# Threat model

## Protected assets

Source clinical documents, pseudonymous identities, mapping/research signing keys, terminology
licences, audit integrity, and reproducible release artifacts are protected assets. The demo
contains no real patient data, but its boundaries assume those assets would be sensitive.

## Principal threats and controls

| Threat | Control |
| --- | --- |
| Cross-role mutation | Route-level RBAC, signed HttpOnly session, CSRF, audit event |
| Identifier disclosure | Site-local HMAC, redacted logs, aggregate schema, small-cell suppression |
| Path/archive/XML attack | Basename normalization, allowlisted signatures, defused XML, and in-memory ZIP validation for traversal, links, encryption, nesting, entry/total size, and compression ratio |
| Malicious document | Optional ClamAV profile; no-op limited to explicitly generated demo fixtures |
| Mapping tamper | Maker/checker, immutable SHA-256 object, Ed25519 signature, verification endpoint |
| Replay/double publication | API idempotency, leased queue, uniqueness, immutable child release |
| SSRF/hosted inference | Fixed configured S3/OCR endpoints; OCR process is local-only |
| Stolen evidence URL | Short expiry, bucket allowlist, access audit |
| Dependency/image compromise | Lockfiles, image digests, audits, SBOM and container scans in CI |
| Denial of service | Upload/archive limits, bounded 50,000-event work units, cursor limits, worker leases and retry caps |

Runtime audit access is append-only. Resetting the synthetic demonstration preserves existing audit
rows and appends a fresh seed event instead of deleting security history.

## Residual risk

Demo session identities are not production SSO, local Compose secrets are intentionally public,
database column encryption and a KMS are deployment responsibilities, the publisher covers five
OMOP domains rather than a complete clinical ETL, and mapping correctness still requires qualified
governance.
