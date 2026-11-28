"""LSP wire format and language tables: framing, parsing and which server serves which file."""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any


def _lsp_error_text(error: Any) -> str:
    code = error.get("code") if isinstance(error, dict) else None
    if isinstance(code, int) and not isinstance(code, bool):
        return f"lsp_request_failed lsp_error_code={code}"
    return "lsp_request_failed"


_LSP_SERVERS: dict[str, list[str]] = {
    "python": ["pylsp"],
    "typescript": ["typescript-language-server", "--stdio"],
    "javascript": ["typescript-language-server", "--stdio"],
    "go": ["gopls"],
    "java": ["jdtls"],
    "c": ["clangd", "--background-index", "--clang-tidy", "--header-insertion=never"],
    "cpp": ["clangd", "--background-index", "--clang-tidy", "--header-insertion=never"],
    "rust": ["rust-analyzer"],
}

_EXT_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".go": "go",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".rs": "rust",
}

WhichResolver = Callable[[str], str | None]
PersistentProcessSpawner = Callable[..., Awaitable[Any]]


def _detect_language(path: str) -> str | None:
    return _EXT_TO_LANG.get(Path(path).suffix.lower())


def _lsp_uri(path: str | Path) -> str:
    return Path(path).resolve().as_uri()


def _encode_message(body: dict) -> bytes:
    payload = json.dumps(body).encode("utf-8")
    header = f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii")
    return header + payload


def _parse_messages(buf: bytes) -> tuple[list[dict], bytes]:
    """Parse as many complete LSP messages as possible from buf."""
    messages: list[dict] = []
    while True:
        header_end = buf.find(b"\r\n\r\n")
        if header_end == -1:
            break
        header = buf[:header_end].decode("ascii", errors="replace")
        match = re.search(r"Content-Length:\s*(\d+)", header, re.IGNORECASE)
        if not match:
            break
        content_length = int(match.group(1))
        body_start = header_end + 4
        if len(buf) < body_start + content_length:
            break
        body = buf[body_start : body_start + content_length]
        try:
            messages.append(json.loads(body.decode("utf-8")))
        except json.JSONDecodeError:
            pass
        buf = buf[body_start + content_length :]
    return messages, buf
