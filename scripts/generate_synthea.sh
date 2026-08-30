#!/usr/bin/env bash
set -euo pipefail

population=${1:-500}
seed=${2:-20260828}
end_date=${3:-20260828}
project_root=$(realpath -- "$(dirname -- "$0")/..")
output=${4:-"$project_root/data/generated/synthea-${population}"}
output=$(realpath -m -- "$output")
generated_root=$(realpath -- "$project_root/data/generated")

if [[ ! "$population" =~ ^[1-9][0-9]*$ || ! "$seed" =~ ^[0-9]+$ ]]; then
  echo "population and seed must be positive integers" >&2
  exit 2
fi
if [[ ! "$end_date" =~ ^[0-9]{8}$ ]]; then
  echo "end date must use YYYYMMDD" >&2
  exit 2
fi
if [[ "$output" != "$generated_root"/* || -e "$output" ]]; then
  echo "output must be a new directory below data/generated: $output" >&2
  exit 2
fi

docker build --file "$project_root/infra/docker/synthea.Dockerfile" \
  --tag ehrfs-synthea:4.0.0 "$project_root"
mkdir -p -- "$output"
docker run --rm --read-only \
  --user "$(id -u):$(id -g)" \
  --memory 4g \
  --cpus 8 \
  --tmpfs /tmp:rw,noexec,nosuid,size=256m \
  --volume "$output:/output" \
  ehrfs-synthea:4.0.0 \
  -s "$seed" \
  -e "$end_date" \
  -p "$population" \
  --exporter.baseDirectory /output \
  --exporter.fhir.export true \
  --exporter.fhir.bulk_data true \
  --exporter.fhir.use_us_core_ig false \
  --exporter.hospital.fhir.export false \
  --exporter.practitioner.fhir.export false \
  --exporter.metadata.export true \
  --generate.log_patients.detail none
uv run python "$project_root/scripts/record_synthea_manifest.py" "$output" \
  --population "$population" --seed "$seed" --end-date "$end_date"
