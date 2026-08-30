# Security policy

This reference implementation processes synthetic data by default and is not a certified health
data hosting platform. Report vulnerabilities privately to `achref.soua@outlook.com`; do not open
a public issue containing exploit details or sensitive data.

Supported code is the latest release on `main`. Never submit real patient records, credentials,
private form definitions, terminology archives, or signing keys.

Security boundaries include strict input validation, bounded uploads, safe XML parsing,
parameterized SQL, role checks, CSRF protection, audit events, local-only OCR, redacted logs, and
immutable signed release manifests. Production deployment additionally requires an organization-
specific legal assessment, identity provider, TLS, secret manager, network controls, backups,
monitoring, and applicable HDS/CNIL controls.
