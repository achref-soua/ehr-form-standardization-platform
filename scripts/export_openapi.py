"""Export the authoritative FastAPI OpenAPI document deterministically."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ehrfs_api.app import app

OUTPUT = Path("docs/api/openapi.json")


def render() -> str:
    schema = app.openapi()
    return json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    generated = render()
    if arguments.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != generated:
            print("OpenAPI contract drift detected; run `make openapi`")
            return 1
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(generated, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
