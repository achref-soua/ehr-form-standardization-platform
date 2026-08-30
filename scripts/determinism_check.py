"""Prove deterministic checksums across every semantic publication stage."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from ehrfs.demo import allergy_form, demo_mapping_artifact, demo_response_payload
from ehrfs.domain.identity import content_hash
from ehrfs.fingerprinting.service import fingerprint_form
from ehrfs.pipeline.service import run_fhir_pipeline
from ehrfs.security.signing import ReleaseSigner

EVALUATED_AT = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


def execute(signer: ReleaseSigner) -> dict[str, object]:
    definition = allergy_form()
    mapping = demo_mapping_artifact(signer, release_id="mapping-determinism-v3")
    result = run_fhir_pipeline(
        definition=definition,
        response_payload=demo_response_payload(),
        establishment_id="site-a",
        source_system_id="site-a-ehr",
        batch_id="determinism-v3",
        patient_pseudonym="p-deterministic",
        definition_object_key="raw/golden/form-v3.json",
        response_object_key="raw/golden/response-v3.json",
        mapping_release=mapping,
        signer=signer,
        evaluated_at=EVALUATED_AT,
    )
    fingerprints = fingerprint_form(definition)
    return {
        "source_definition_sha256": fingerprints.source,
        "mapping_compatibility_sha256": fingerprints.compatibility,
        "source_manifest_sha256": content_hash(result.source_manifest.model_dump(mode="json")),
        **result.checksums.model_dump(mode="json"),
    }


def main() -> int:
    signer = ReleaseSigner.generate()
    first = execute(signer)
    second = execute(signer)
    if first != second:
        print(json.dumps({"first": first, "second": second}, indent=2, sort_keys=True))
        return 1
    print(json.dumps(first, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
