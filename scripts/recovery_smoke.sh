#!/usr/bin/env bash
set -euo pipefail

project_root=$(realpath -- "$(dirname -- "$0")/..")
recovery_id=${EHRFS_RECOVERY_RUN_ID:-$(date -u +%Y%m%d%H%M%S)-$$}
if [[ ! "$recovery_id" =~ ^[0-9]{14}-[0-9]+$ ]]; then
  echo "invalid recovery run identity" >&2
  exit 2
fi

backup_parent="$project_root/artifacts/recovery"
backup_target="$backup_parent/backup-$recovery_id"
recovery_database="ehrfs_restore_${recovery_id//-/}"
mkdir -p -- "$backup_parent"
if [[ -e "$backup_target" ]]; then
  echo "refusing existing recovery target: $backup_target" >&2
  exit 2
fi

"$project_root/scripts/backup.sh" "$backup_target"
"$project_root/scripts/restore.sh" "$backup_target" "$recovery_database"
echo "recovery smoke passed; retained isolated evidence at $backup_target"
