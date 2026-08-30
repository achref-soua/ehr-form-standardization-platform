#!/bin/sh
set -eu

until mc alias set local "${EHRFS_S3_ENDPOINT}" "${EHRFS_S3_ACCESS_KEY}" "${EHRFS_S3_SECRET_KEY}"; do
  sleep 1
done

for bucket in ehrfs-raw ehrfs-canonical ehrfs-documents ehrfs-mapping-releases ehrfs-research-releases; do
  mc mb --ignore-existing "local/${bucket}"
  mc version enable "local/${bucket}"
done
