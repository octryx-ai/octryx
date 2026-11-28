"""A confirmed test file may be reformatted, never changed."""

from __future__ import annotations

import ast
from hashlib import sha256
from pathlib import Path


def ast_fingerprint(text: str) -> str | None:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return None
    return "ast-sha256:" + sha256(ast.dump(tree, include_attributes=False).encode("utf-8")).hexdigest()


def file_ast_fingerprint(path: Path) -> str | None:
    if path.suffix != ".py":
        return None
    try:
        return ast_fingerprint(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None


def formatting_only(path: Path, new_text: str | None) -> bool:
    if new_text is None or not path.is_file():
        return False
    before = file_ast_fingerprint(path)
    return before is not None and ast_fingerprint(new_text) == before


__all__ = ["ast_fingerprint", "file_ast_fingerprint", "formatting_only"]
