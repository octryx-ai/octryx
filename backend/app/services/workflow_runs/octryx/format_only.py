"""A formatting-only edit of a protected test is allowed.

Example: a fix phase's pipeline was red only on style: `ruff format --check` wanted tests/test_pricing.py, the
reproduction test the agent had written and submitted, reformatted. The phase may not change that confirmed test, so
the agent's Edit that joined a three-line call into one line was refused three times and the run paused at its loop
limit, with no way out. An Edit whose old and new text are the same program text, apart from layout, changes no test:
the same tokens after dropping line breaks inside brackets, indentation width, trailing commas before a closing
bracket and the spelling of string literals (quotes). Which comparison a file gets is stack data (stacks.json
``formatting``: ``python`` for Python's own tokenizer, ``tokens`` for a generic one); anything else stays protected.

:func:`program_fingerprint` is that comparison as one value, and it is the only one: the edit guard compares the old
and new text's fingerprints, and the confirmed tests' intact check compares the file's fingerprint at its confirmation
with its latest one (comparing bytes instead would fail a green gate after a layout-only Edit the guard let
through).
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from hashlib import sha256
from typing import Any

_CLOSERS = {")", "]", "}"}
_GENERIC = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`|//[^\n]*|/\*.*?\*/|[A-Za-z_$][\w$]*|'
                      r"\d[\w.]*|\S", re.DOTALL)


def _python(text: str) -> list[tuple[str, str]] | None:
    tokens: list[tuple[str, str]] = []
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            kind = tokenize.tok_name[token.type]
            if kind in ("NL", "ENDMARKER", "INDENT", "DEDENT"):
                continue  # layout; a fragment's indentation width may change, its statements may not
            value = token.string
            if kind == "STRING":
                try:
                    value = repr(ast.literal_eval(value))
                except (ValueError, SyntaxError):
                    pass
            elif kind == "COMMENT":
                value = value.lstrip("#").strip()
            tokens.append((kind, value))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return None
    return _without_trailing_commas(tokens)


def _generic(text: str) -> list[tuple[str, str]]:
    tokens = []
    for value in _GENERIC.findall(text):
        if value[:1] in "\"'":
            try:
                value = repr(ast.literal_eval(value))
            except (ValueError, SyntaxError):
                pass
        elif value.startswith(("//", "/*")):
            value = " ".join(value.strip("/*").split())
        tokens.append(("OP" if len(value) == 1 and not value.isalnum() else "TOKEN", value))
    return _without_trailing_commas(tokens)


def _without_trailing_commas(tokens: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return [token for index, token in enumerate(tokens)
            if not (token[1] == "," and index + 1 < len(tokens) and tokens[index + 1][1] in _CLOSERS)]


def comparison(path: str) -> str:
    """The stack's comparison for ``path`` (stacks.json ``formatting.compare`` by its code suffixes), else ``""``."""
    from ...engineering_knowledge.stacks import built_in

    suffix = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    for stack in dict(built_in().get("stacks") or {}).values():
        compare = str(dict(stack.get("formatting") or {}).get("compare") or "")
        if compare and suffix in {str(item).lstrip(".").lower() for item in stack.get("code_suffixes") or []}:
            return compare
    return ""


def program_fingerprint(text: str, path: str) -> str | None:
    """``text`` without its layout as one value, by the stack's comparison of ``path``; ``None`` when ``path`` has no
    comparison or does not tokenize (then only identical bytes are the same program)."""
    compare = comparison(path)
    tokens = _python(text) if compare == "python" else _generic(text) if compare == "tokens" else None
    if tokens is None:
        return None
    return f"program-sha256:{compare}:" + sha256(repr(tokens).encode("utf-8")).hexdigest()


def same_program(old: str, new: str, path: str) -> bool:
    """Whether ``new`` is ``old`` with only its layout changed, by the stack's comparison of ``path``."""
    before = program_fingerprint(old, path)
    return before is not None and before == program_fingerprint(new, path)


def formatting_only(tool_input: dict[str, Any], path: str) -> bool:
    """An Edit (or each edit of a MultiEdit) that changes only the layout of ``path``."""
    edits = tool_input.get("edits") if isinstance(tool_input.get("edits"), list) else [tool_input]
    pairs = [(item.get("old_string"), item.get("new_string")) for item in edits if isinstance(item, dict)]
    return bool(pairs) and all(isinstance(old, str) and old.strip() and isinstance(new, str)
                               and same_program(old, new, path) for old, new in pairs)


__all__ = ["comparison", "formatting_only", "program_fingerprint", "same_program"]
