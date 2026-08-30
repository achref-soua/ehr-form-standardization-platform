"""Bounded in-memory ZIP inspection that never trusts archive paths or sizes."""

from __future__ import annotations

import stat
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile, ZipInfo, is_zipfile

from ehrfs.domain.errors import DomainError

DEFAULT_MAXIMUM_ENTRIES = 100
DEFAULT_MAXIMUM_ENTRY_BYTES = 50 * 1024 * 1024
DEFAULT_MAXIMUM_TOTAL_BYTES = 250 * 1024 * 1024
DEFAULT_MAXIMUM_COMPRESSION_RATIO = 100
NESTED_ARCHIVE_SUFFIXES = frozenset({".7z", ".bz2", ".gz", ".rar", ".tar", ".xz", ".zip"})


@dataclass(frozen=True, slots=True)
class ArchiveEntry:
    name: str
    content: bytes


def _safe_member_name(name: str) -> str:
    if "\\" in name or "\x00" in name:
        raise DomainError("UNSAFE_ARCHIVE_PATH", "Archive member path is ambiguous or unsafe")
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise DomainError("UNSAFE_ARCHIVE_PATH", "Archive member escapes its logical root")
    if path.suffix.casefold() in NESTED_ARCHIVE_SUFFIXES:
        raise DomainError("NESTED_ARCHIVE", "Nested archives are not accepted")
    return path.as_posix()


def _validate_member(
    member: ZipInfo,
    *,
    names: set[str],
    maximum_entry_bytes: int,
    maximum_compression_ratio: int,
) -> str:
    name = _safe_member_name(member.filename)
    if name in names:
        raise DomainError("DUPLICATE_ARCHIVE_PATH", "Archive repeats a member path")
    unix_mode = member.external_attr >> 16
    if stat.S_ISLNK(unix_mode):
        raise DomainError("ARCHIVE_LINK", "Archive links are not accepted")
    if member.flag_bits & 0x1:
        raise DomainError("ENCRYPTED_ARCHIVE", "Encrypted archives are not accepted")
    if member.file_size > maximum_entry_bytes:
        raise DomainError("ARCHIVE_ENTRY_TOO_LARGE", "Archive member exceeds its limit")
    if member.file_size and (
        member.compress_size == 0
        or member.file_size / member.compress_size > maximum_compression_ratio
    ):
        raise DomainError("ARCHIVE_COMPRESSION_RATIO", "Archive expansion ratio is unsafe")
    return name


def _read_member(archive: ZipFile, member: ZipInfo, maximum_entry_bytes: int) -> bytes:
    try:
        with archive.open(member) as stream:
            return stream.read(maximum_entry_bytes + 1)
    except (BadZipFile, OSError, RuntimeError) as error:
        raise DomainError("INVALID_ARCHIVE", "Archive member cannot be read safely") from error


def extract_safe_zip(
    content: bytes,
    *,
    maximum_entries: int = DEFAULT_MAXIMUM_ENTRIES,
    maximum_entry_bytes: int = DEFAULT_MAXIMUM_ENTRY_BYTES,
    maximum_total_bytes: int = DEFAULT_MAXIMUM_TOTAL_BYTES,
    maximum_compression_ratio: int = DEFAULT_MAXIMUM_COMPRESSION_RATIO,
) -> tuple[ArchiveEntry, ...]:
    """Validate and read a ZIP into bounded immutable entries without filesystem extraction."""
    source = BytesIO(content)
    if not is_zipfile(source):
        raise DomainError("INVALID_ARCHIVE", "Upload is not a valid ZIP archive")
    source.seek(0)
    try:
        archive = ZipFile(source)
    except (BadZipFile, OSError) as error:
        raise DomainError("INVALID_ARCHIVE", "Upload is not a readable ZIP archive") from error
    with archive:
        members = [member for member in archive.infolist() if not member.is_dir()]
        if len(members) > maximum_entries:
            raise DomainError("ARCHIVE_ENTRY_LIMIT", "Archive contains too many files")
        result: list[ArchiveEntry] = []
        names: set[str] = set()
        total = 0
        for member in members:
            name = _validate_member(
                member,
                names=names,
                maximum_entry_bytes=maximum_entry_bytes,
                maximum_compression_ratio=maximum_compression_ratio,
            )
            names.add(name)
            total += member.file_size
            if total > maximum_total_bytes:
                raise DomainError("ARCHIVE_TOO_LARGE", "Archive expansion exceeds its limit")
            extracted = _read_member(archive, member, maximum_entry_bytes)
            if len(extracted) != member.file_size or len(extracted) > maximum_entry_bytes:
                raise DomainError("ARCHIVE_SIZE_MISMATCH", "Archive member size is inconsistent")
            result.append(ArchiveEntry(name=name, content=extracted))
        return tuple(result)
