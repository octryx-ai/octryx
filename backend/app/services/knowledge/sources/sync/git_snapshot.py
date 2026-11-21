"""One repository commit as a bounded, classified file list.

The ``remote_git`` fetch mode reads the host's gzip archive at a sha (its entries under one
top-level directory, which is stripped). ``strip_top_level=False`` reads entries relative to the
repository root, as ``git archive HEAD`` writes them, so the same classification can serve a
launcher's local snapshot too.

Every regular file gets exactly one closed outcome, in this order:

1. ``path_too_long``: longer than a display title may be (the title is the path);
2. ``skipped_unsupported_path``: not a plain relative POSIX path (``git_paths.supported_path``);
3. ``excluded``: outside the include globs or inside an exclude glob;
4. ``skipped_too_large``: above ``max_file_bytes``, judged by the tar header, never read;
5. ``skipped_empty``: nothing but whitespace;
6. ``skipped_binary``: a NUL byte, not strict UTF-8, or a known binary signature;
7. otherwise the file is an item. Its identity is the git blob sha1 of its bytes, so a re-sync of
   the same commit, or of a later commit where the file did not change, is ``unchanged``. Secret
   redaction happens at ingestion (``ingestion/code_ingest.py``), the same for every fetch mode.

Directories, symlinks and other non-regular entries are no files and get no outcome. Bounds are
explicit refusals (``repository_too_large``): the archive's entry count, the bytes its headers
declare, the bytes kept in memory, and ``max_files`` items after the globs. A corrupt archive is
``source_contract_violation``.
"""

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
    """One regular file: ``skip`` is its skip outcome, or ``None`` for an item with its text."""

    path: str
    skip: str | None
    data: bytes | None = field(default=None, repr=False)

    @property
    def blob_sha(self) -> str:
        """The git blob id of the bytes (``sha1("blob <size>\\0" + bytes)``), as ``git hash-object`` prints it."""
        data = self.data or b""
        return hashlib.sha1(b"blob %d\x00" % len(data) + data, usedforsecurity=False).hexdigest()


@dataclass(frozen=True, slots=True)
class SnapshotLimits:
    paths: PathFilter
    max_files: int
    max_file_bytes: int


def _relative(name: str, *, strip_top_level: bool) -> str | None:
    """The entry's repository path; ``None`` for the top-level directory entry itself."""
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
    """The path is its own display title, unchanged by the title rule (whitespace, unsafe characters)."""
    try:
        return normalize_display_title(path) == path
    except EvidenceLedgerError:
        return False


def read_snapshot(archive: bytes, *, limits: SnapshotLimits, strip_top_level: bool) -> tuple[SnapshotEntry, ...]:
    """Every regular file of a gzip tarball with its outcome, sorted by path; bounded."""
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
