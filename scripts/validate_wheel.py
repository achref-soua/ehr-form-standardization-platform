"""Verify that built wheels carry the checksummed OMOP schema assets."""

from __future__ import annotations

import hashlib
from pathlib import Path
from zipfile import ZipFile

from ehrfs.omop.schema import ASSET_SHA256


def main() -> None:
    wheels = tuple(sorted(Path("dist").glob("*.whl")))
    if len(wheels) != 1:
        print(f"expected exactly one wheel under dist, found {len(wheels)}")
        raise SystemExit(2)

    wheel = wheels[0]
    with ZipFile(wheel) as archive:
        for asset, expected_checksum in ASSET_SHA256.items():
            member = f"ehrfs/omop/assets/{asset}"
            try:
                payload = archive.read(member)
            except KeyError as error:
                print(f"wheel is missing {member}")
                raise SystemExit(2) from error
            checksum = hashlib.sha256(payload).hexdigest()
            if checksum != expected_checksum:
                print(f"wheel asset checksum mismatch: {member}")
                raise SystemExit(2)

    print(f"wheel assets validated: {wheel} ({len(ASSET_SHA256)} OMOP files)")


if __name__ == "__main__":
    main()
