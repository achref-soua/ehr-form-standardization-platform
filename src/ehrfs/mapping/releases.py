"""Create and verify immutable mapping-release artifacts."""

from __future__ import annotations

from datetime import datetime

from ehrfs.domain.enums import AnswerState
from ehrfs.domain.errors import DomainError
from ehrfs.domain.identity import canonical_json_bytes, content_hash
from ehrfs.mapping.models import MappingEntry, MappingReleaseArtifact, VocabularyRelease
from ehrfs.security.signing import ReleaseSigner
from ehrfs.standardization.conversion import convert_unit, normalize_source_value


def validate_mapping_tests(entries: tuple[MappingEntry, ...]) -> None:
    """Execute every release vector through the declarative transformation subset."""
    for entry in entries:
        for vector in entry.tests:
            state = entry.state_map.get(vector.source_state, vector.source_state)
            value = vector.source_value
            unit = vector.source_unit
            if state == AnswerState.PRESENT and value is not None:
                normalized = normalize_source_value(value)
                if normalized in entry.missing_value_codes:
                    state = AnswerState.UNKNOWN
                    value = None
                    unit = None
                elif normalized in entry.negative_value_codes:
                    state = AnswerState.EXPLICITLY_ABSENT
                    value = None
                    unit = None
                else:
                    if entry.value_map:
                        value = entry.value_map.get(normalized)
                    if entry.unit_rule is not None:
                        if unit != entry.unit_rule.source_unit:
                            value = None
                        else:
                            value = (
                                convert_unit(value, entry.unit_rule) if value is not None else None
                            )
                            unit = entry.unit_rule.target_unit
            elif state != AnswerState.PRESENT:
                value = None
                unit = None
            observed = (state, value, unit)
            expected = (vector.expected_state, vector.expected_value, vector.expected_unit)
            if observed != expected:
                detail = (
                    f"{entry.mapping_id}/{vector.name}: "
                    f"expected {expected!r}, observed {observed!r}"
                )
                raise DomainError(
                    "MAPPING_TEST_FAILED",
                    detail,
                )


def sign_mapping_release(
    provisional: MappingReleaseArtifact,
    signer: ReleaseSigner,
) -> MappingReleaseArtifact:
    """Finalize a typed release whose stable identity is already assigned."""
    validate_mapping_tests(provisional.entries)
    unsigned = provisional.unsigned_payload()
    signed = signer.sign(canonical_json_bytes(unsigned))
    return provisional.model_copy(
        update={
            "payload_checksum_sha256": content_hash(unsigned),
            "signature_base64": signed.signature_base64,
            "signing_key_id": signed.signing_key_id,
        }
    )


def create_mapping_release(
    *,
    parent_release_id: str | None,
    vocabulary_release: VocabularyRelease,
    entries: tuple[MappingEntry, ...],
    authored_by: str,
    approved_by: str,
    approved_at: datetime,
    signer: ReleaseSigner,
) -> MappingReleaseArtifact:
    core = {
        "schema_version": "1.0",
        "parent_release_id": parent_release_id,
        "vocabulary_release": vocabulary_release.model_dump(),
        "entries": [entry.model_dump() for entry in entries],
        "authored_by": authored_by,
        "approved_by": approved_by,
        "approved_at": approved_at.isoformat(),
    }
    release_id = f"mapping_{content_hash(core)[:16]}"
    provisional = MappingReleaseArtifact(
        release_id=release_id,
        parent_release_id=parent_release_id,
        vocabulary_release=vocabulary_release,
        entries=entries,
        authored_by=authored_by,
        approved_by=approved_by,
        approved_at=approved_at,
        payload_checksum_sha256="0" * 64,
        signature_base64="pending",
        signing_key_id=signer.key_id,
    )
    return sign_mapping_release(provisional, signer)


def verify_mapping_release(artifact: MappingReleaseArtifact, signer: ReleaseSigner) -> bool:
    if not artifact.has_valid_checksum() or artifact.signing_key_id != signer.key_id:
        return False
    return signer.verify(
        canonical_json_bytes(artifact.unsigned_payload()),
        artifact.signature_base64,
    )
