"""Which files of a local snapshot are items, with the closed outcomes of the source model.

A local snapshot classifies its files like the ``remote_git`` archive does (``sync/git_snapshot``),
so the same file is an item or a skip in both fetch modes.

From the manifest (path and size, before any byte is sent):

- ``path_too_long``: the path is longer than a display title may be;
- ``skipped_unsupported_path``: the path is not a plain relative POSIX path that is its own title;
- ``skipped_too_large``: the size is above :func:`max_snapshot_file_bytes`
  (``Settings.knowledge_snapshot_max_file_bytes``, default 1 MiB, at most the general 8 MiB ingestion
  limit);
- ``skipped_sensitive_path``: local snapshots only. The file holds credentials by convention
  (``.env``, private keys, keystores, ``.npmrc``, ``.pypirc``, ``.netrc``). A checkout on a laptop is
  not a public repository, so these files are never uploaded, even though they are tracked.

From the bytes (after the blob sha1 is verified):

- ``skipped_empty``: nothing but whitespace;
- ``skipped_binary``: a NUL byte, not strict UTF-8, or not text-native;
- ``skipped_secret_material``: local snapshots only. A private key block is never stored, not even
  redacted.

Everything else is ingested; its secrets are redacted line by line at ingestion (``code_ingest``).
"""

from __future__ import annotations

from .....config import get_settings
from ...ingestion.media_types import resolve_text_native_media_type
from ...ingestion.spans import normalize_display_title
from ...ledger.errors import EvidenceLedgerError
from ..sync.git_paths import supported_path
from ..sync.git_snapshot import (
    MAX_TITLE_PATH_CHARS,
    OUTCOME_PATH_TOO_LONG,
    OUTCOME_SKIPPED_BINARY,
    OUTCOME_SKIPPED_EMPTY,
    OUTCOME_SKIPPED_TOO_LARGE,
    OUTCOME_SKIPPED_UNSUPPORTED_PATH,
)


def max_snapshot_file_bytes() -> int:
    """The per-file bound of a snapshot upload, read from the current settings."""
    return int(get_settings().knowledge_snapshot_max_file_bytes)


OUTCOME_SKIPPED_SENSITIVE_PATH = "skipped_sensitive_path"
OUTCOME_SKIPPED_SECRET_MATERIAL = "skipped_secret_material"
_PRIVATE_KEY_MARKER = b"PRIVATE KEY-----"
_SENSITIVE_NAMES = frozenset(
    {".env", ".npmrc", ".pypirc", ".netrc", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "credentials"}
)
_SENSITIVE_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".kdbx")


def _titled(path: str) -> bool:
    try:
        return normalize_display_title(path) == path
    except EvidenceLedgerError:
        return False


def sensitive_path(path: str) -> bool:
    name = path.rsplit("/", 1)[-1].lower()
    return name in _SENSITIVE_NAMES or name.startswith(".env.") or name.endswith(_SENSITIVE_SUFFIXES)


def manifest_outcome(path: str, size: int) -> str | None:
    """The skip outcome of a manifest entry, or ``None`` when the file is wanted."""
    if len(path) > MAX_TITLE_PATH_CHARS:
        return OUTCOME_PATH_TOO_LONG
    if not supported_path(path) or not _titled(path):
        return OUTCOME_SKIPPED_UNSUPPORTED_PATH
    if size > max_snapshot_file_bytes():
        return OUTCOME_SKIPPED_TOO_LARGE
    if sensitive_path(path):
        return OUTCOME_SKIPPED_SENSITIVE_PATH
    return None


def content_outcome(data: bytes) -> str | None:
    """The skip outcome of verified bytes, or ``None`` for an item."""
    if not data.strip():
        return OUTCOME_SKIPPED_EMPTY
    if b"\x00" in data:
        return OUTCOME_SKIPPED_BINARY
    try:
        data.decode("utf-8")
        resolve_text_native_media_type("text/plain", data)
    except (UnicodeDecodeError, EvidenceLedgerError):
        return OUTCOME_SKIPPED_BINARY
    if _PRIVATE_KEY_MARKER in data:
        return OUTCOME_SKIPPED_SECRET_MATERIAL
    return None


__all__ = [
    "max_snapshot_file_bytes",
    "OUTCOME_SKIPPED_SECRET_MATERIAL",
    "OUTCOME_SKIPPED_SENSITIVE_PATH",
    "content_outcome",
    "manifest_outcome",
    "sensitive_path",
]
