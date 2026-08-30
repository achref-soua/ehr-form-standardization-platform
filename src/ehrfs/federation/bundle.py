"""Privacy-bounded aggregate exports for site-mode deployment."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import Field

from ehrfs.domain.identity import canonical_json_bytes, content_hash
from ehrfs.domain.models import DomainModel
from ehrfs.security.signing import ReleaseSigner


class SiteMetric(DomainModel):
    concept_key: str
    period_start: date
    period_end: date
    eligible_count: int | None = Field(default=None, ge=0)
    recorded_count: int = Field(ge=0)
    usable_count: int = Field(ge=0)
    positive_count: int = Field(ge=0)
    suppressed: bool = False


class SiteSummaryBundle(DomainModel):
    schema_version: Literal["1.0"] = "1.0"
    establishment_id: str
    mapping_release_ids: tuple[str, ...]
    research_release_id: str
    generated_at: datetime
    minimum_cell_threshold: int = Field(ge=1)
    metrics: tuple[SiteMetric, ...]


class SignedSiteSummary(DomainModel):
    bundle: SiteSummaryBundle
    payload_checksum_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    signature_base64: str
    signing_key_id: str


def _suppress(metric: SiteMetric, threshold: int) -> SiteMetric:
    visible_counts = [metric.recorded_count, metric.usable_count, metric.positive_count]
    if all(value == 0 or value >= threshold for value in visible_counts):
        return metric
    return metric.model_copy(
        update={
            "eligible_count": None,
            "recorded_count": 0,
            "usable_count": 0,
            "positive_count": 0,
            "suppressed": True,
        }
    )


def build_site_summary(
    *,
    establishment_id: str,
    mapping_release_ids: tuple[str, ...],
    research_release_id: str,
    generated_at: datetime,
    metrics: tuple[SiteMetric, ...],
    threshold: int,
    signer: ReleaseSigner,
) -> SignedSiteSummary:
    bundle = SiteSummaryBundle(
        establishment_id=establishment_id,
        mapping_release_ids=mapping_release_ids,
        research_release_id=research_release_id,
        generated_at=generated_at,
        minimum_cell_threshold=threshold,
        metrics=tuple(_suppress(metric, threshold) for metric in metrics),
    )
    payload = canonical_json_bytes(bundle.model_dump(mode="json"))
    signed = signer.sign(payload)
    return SignedSiteSummary(
        bundle=bundle,
        payload_checksum_sha256=content_hash(bundle.model_dump(mode="json")),
        signature_base64=signed.signature_base64,
        signing_key_id=signed.signing_key_id,
    )
