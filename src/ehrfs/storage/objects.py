"""Content-addressed S3-compatible object storage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Protocol

import boto3
from botocore.exceptions import ClientError

if TYPE_CHECKING:
    from types_boto3_s3.client import S3Client

from ehrfs.config import Settings
from ehrfs.domain.identity import sha256_hex

MAXIMUM_EVIDENCE_URL_SECONDS = 900


@dataclass(frozen=True, slots=True)
class StoredObject:
    bucket: str
    key: str
    checksum_sha256: str
    size_bytes: int
    media_type: str


class ObjectStore(Protocol):
    def ready(self, *, bucket: str) -> bool: ...

    def put_immutable(
        self,
        *,
        bucket: str,
        namespace: str,
        content: bytes,
        media_type: str,
    ) -> StoredObject: ...

    def read(self, *, bucket: str, key: str) -> bytes: ...

    def signed_download_url(
        self,
        *,
        bucket: str,
        key: str,
        expires: timedelta,
    ) -> str: ...


class S3ObjectStore:
    def __init__(self, settings: Settings, client: S3Client | None = None) -> None:
        self._client = client or boto3.client(
            "s3",
            endpoint_url=str(settings.s3_endpoint),
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            use_ssl=settings.s3_use_ssl,
        )

    def ensure_bucket(self, bucket: str) -> None:
        """Create a versioned bucket when it does not already exist."""
        try:
            self._client.head_bucket(Bucket=bucket)
        except ClientError as error:
            code = str(error.response.get("Error", {}).get("Code", ""))
            if code not in {"404", "NoSuchBucket", "NotFound"}:
                raise
            self._client.create_bucket(Bucket=bucket)
            self._client.put_bucket_versioning(
                Bucket=bucket,
                VersioningConfiguration={"Status": "Enabled"},
            )

    def ready(self, *, bucket: str) -> bool:
        self._client.head_bucket(Bucket=bucket)
        return True

    def put_immutable(
        self,
        *,
        bucket: str,
        namespace: str,
        content: bytes,
        media_type: str,
    ) -> StoredObject:
        checksum = sha256_hex(content)
        key = f"{namespace.strip('/')}/{checksum[:2]}/{checksum}"
        try:
            existing = self._client.head_object(Bucket=bucket, Key=key)
        except ClientError as error:
            code = str(error.response.get("Error", {}).get("Code", ""))
            if code not in {"404", "NoSuchKey", "NotFound"}:
                raise
        else:
            return StoredObject(
                bucket=bucket,
                key=key,
                checksum_sha256=checksum,
                size_bytes=int(existing["ContentLength"]),
                media_type=str(existing.get("ContentType", media_type)),
            )
        self._client.put_object(
            Bucket=bucket,
            Key=key,
            Body=content,
            ContentType=media_type,
            Metadata={"sha256": checksum},
        )
        return StoredObject(
            bucket=bucket,
            key=key,
            checksum_sha256=checksum,
            size_bytes=len(content),
            media_type=media_type,
        )

    def read(self, *, bucket: str, key: str) -> bytes:
        response = self._client.get_object(Bucket=bucket, Key=key)
        return response["Body"].read()

    def signed_download_url(
        self,
        *,
        bucket: str,
        key: str,
        expires: timedelta,
    ) -> str:
        seconds = int(expires.total_seconds())
        if not 1 <= seconds <= MAXIMUM_EVIDENCE_URL_SECONDS:
            msg = "Evidence URLs must expire between 1 and 900 seconds"
            raise ValueError(msg)
        return str(
            self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=seconds,
            )
        )
