from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session
from testcontainers.community.postgres import PostgresContainer
from typer.testing import CliRunner

from ehrfs.cli.app import DEMO_MODE_REQUIRED_MESSAGE, KEYS_EXIST_MESSAGE, app
from ehrfs.config import Settings, get_settings
from ehrfs.demo import reset_demo
from ehrfs.storage.database import create_engine, create_schema

POSTGRES_IMAGE = (
    "postgres:18-bookworm@sha256:1c59e2c3c818eaa0f0628f695b36e7c9e362d6b219b36a54a32df645cbd7e1af"
)


@pytest.fixture(scope="module", autouse=True)
def cli_database() -> Iterator[None]:
    with (
        PostgresContainer(image=POSTGRES_IMAGE, driver="psycopg") as postgres,
        pytest.MonkeyPatch.context() as monkeypatch,
    ):
        monkeypatch.setenv("EHRFS_DATABASE_URL", postgres.get_connection_url())
        monkeypatch.setenv("EHRFS_DATABASE_SSLMODE", "disable")
        get_settings.cache_clear()
        yield
        get_settings.cache_clear()


def _invoke(*arguments: str) -> tuple[int, str]:
    result = CliRunner().invoke(app, list(arguments))
    return result.exit_code, result.output


def test_informational_and_deterministic_data_commands(tmp_path: Path) -> None:
    exit_code, output = _invoke("version")
    assert exit_code == 0
    assert output.strip() == "0.1.0"

    exit_code, output = _invoke("preflight", "--json")
    assert exit_code == 0
    assert json.loads(output)["python"]
    exit_code, output = _invoke("preflight")
    assert exit_code == 0
    assert '"disk_free_bytes"' in output

    output_path = tmp_path / "patients.ndjson"
    exit_code, output = _invoke(
        "data",
        "generate",
        "--patients",
        "3",
        "--seed",
        "7",
        "--output",
        str(output_path),
    )
    assert exit_code == 0
    assert "Generated 3" in output
    assert output_path.read_text(encoding="utf-8").count("\n") == 3
    manifest = json.loads(output_path.with_suffix(".manifest.json").read_text(encoding="utf-8"))
    assert manifest["contains_real_patient_data"] is False
    assert len(manifest["checksum_sha256"]) == 64

    exit_code, output = _invoke("data", "fetch")
    assert exit_code == 0
    assert "never downloaded implicitly" in output
    exit_code, output = _invoke("forms", "fingerprint", "--version", "4", "--json")
    assert exit_code == 0
    assert len(json.loads(output)["compatibility"]) == 64
    exit_code, output = _invoke("benchmark", "--events", "10", "--json")
    assert exit_code == 0
    assert json.loads(output)["events"] == 10


def test_key_generation_refuses_accidental_replacement(tmp_path: Path) -> None:
    destination = tmp_path / "keys"
    exit_code, output = _invoke("keys", "generate", "--destination", str(destination))
    assert exit_code == 0
    assert "Generated signing key" in output
    assert (destination / "ehrfs_signing_key").stat().st_mode & 0o777 == 0o600
    exit_code, output = _invoke("keys", "generate", "--destination", str(destination))
    assert exit_code != 0
    assert KEYS_EXIST_MESSAGE in output
    exit_code, output = _invoke("keys", "generate", "--destination", str(destination), "--force")
    assert exit_code == 0
    assert (destination / "ehrfs_signing_key.pub").exists()


def test_demo_reset_is_disabled_outside_demo_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ehrfs.cli.app.get_settings", lambda: SimpleNamespace(demo_mode=False))

    exit_code, output = _invoke("demo", "reset")

    assert exit_code == 2
    assert DEMO_MODE_REQUIRED_MESSAGE in output


@pytest.mark.integration
def test_database_backed_cli_workflow() -> None:
    exit_code, output = _invoke("demo", "reset")
    assert exit_code == 0
    assert "reset" in output
    exit_code, output = _invoke("source", "inventory", "--json")
    assert exit_code == 0
    assert json.loads(output) == {"forms": 3, "pipeline_runs": 2, "quarantined": 1}
    exit_code, output = _invoke("mappings", "validate", "--json")
    assert exit_code == 0
    assert json.loads(output)[0]["author_and_approver_differ"]
    exit_code, output = _invoke("mappings", "release")
    assert exit_code == 0
    assert "never commits to Git" in output

    exit_code, output = _invoke(
        "pipeline", "run", "--batch-id", "cli-batch", "--form-version", "3", "--json"
    )
    assert exit_code == 0
    assert json.loads(output)["status"] == "QUEUED"
    exit_code, output = _invoke(
        "pipeline",
        "replay",
        "--quarantine-id",
        "00000000-0000-0000-0000-000000000001",
        "--mapping-release-id",
        "mapping_2026_08_v3",
    )
    assert exit_code == 0
    assert len(output.strip()) == 36
    exit_code, output = _invoke("quarantine", "list", "--json")
    assert exit_code == 0
    assert json.loads(output)[0]["reason"] == "UNKNOWN_FORM_VERSION"
    exit_code, output = _invoke("omop", "validate", "--json")
    assert exit_code == 0
    assert json.loads(output)["passed"]
    exit_code, output = _invoke("catalog", "rebuild")
    assert exit_code == 0
    assert "1 concepts, 4 site-period metrics" in output
    exit_code, output = _invoke("demo", "run")
    assert exit_code == 0
    assert "v4 is quarantined" in output


@pytest.mark.integration
def test_omop_cli_returns_stable_failure_exit_code() -> None:
    settings = Settings()
    engine = create_engine(settings)
    create_schema(engine)
    with Session(engine) as session:
        reset_demo(session)
        session.commit()
    exit_code, output = _invoke("omop", "validate", "--json")
    assert exit_code == 1
    assert json.loads(output)["passed"] is False
    _invoke("demo", "reset")
    engine.dispose()
