"""The facets of one repository file as Source Sync hands it to ingestion.

``repository`` is the normalized remote URL, ``path`` the POSIX path relative to the repository
root (also the source's display title), ``language`` from the closed table in
``sources/sync/git_paths.py`` (``None`` outside it), ``commit`` the commit the file was listed at,
``blob_sha`` the git blob id of its original bytes (before redaction), and ``dirty`` whether the
bytes came from a working tree with uncommitted changes (a local snapshot).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..ledger.errors import EvidenceLedgerContractError

MAX_REPOSITORY_CHARS = 300
MAX_PATH_CHARS = 300
MAX_LANGUAGE_CHARS = 30
_SHA1 = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True, slots=True)
class CodeFileFacet:
    repository: str
    path: str
    language: str | None
    commit: str
    blob_sha: str
    dirty: bool = False

    def __post_init__(self) -> None:
        if type(self.repository) is not str or not 0 < len(self.repository) <= MAX_REPOSITORY_CHARS:
            raise EvidenceLedgerContractError()
        if type(self.path) is not str or not 0 < len(self.path) <= MAX_PATH_CHARS:
            raise EvidenceLedgerContractError()
        if self.language is not None and (type(self.language) is not str or len(self.language) > MAX_LANGUAGE_CHARS):
            raise EvidenceLedgerContractError()
        for sha in (self.commit, self.blob_sha):
            if type(sha) is not str or not _SHA1.fullmatch(sha):
                raise EvidenceLedgerContractError()
        if type(self.dirty) is not bool:
            raise EvidenceLedgerContractError()


__all__ = ["CodeFileFacet"]
