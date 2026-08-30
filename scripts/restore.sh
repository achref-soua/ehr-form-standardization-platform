#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "usage: scripts/restore.sh <backup-directory> [new-database-name]" >&2
  exit 2
fi

restore_source=$(realpath -- "$1")
restore_database=${2:-ehrfs_restore}
if [[ ! "$restore_database" =~ ^[a-z][a-z0-9_]{2,62}$ ]]; then
  echo "invalid recovery database name" >&2
  exit 2
fi
if [[ ! -f "$restore_source/postgres.dump" || ! -f "$restore_source/SHA256SUMS" ]]; then
  echo "backup is incomplete" >&2
  exit 2
fi
(
  cd -- "$restore_source"
  sha256sum --check --strict SHA256SUMS
)

project_root=$(realpath -- "$(dirname -- "$0")/..")
compose=(docker compose -f "$project_root/infra/compose/compose.yaml")
exists=$("${compose[@]}" exec -T postgres psql -U ehrfs_owner -d postgres -Atqc \
  "SELECT 1 FROM pg_database WHERE datname = '$restore_database'")
if [[ "$exists" == "1" ]]; then
  echo "refusing to overwrite existing database: $restore_database" >&2
  exit 2
fi
"${compose[@]}" exec -T postgres createdb -U ehrfs_owner -O ehrfs_owner "$restore_database"
"${compose[@]}" exec -T postgres pg_restore -U ehrfs_owner -d "$restore_database" \
  < "$restore_source/postgres.dump"

restore_token=$(printf '%s' "$restore_database" | sha256sum | cut -c1-16)
restore_prefix="restore-$restore_token"
minio_container=$("${compose[@]}" ps -q minio)
if [[ -z "$minio_container" ]]; then
  echo "MinIO container is not running" >&2
  exit 1
fi
compose_project=$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project" }}' "$minio_container")
mapfile -t compose_networks < <(
  docker network ls \
    --filter "label=com.docker.compose.project=$compose_project" \
    --filter "label=com.docker.compose.network=default" \
    --format '{{.Name}}'
)
if [[ ${#compose_networks[@]} -ne 1 ]]; then
  echo "could not resolve the Compose default network" >&2
  exit 1
fi

docker run --rm --network "${compose_networks[0]}" \
  --user "$(id -u):$(id -g)" \
  --env MC_CONFIG_DIR=/tmp/.mc \
  --env "EHRFS_RESTORE_PREFIX=$restore_prefix" \
  --volume "$restore_source/objects:/backup:ro" \
  --entrypoint /bin/sh \
  minio/mc:RELEASE.2025-08-13T08-35-41Z@sha256:a7fe349ef4bd8521fb8497f55c6042871b2ae640607cf99d9bede5e9bdf11727 \
  -ceu '
    mc alias set local http://minio:9000 ehrfs-local ehrfs-local-secret >/dev/null
    for bucket in ehrfs-raw ehrfs-canonical ehrfs-documents ehrfs-mapping-releases ehrfs-research-releases; do
      destination="local/$EHRFS_RESTORE_PREFIX-$bucket"
      mc mb --ignore-existing "$destination" >/dev/null
      mc mirror --quiet "/backup/$bucket" "$destination"
      differences=$(mc diff "/backup/$bucket" "$destination")
      if [ -n "$differences" ]; then
        echo "object restore verification failed for $bucket" >&2
        echo "$differences" >&2
        exit 1
      fi
    done
  '

count_query='SELECT json_build_object(
  '\''establishments'\'', (SELECT count(*) FROM control.establishment),
  '\''forms'\'', (SELECT count(*) FROM control.form_version),
  '\''mapping_releases'\'', (SELECT count(*) FROM control.mapping_release),
  '\''pipeline_jobs'\'', (SELECT count(*) FROM control.pipeline_job),
  '\''quarantine'\'', (SELECT count(*) FROM control.quarantine_record),
  '\''research_releases'\'', (SELECT count(*) FROM control.research_release),
  '\''release_membership'\'', (SELECT count(*) FROM control.release_membership),
  '\''audit_events'\'', (SELECT count(*) FROM audit.audit_event),
  '\''omop_people'\'', (SELECT count(*) FROM omop.person),
  '\''omop_observations'\'', (SELECT count(*) FROM omop.observation)
)::text'
source_counts=$("${compose[@]}" exec -T postgres psql -U ehrfs_owner -d ehrfs -Atqc "$count_query")
restored_counts=$(
  "${compose[@]}" exec -T postgres psql -U ehrfs_owner -d "$restore_database" -Atqc "$count_query"
)
if [[ "$source_counts" != "$restored_counts" ]]; then
  echo "database restore verification failed" >&2
  echo "source:   $source_counts" >&2
  echo "restored: $restored_counts" >&2
  exit 1
fi
echo "restored into database $restore_database and object prefix $restore_prefix"
