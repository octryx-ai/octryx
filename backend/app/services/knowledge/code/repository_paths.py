"""Validation of the values the repository code index stores: paths, commit and blob ids, languages."""

from __future__ import annotations

import hashlib
import re

from ..ledger.errors import EvidenceLedgerContractError

MAX_PATH_CHARS = 1024
MAX_ELEMENTS_PER_FILE = 2000
MAX_LANGUAGE_CHARS = 40
_SHA1 = re.compile(r"^[0-9a-f]{40}$")
_LANGUAGE = re.compile(r"^[a-z0-9][a-z0-9+#._-]{0,39}$")


def path_digest(path: str) -> str:
    return hashlib.sha256(path.encode("utf-8")).hexdigest()


def validate_repository_path(path: object) -> str:
    if type(path) is not str or not path or len(path) > MAX_PATH_CHARS:
        raise EvidenceLedgerContractError()
    if path.startswith("/") or "\\" in path or any(ord(ch) < 32 or ord(ch) == 127 for ch in path):
        raise EvidenceLedgerContractError()
    if any(part in {"", ".", ".."} for part in path.split("/")):
        raise EvidenceLedgerContractError()
    return path


def _sha1(value: object) -> str:
    if type(value) is not str or not _SHA1.fullmatch(value):
        raise EvidenceLedgerContractError()
    return value


def _language(value: object) -> str | None:
    if value is None:
        return None
    if type(value) is not str or not _LANGUAGE.fullmatch(value):
        raise EvidenceLedgerContractError()
    return value
