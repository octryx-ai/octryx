"""Code elements from files an MCP client sends explicitly (``knowledge_code_impact`` over MCP).

An external client such as Claude Code works in its own checkout, which the server cannot read. The
explicit way to ask about "this codebase" without a recorded snapshot is to send the files that
carry the elements: build files, configuration and sources. They are validated at the boundary:

- at most :data:`MAX_CLIENT_FILES` files and :data:`MAX_CLIENT_BYTES` of text in total;
- every path is repository-relative and safe (``repository_index.validate_repository_path``);
- only files the scanner reads (by file class) are accepted. Any other file is refused, never
  silently ignored, so the client learns what was not considered;
- the content is text. A NUL byte is refused.

Nothing is stored. The elements live only for the one answer.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..ledger.errors import EvidenceLedgerContractError
from .repository_paths import validate_repository_path
from .scan import CodeElement, elements_of_text, is_scanned_file

MAX_CLIENT_FILES = 200
MAX_CLIENT_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ClientFiles:
    elements: tuple[CodeElement, ...]
    file_count: int


class ClientFilesRefusedError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def client_file_elements(files: object) -> ClientFiles:
    """The elements of ``[{path, content}, ...]``, or :class:`ClientFilesRefusedError`."""
    if not isinstance(files, list) or not files:
        raise ClientFilesRefusedError("files_invalid")
    if len(files) > MAX_CLIENT_FILES:
        raise ClientFilesRefusedError("too_many_files")
    total = 0
    seen: set[str] = set()
    elements: list[CodeElement] = []
    for entry in files:
        if not isinstance(entry, dict) or type(entry.get("content")) is not str:
            raise ClientFilesRefusedError("files_invalid")
        try:
            path = validate_repository_path(entry.get("path"))
        except EvidenceLedgerContractError:
            raise ClientFilesRefusedError("path_invalid") from None
        if path in seen:
            raise ClientFilesRefusedError("duplicate_path")
        if not is_scanned_file(path):
            raise ClientFilesRefusedError("file_class_not_scanned")
        content = entry["content"]
        total += len(content.encode("utf-8"))
        if total > MAX_CLIENT_BYTES:
            raise ClientFilesRefusedError("files_too_large")
        if "\x00" in content:
            raise ClientFilesRefusedError("binary_content")
        seen.add(path)
        elements.extend(elements_of_text(path, content))
    return ClientFiles(elements=tuple(elements), file_count=len(seen))


__all__ = ["MAX_CLIENT_BYTES", "MAX_CLIENT_FILES", "ClientFiles", "ClientFilesRefusedError", "client_file_elements"]
