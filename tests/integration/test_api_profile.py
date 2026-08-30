"""HTTP contract tests against an isolated PostgreSQL 18 control plane."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from testcontainers.community.postgres import PostgresContainer

from ehrfs.config import Settings
from ehrfs.domain.errors import DomainError
from ehrfs.domain.identity import sha256_hex
from ehrfs.storage.objects import StoredObject
from ehrfs_api.app import create_app

POSTGRES_IMAGE = (
    "postgres:18-bookworm@sha256:1c59e2c3c818eaa0f0628f695b36e7c9e362d6b219b36a54a32df645cbd7e1af"
)
OUTAGE_MESSAGE = "synthetic object-store outage"


class MemoryObjectStore:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.fail_writes = False

    def ready(self, *, bucket: str) -> bool:
        return bool(bucket)

    def put_immutable(
        self,
        *,
        bucket: str,
        namespace: str,
        content: bytes,
        media_type: str,
    ) -> StoredObject:
        if self.fail_writes:
            raise OSError(OUTAGE_MESSAGE)
        checksum = sha256_hex(content)
        key = f"{namespace}/{checksum[:2]}/{checksum}"
        self.objects[(bucket, key)] = content
        return StoredObject(bucket, key, checksum, len(content), media_type)

    def read(self, *, bucket: str, key: str) -> bytes:
        return self.objects[(bucket, key)]

    def signed_download_url(
        self,
        *,
        bucket: str,
        key: str,
        expires: timedelta,
    ) -> str:
        return f"https://evidence.invalid/{bucket}/{key}?ttl={int(expires.total_seconds())}"


@pytest.fixture(scope="module")
def api_client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[TestClient, FastAPI]]:
    key_directory = tmp_path_factory.mktemp("keys")
    with PostgresContainer(image=POSTGRES_IMAGE, driver="psycopg") as postgres:
        settings = Settings(
            environment="test",
            database_url=postgres.get_connection_url(),
            database_sslmode="disable",
            signing_private_key_path=key_directory / "missing-private-key",
            signing_public_key_path=key_directory / "missing-public-key",
            session_secret="test-session-secret-with-at-least-32-bytes",
            csrf_secret="test-csrf-secret-with-at-least-32-bytes",  # gitleaks:allow
            pseudonymization_key="test-site-key-with-at-least-32-bytes",
        )
        application = create_app(settings)
        application.state.object_store = MemoryObjectStore()

        @application.get("/test/domain-error")
        def domain_error() -> None:
            raise DomainError("TEST_FAILURE", "Synthetic domain failure", 409)

        with TestClient(application) as client:
            yield client, application


def _open_session(client: TestClient, persona: str) -> str:
    response = client.post("/api/v1/session", json={"persona": persona})
    assert response.status_code == 200
    return str(response.json()["csrf_token"])


def _post_headers(csrf: str, *, idempotency_key: str = "api-contract-default") -> dict[str, str]:
    return {
        "X-CSRF-Token": csrf,
        "X-Correlation-ID": "api-contract-test",
        "Idempotency-Key": idempotency_key,
    }


@pytest.mark.integration
def test_health_error_shapes_and_session_boundaries(
    api_client: tuple[TestClient, FastAPI],
) -> None:
    client, application = api_client
    health = client.get("/api/v1/health")
    assert health.status_code == 200
    assert health.json()["components"]["worker"] == "not observed"
    assert health.headers["x-content-type-options"] == "nosniff"
    assert client.get("/api/v1/metrics").status_code == 200
    assert client.get("/api/v1/health/live").json()["status"] == "alive"
    assert client.get("/api/v1/health/ready").json()["status"] == "ready"
    assert len(client.get("/api/v1/session/personas").json()) == 4

    unauthenticated = client.get("/api/v1/sources")
    assert unauthenticated.status_code == 401
    assert unauthenticated.headers["content-type"].startswith("application/problem+json")
    assert unauthenticated.json()["code"] == "HTTP_401"

    invalid_body = client.post("/api/v1/session", json={"persona": "invalid"})
    assert invalid_body.status_code == 422
    assert invalid_body.json()["code"] == "VALIDATION_ERROR"
    domain_failure = client.get("/test/domain-error")
    assert domain_failure.status_code == 409
    assert domain_failure.json()["code"] == "TEST_FAILURE"

    original = application.state.settings
    application.state.settings = original.model_copy(
        update={
            "demo_mode": False,
            "session_secret": "non-placeholder-session-secret-value",
            "csrf_secret": "non-placeholder-csrf-secret-value",
            "pseudonymization_key": "non-placeholder-site-secret-value",
            "s3_secret_key": "non-placeholder-object-secret-value",
        }
    )
    try:
        disabled = client.post("/api/v1/session", json={"persona": "engineer"})
        assert disabled.status_code == 404
    finally:
        application.state.settings = original


@pytest.mark.integration
def test_read_contracts_rbac_and_pagination(api_client: tuple[TestClient, FastAPI]) -> None:
    client, _application = api_client
    _open_session(client, "researcher")
    assert client.get("/api/v1/session/me").json()["role"] == "researcher"

    first_page = client.get("/api/v1/establishments", params={"limit": 2})
    assert first_page.status_code == 200
    assert first_page.json()["total"] == 4
    second_page = client.get(
        "/api/v1/establishments", params={"cursor": first_page.json()["next_cursor"], "limit": 2}
    )
    assert len(second_page.json()["data"]) == 2
    assert client.get("/api/v1/establishments", params={"cursor": "LTE"}).status_code == 422
    assert client.get("/api/v1/establishments", params={"cursor": "!!!"}).status_code == 422
    assert client.get("/api/v1/establishments", params={"limit": 0}).status_code == 422

    simple_resources = (
        "/api/v1/sources",
        "/api/v1/batches",
        "/api/v1/forms",
        "/api/v1/form-versions",
        "/api/v1/fingerprints",
        "/api/v1/mappings",
        "/api/v1/mapping-releases",
        "/api/v1/pipeline-runs",
        "/api/v1/quarantine",
        "/api/v1/documents",
        "/api/v1/omop/releases",
        "/api/v1/omop/events",
        "/api/v1/catalog/concepts",
        "/api/v1/catalog/coverage",
        "/api/v1/catalog/releases/compare",
        "/api/v1/lineage",
    )
    for resource in simple_resources:
        response = client.get(resource)
        assert response.status_code == 200, resource
        assert response.json()

    versions = client.get("/api/v1/form-versions").json()
    assert client.get(f"/api/v1/form-versions/{versions[0]['id']}").status_code == 200
    missing_uuid = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"/api/v1/form-versions/{missing_uuid}").status_code == 404
    assert client.get("/api/v1/catalog/concepts", params={"query": "not-found"}).json() == []
    assert client.get("/api/v1/catalog/coverage", params={"concept_key": "missing"}).json() == []
    assert client.get("/api/v1/lineage", params={"root": "missing"}).status_code == 404
    assert client.get("/api/v1/audit").status_code == 403


@pytest.mark.integration
def test_mutation_security_mapping_artifact_and_replay(
    api_client: tuple[TestClient, FastAPI],
) -> None:
    client, application = api_client
    engineer_csrf = _open_session(client, "engineer")
    draft_id = client.get("/api/v1/mappings").json()[0]["id"]
    assert (
        client.post(
            f"/api/v1/mappings/{draft_id}/approve",
            json={"comment": "Valid checker comment"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/mappings/{draft_id}/approve",
            headers=_post_headers(engineer_csrf),
            json={"comment": "Author must not approve"},
        ).status_code
        == 403
    )

    steward_csrf = _open_session(client, "steward")
    store = application.state.object_store
    assert isinstance(store, MemoryObjectStore)
    store.fail_writes = True
    unavailable = client.post(
        f"/api/v1/mappings/{draft_id}/approve",
        headers=_post_headers(steward_csrf),
        json={"comment": "Object store must be durable before publication"},
    )
    assert unavailable.status_code == 503
    store.fail_writes = False
    approved = client.post(
        f"/api/v1/mappings/{draft_id}/approve",
        headers=_post_headers(steward_csrf),
        json={"comment": "Reviewed value set and UNKNOWN preservation"},
    )
    assert approved.status_code == 200
    release_id = approved.json()["release_id"]
    assert client.get(f"/api/v1/mapping-releases/{release_id}/verify").json()["verified"]
    assert client.get("/api/v1/mapping-releases/mapping_2026_08_v3/verify").json()["verified"]
    assert client.get("/api/v1/mapping-releases/does-not-exist/verify").status_code == 404
    duplicate = client.post(
        f"/api/v1/mappings/{draft_id}/approve",
        headers=_post_headers(steward_csrf),
        json={"comment": "Reviewed value set and UNKNOWN preservation"},
    )
    assert duplicate.status_code == 200
    assert duplicate.json() == approved.json()
    assert (
        client.post(
            f"/api/v1/mappings/{draft_id}/approve",
            headers=_post_headers(steward_csrf),
            json={"comment": "A different request under the same key"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/v1/mappings/{draft_id}/approve",
            headers=_post_headers(steward_csrf, idempotency_key="api-contract-different"),
            json={"comment": "Cannot publish twice"},
        ).status_code
        == 409
    )

    access = client.post(
        "/api/v1/evidence/access-url",
        headers=_post_headers(steward_csrf),
        json={
            "bucket": application.state.settings.s3_mapping_bucket,
            "key": next(iter(store.objects))[1],
            "expires_seconds": 120,
        },
    )
    assert access.status_code == 200
    assert "ttl=120" in access.json()["url"]
    assert (
        client.post(
            "/api/v1/evidence/access-url",
            headers=_post_headers(steward_csrf),
            json={"bucket": "private", "key": "x", "expires_seconds": 60},
        ).status_code
        == 422
    )

    operator_csrf = _open_session(client, "operator")
    exported = client.post(
        "/api/v1/site-summaries/export",
        headers=_post_headers(operator_csrf),
        params={"establishment_id": "site-a"},
    )
    assert exported.status_code == 200
    serialized_bundle = json.dumps(exported.json()).lower()
    assert "patient" not in serialized_bundle and "answer" not in serialized_bundle
    imported = client.post(
        "/api/v1/site-summaries/import",
        headers=_post_headers(operator_csrf),
        json=exported.json(),
    )
    assert imported.status_code == 200 and imported.json()["accepted"]
    tampered = exported.json()
    tampered["bundle"]["metrics"][0]["recorded_count"] += 1
    assert (
        client.post(
            "/api/v1/site-summaries/import",
            headers=_post_headers(operator_csrf),
            json=tampered,
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/site-summaries/export",
            headers=_post_headers(operator_csrf),
            params={"establishment_id": "missing"},
        ).status_code
        == 404
    )
    quarantine_id = client.get("/api/v1/quarantine").json()[0]["id"]
    missing_mapping = client.post(
        "/api/v1/replays",
        headers=_post_headers(operator_csrf),
        json={"quarantine_id": quarantine_id, "mapping_release_id": "missing"},
    )
    assert missing_mapping.status_code == 422
    replay = client.post(
        "/api/v1/replays",
        headers=_post_headers(operator_csrf),
        json={"quarantine_id": quarantine_id, "mapping_release_id": release_id},
    )
    assert replay.status_code == 200
    assert replay.json()["status"] == "QUEUED"
    missing_quarantine = client.post(
        "/api/v1/replays",
        headers=_post_headers(operator_csrf),
        json={
            "quarantine_id": "00000000-0000-0000-0000-000000000000",
            "mapping_release_id": release_id,
        },
    )
    assert missing_quarantine.status_code == 404


@pytest.mark.integration
def test_pipeline_and_document_mutations(api_client: tuple[TestClient, FastAPI]) -> None:
    client, _application = api_client
    engineer_csrf = _open_session(client, "engineer")
    headers = _post_headers(engineer_csrf, idempotency_key="api-contract-run-001")
    payload = {"batch_id": "contract-batch", "form_version": "3"}
    first = client.post("/api/v1/pipeline-runs", headers=headers, json=payload)
    second = client.post("/api/v1/pipeline-runs", headers=headers, json=payload)
    assert first.status_code == second.status_code == 200
    assert first.json()["job_id"] == second.json()["job_id"]
    assert (
        client.post(
            "/api/v1/pipeline-runs",
            headers=_post_headers(engineer_csrf, idempotency_key="short"),
            json=payload,
        ).status_code
        == 422
    )

    accepted = client.post(
        "/api/v1/documents",
        headers={**_post_headers(engineer_csrf), "X-Synthetic-Fixture": "true"},
        files={"upload": ("../safe scan.png", b"\x89PNG\r\n\x1a\nsynthetic", "image/png")},
    )
    assert accepted.status_code == 200
    assert accepted.json()["filename"] == "safe-scan.png"
    rejected = client.post(
        "/api/v1/documents",
        headers=_post_headers(engineer_csrf),
        files={"upload": ("scan.exe", b"synthetic", "application/octet-stream")},
    )
    assert rejected.status_code == 415
    assert client.post("/api/v1/ocr", headers=_post_headers(engineer_csrf)).status_code == 200

    researcher_csrf = _open_session(client, "researcher")
    assert (
        client.post(
            "/api/v1/documents",
            headers=_post_headers(researcher_csrf),
            files={"upload": ("scan.png", b"\x89PNG\r\n\x1a\nsynthetic", "image/png")},
        ).status_code
        == 403
    )
    steward_csrf = _open_session(client, "steward")
    audit = client.get("/api/v1/audit", headers=_post_headers(steward_csrf))
    assert audit.status_code == 200
    assert any(row["correlation_id"] == "api-contract-test" for row in audit.json())


def test_memory_object_store_contract() -> None:
    store = MemoryObjectStore()
    stored = store.put_immutable(
        bucket="test", namespace="raw", content=b"value", media_type="text/plain"
    )
    assert store.read(bucket="test", key=stored.key) == b"value"
    assert store.signed_download_url(
        bucket="test", key=stored.key, expires=timedelta(seconds=30)
    ).endswith("ttl=30")
