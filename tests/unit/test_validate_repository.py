from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from scripts import validate_repository


def test_repository_validation_allows_a_standard_remote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    git = shutil.which("git")
    assert git is not None
    for name in ("LICENSE", "NOTICE", "README.md", "SECURITY.md", "uv.lock", "pnpm-lock.yaml"):
        (tmp_path / name).write_text(f"fixture for {name}\n", encoding="utf-8")
    subprocess.run(  # noqa: S603 -- executable is resolved from the trusted PATH
        [git, "init"], cwd=tmp_path, check=True, capture_output=True
    )
    subprocess.run(  # noqa: S603 -- executable is resolved from the trusted PATH
        [git, "add", "."], cwd=tmp_path, check=True, capture_output=True
    )
    subprocess.run(  # noqa: S603 -- executable is resolved from the trusted PATH
        [git, "remote", "add", "origin", "https://example.invalid/project.git"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    monkeypatch.setattr(validate_repository, "ROOT", tmp_path)

    assert validate_repository.main() == 0
