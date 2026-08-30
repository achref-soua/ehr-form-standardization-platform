"""Measure the local OCR profile and validate an evidence-linked French candidate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter

from ehrfs.documents.assertion import extract_allergy_candidate
from ehrfs.documents.ocr import HttpOcrAdapter
from ehrfs.domain.enums import AnswerState, ExtractionMethod
from ehrfs.domain.identity import sha256_hex
from ehrfs.domain.models import EvidenceReference

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "data/fixtures/ocr/allergy-clean.png"
DEFAULT_REPORT = ROOT / "artifacts/benchmarks/ocr-cpu.json"
NO_SPANS_MESSAGE = "Local OCR returned no evidence spans"
ABSTAINED_MESSAGE = "Local OCR did not produce the expected bounded allergy candidate"


def run(endpoint: str) -> dict[str, object]:
    content = FIXTURE.read_bytes()
    started = perf_counter()
    extraction = HttpOcrAdapter(endpoint, timeout_seconds=600).extract(
        content, media_type="image/png"
    )
    wall_ms = (perf_counter() - started) * 1000
    spans = tuple(span for page in extraction.pages for span in page.spans)
    if not spans:
        raise RuntimeError(NO_SPANS_MESSAGE)
    text = " ".join(span.text for span in spans)
    strongest = max(spans, key=lambda span: span.confidence)
    evidence = EvidenceReference(
        object_key="fixtures/ocr/allergy-clean.png",
        checksum_sha256=sha256_hex(content),
        media_type="image/png",
        page=1,
        bounding_box=strongest.bounding_box,
        extraction_method=ExtractionMethod.OCR_RULES,
        extractor_version=extraction.model_version,
        confidence=strongest.confidence,
    )
    candidate = extract_allergy_candidate(text, evidence=evidence)
    if candidate.assertion != AnswerState.PRESENT or candidate.failures:
        raise RuntimeError(ABSTAINED_MESSAGE)
    return {
        "fixture": str(FIXTURE.relative_to(ROOT)),
        "fixture_sha256": sha256_hex(content),
        "device": extraction.device,
        "model_version": extraction.model_version,
        "service_elapsed_ms": round(extraction.elapsed_ms, 3),
        "client_wall_ms": round(wall_ms, 3),
        "span_count": len(spans),
        "minimum_confidence": min(span.confidence for span in spans),
        "text": text,
        "candidate": candidate.model_dump(mode="json"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default="http://127.0.0.1:8081")
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    arguments = parser.parse_args()
    report = run(arguments.endpoint)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
