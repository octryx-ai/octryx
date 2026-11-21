"""A confirmed test file may be reformatted, never changed.

Example: CI failed on ``flake8`` E501 in the new test helper of the confirmed test file; implement protects the
confirmed tests (``path_rules.protect_confirmed_tests``) and refused the fix, so the CI-red loop had no legal move.

A write to a confirmed test file passes the phase's path rule only when it provably preserves the file's semantics:
both versions are Python and parse, and their syntax trees are identical ignoring positions
(``ast.dump(..., include_attributes=False)``). Line breaks, indentation of continuation lines, quotes of equal strings
and comments may change; any other change — an assertion, a name, a literal, a docstring — stays refused. A file
that is not Python, or does not parse before or after, is never "formatting only".

The confirmed tests' content snapshot (``test_runs``) keeps the confirmed syntax tree's fingerprint next to the byte
hash, so a reformatted file still counts as intact — and nothing else does.
"""

from __future__ import annotations

import ast
from hashlib import sha256
from pathlib import Path


def ast_fingerprint(text: str) -> str | None:
    """The fingerprint of a Python source's syntax tree without positions, or ``None`` when it does not parse."""
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
    """True when writing ``new_text`` to the existing Python file ``path`` keeps its syntax tree identical."""
    if new_text is None or not path.is_file():
        return False
    before = file_ast_fingerprint(path)
    return before is not None and ast_fingerprint(new_text) == before


__all__ = ["ast_fingerprint", "file_ast_fingerprint", "formatting_only"]
