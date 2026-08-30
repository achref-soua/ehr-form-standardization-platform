from __future__ import annotations

from pathlib import Path

from scripts.record_synthea_manifest import SYNTHEA_JAR_SHA256, build_manifest


def test_synthea_manifest_is_complete_and_deterministic(tmp_path: Path) -> None:
    fhir = tmp_path / "fhir"
    fhir.mkdir()
    (fhir / "Patient.ndjson").write_text('{"resourceType":"Patient"}\n', encoding="utf-8")
    (tmp_path / "metadata.json").write_text('{"synthetic":true}\n', encoding="utf-8")

    first = build_manifest(tmp_path, population=2, seed=17, end_date="20260828")
    second = build_manifest(tmp_path, population=2, seed=17, end_date="20260828")

    assert first == second
    assert first["contains_real_patient_data"] is False
    assert first["file_count"] == 2
    assert first["jar_sha256"] == SYNTHEA_JAR_SHA256
    assert first["dataset_sha256"]
