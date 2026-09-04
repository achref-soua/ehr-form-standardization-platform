"""Validate public-boundary, licensing, compose, and generated-document invariants."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_MARKERS = (
    "compensation discussions",
    "EUR 60,000",
    "first interview",
    "private planning context",
)
GIT_REQUIRED_MESSAGE = "git is required for repository validation"


def tracked_text_files() -> list[Path]:
    git = shutil.which("git")
    if git is None:
        raise RuntimeError(GIT_REQUIRED_MESSAGE)
    result = subprocess.run(  # noqa: S603 -- executable is resolved from the trusted PATH
        [git, "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [ROOT / line for line in result.stdout.splitlines() if line]


def main() -> int:
    git = shutil.which("git")
    if git is None:
        print("ERROR: git is required for repository validation")
        return 1
    required = ("LICENSE", "NOTICE", "README.md", "SECURITY.md", "uv.lock", "pnpm-lock.yaml")
    errors = [f"missing required file: {name}" for name in required if not (ROOT / name).is_file()]
    if (ROOT / "EPICONCEPT_CASE_STUDY_AND_DEMO_MASTER_SPEC.md").exists():
        errors.append("the private master specification must stay outside this repository")
    for path in tracked_text_files():
        if (
            path == Path(__file__).resolve()
            or not path.is_file()
            or path.suffix.lower() in {".png", ".pdf", ".gif", ".woff2"}
        ):
            continue
        try:
            value = path.read_text(encoding="utf-8").casefold()
        except UnicodeDecodeError:
            continue
        errors.extend(
            f"private planning marker found in {path.relative_to(ROOT)}"
            for marker in PRIVATE_MARKERS
            if marker.casefold() in value
        )
    if errors:
        print("\n".join(f"ERROR: {error}" for error in errors))
        return 1
    print("repository boundary validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
