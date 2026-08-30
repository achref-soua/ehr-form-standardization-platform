#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: scripts/backup.sh <new-backup-directory>" >&2
  exit 2
fi

backup_target=$(realpath -m -- "$1")
project_root=$(realpath -- "$(dirname -- "$0")/..")
if [[ "$backup_target" == "/" || "$backup_target" == "$project_root" || -e "$backup_target" ]]; then
  echo "refusing unsafe or existing backup target: $backup_target" >&2
  exit 2
fi

mkdir -p -- "$backup_target/objects"
compose=(docker compose -f "$project_root/infra/compose/compose.yaml")
"${compose[@]}" exec -T postgres pg_dump -U ehrfs_owner -d ehrfs --format=custom \
  > "$backup_target/postgres.dump"

docker run --rm --network ehrfs_default \
  --user "$(id -u):$(id -g)" \
  --env MC_CONFIG_DIR=/tmp/.mc \
  --volume "$backup_target/objects:/backup" \
  --entrypoint /bin/sh \
  minio/mc:RELEASE.2025-08-13T08-35-41Z@sha256:a7fe349ef4bd8521fb8497f55c6042871b2ae640607cf99d9bede5e9bdf11727 \
  -ceu '
    mc alias set local http://minio:9000 ehrfs-local ehrfs-local-secret >/dev/null
    for bucket in ehrfs-raw ehrfs-canonical ehrfs-documents ehrfs-mapping-releases ehrfs-research-releases; do
      mkdir -p "/backup/$bucket"
      mc mirror --quiet "local/$bucket" "/backup/$bucket"
    done
  '

(
  cd -- "$backup_target"
  find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
)
chmod -R go-rwx -- "$backup_target"
echo "backup created at $backup_target"
