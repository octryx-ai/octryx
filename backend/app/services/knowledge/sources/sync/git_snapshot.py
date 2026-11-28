"""One repository commit as a bounded, classified file list."""

from __future__ import annotations

import hashlib
import io
import tarfile
import zlib
from dataclasses import dataclass, field

from ...ingestion.media_types import resolve_text_native_media_type
from ...ingestion.spans import normalize_display_title
from ...ledger.errors import EvidenceLedgerError
from .contract import REASON_REPOSITORY_TOO_LARGE, REASON_SOURCE_CONTRACT_VIOLATION, ConnectorError
from .git_paths import PathFilter, supported_path

OUTCOME_EXCLUDED = "excluded"
OUTCOME_SKIPPED_TOO_LARGE = "skipped_too_large"
OUTCOME_SKIPPED_EMPTY = "skipped_empty"
OUTCOME_SKIPPED_BINARY = "skipped_binary"
OUTCOME_SKIPPED_UNSUPPORTED_PATH = "skipped_unsupported_path"
OUTCOME_PATH_TOO_LONG = "path_too_long"
FILE_SKIP_OUTCOMES = (
    OUTCOME_PATH_TOO_LONG,
    OUTCOME_EXCLUDED,
    OUTCOME_SKIPPED_TOO_LARGE,
    OUTCOME_SKIPPED_EMPTY,
    OUTCOME_SKIPPED_BINARY,
    OUTCOME_SKIPPED_UNSUPPORTED_PATH,
)

MAX_ARCHIVE_ENTRIES = 50_000
MAX_DECLARED_BYTES = 1024 * 1024 * 1024
MAX_KEPT_BYTES = 256 * 1024 * 1024
MAX_TITLE_PATH_CHARS = 300


@dataclass(frozen=True, slots=True)
class SnapshotEntry:
    path: str
    skip: str | None
    data: bytes | None = field(default=None, repr=False)

    @property
    def blob_sha(self) -> str:
        data = self.data or b""
        return hashlib.sha1(b"blob %d\x00" % len(data) + data, usedforsecurity=False).hexdigest()


@dataclass(frozen=True, slots=True)
class SnapshotLimits:
    paths: PathFilter
    max_files: int
    max_file_bytes: int


def _relative(name: str, *, strip_top_level: bool) -> str | None:
    name = name.removeprefix("./")
    if not strip_top_level:
        return name
    _, _, rest = name.partition("/")
    return rest or None


def _is_binary(data: bytes) -> bool:
    if b"\x00" in data:
        return True
    try:
        data.decode("utf-8")
        resolve_text_native_media_type("text/plain", data)
    except (UnicodeDecodeError, EvidenceLedgerError):
        return True
    return False


def _classify(member: tarfile.TarFile, entry: tarfile.TarInfo, path: str, limits: SnapshotLimits) -> SnapshotEntry:
    if len(path) > MAX_TITLE_PATH_CHARS:
        return SnapshotEntry(path, OUTCOME_PATH_TOO_LONG)
    if not supported_path(path) or not _titled(path):
        return SnapshotEntry(path, OUTCOME_SKIPPED_UNSUPPORTED_PATH)
    if not limits.paths.admits(path):
        return SnapshotEntry(path, OUTCOME_EXCLUDED)
    if entry.size > limits.max_file_bytes:
        return SnapshotEntry(path, OUTCOME_SKIPPED_TOO_LARGE)
    handle = member.extractfile(entry)
    data = handle.read() if handle is not None else b""
    if not data.strip():
        return SnapshotEntry(path, OUTCOME_SKIPPED_EMPTY)
    if _is_binary(data):
        return SnapshotEntry(path, OUTCOME_SKIPPED_BINARY)
    return SnapshotEntry(path, None, data)


def _titled(path: str) -> bool:
    try:
        return normalize_display_title(path) == path
    except EvidenceLedgerError:
        return False


def read_snapshot(archive: bytes, *, limits: SnapshotLimits, strip_top_level: bool) -> tuple[SnapshotEntry, ...]:
    entries: dict[str, SnapshotEntry] = {}
    declared = kept = items = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
            for count, member in enumerate(tar, start=1):
                if count > MAX_ARCHIVE_ENTRIES:
                    raise ConnectorError(REASON_REPOSITORY_TOO_LARGE)
                if not member.isreg():
                    continue
                declared += member.size
                if declared > MAX_DECLARED_BYTES:
                    raise ConnectorError(REASON_REPOSITORY_TOO_LARGE)
                path = _relative(member.name, strip_top_level=strip_top_level)
                if path is None or path in entries:
                    raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
                entry = _classify(tar, member, path, limits)
                if entry.skip is None:
                    items += 1
                    kept += len(entry.data or b"")
                    if items > limits.max_files or kept > MAX_KEPT_BYTES:
                        raise ConnectorError(REASON_REPOSITORY_TOO_LARGE)
                entries[path] = entry
    except (tarfile.TarError, zlib.error, EOFError, OSError):
        raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION) from None
    return tuple(entries[path] for path in sorted(entries))


__all__ = [
    "FILE_SKIP_OUTCOMES",
    "OUTCOME_EXCLUDED",
    "OUTCOME_PATH_TOO_LONG",
    "OUTCOME_SKIPPED_BINARY",
    "OUTCOME_SKIPPED_EMPTY",
    "OUTCOME_SKIPPED_TOO_LARGE",
    "OUTCOME_SKIPPED_UNSUPPORTED_PATH",
    "SnapshotEntry",
    "SnapshotLimits",
    "read_snapshot",
]
