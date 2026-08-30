"""Record checksummed provenance for an explicitly generated Synthea profile."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

SYNTHEA_VERSION = "4.0.0"
SYNTHEA_RELEASE_COMMIT = "0185c09"
SYNTHEA_JAR_SHA256 = "ed43c20ad40ba5c3bc724503a5af032715fe3c491620b766148e7c2361e6ecc1"
BASE_IMAGE = (
    "eclipse-temurin:25-jre-jammy@"
    "sha256:10c251954d0bfe1a59ba93505f8c628d755919412400aa98685764c9353605d6"
)


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(output: Path, *, population: int, seed: int, end_date: str) -> dict[str, object]:
    files: list[dict[str, object]] = []
    total_bytes = 0
    dataset_digest = hashlib.sha256()
    for path in sorted(candidate for candidate in output.rglob("*") if candidate.is_file()):
        if path.name == "manifest.json":
            continue
        relative = path.relative_to(output).as_posix()
        checksum = file_digest(path)
        size = path.stat().st_size
        files.append({"path": relative, "bytes": size, "sha256": checksum})
        total_bytes += size
        dataset_digest.update(relative.encode())
        dataset_digest.update(b"\0")
        dataset_digest.update(bytes.fromhex(checksum))
    return {
        "source": "https://github.com/synthetichealth/synthea",
        "version": SYNTHEA_VERSION,
        "release_commit": SYNTHEA_RELEASE_COMMIT,
        "licence": "Apache-2.0",
        "jar_sha256": SYNTHEA_JAR_SHA256,
        "base_image": BASE_IMAGE,
        "settings": {
            "population": population,
            "seed": seed,
            "end_date": end_date,
            "fhir_r4": True,
            "bulk_ndjson": True,
            "us_core_ig": False,
            "hospital_exports": False,
            "practitioner_exports": False,
        },
        "file_count": len(files),
        "total_bytes": total_bytes,
        "dataset_sha256": dataset_digest.hexdigest(),
        "files": files,
        "contains_real_patient_data": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--population", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--end-date", required=True)
    arguments = parser.parse_args()
    manifest = build_manifest(
        arguments.output,
        population=arguments.population,
        seed=arguments.seed,
        end_date=arguments.end_date,
    )
    destination = arguments.output / "manifest.json"
    destination.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in manifest.items() if key != "files"}, indent=2))


if __name__ == "__main__":
    main()
