"""The strict argv form of a shell command: plain words joined by ``&&``, ``||``, ``|``, ``;`` or newlines."""

from __future__ import annotations

import posixpath
import re

from .command_tokens import (
    _SHELLS,
    _WRAPPERS,
    MAX_COMMAND_CHARS,
    MAX_SEGMENTS,
    Segment,
    _is_env_assignment,
    _is_operator,
    _tokenize,
)

_STRICT_SEPARATORS = frozenset({"&&", "||", "|"})
_STRICT_REFUSED_NAMES = _WRAPPERS | _SHELLS | frozenset({"eval", "xargs", "source", ".", "exec", "env"})


_MERGE_STDERR = re.compile(r"(?<=\s)2>&1(?=\s|$)")
# Output thrown away (``2>/dev/null``, ``>/dev/null``, ``&>/dev/null``) writes no file either (``ls tests/system
# 2>/dev/null`` and the like must not be refused as redirections).
_DISCARD_OUTPUT = re.compile(r"(?<=\s)(?:[12]?>|&>)\s*/dev/null(?=\s|$)")


def strict_argv(command: str) -> list[Segment] | None:
    """Plain argv commands only, joined by ``&&``, ``||``, ``|``, ``;`` or newlines; ``None`` for anything else.

    No redirection, background ``&``, subshell, substitution, variable (``$``), environment assignment, wrapper or
    nested shell: what runs is exactly the words. The structural form a phase that may not run free shell code
    accepts (``workflow_runs/octryx/shell_rules``)."""

    text = str(command or "")
    if not text.strip() or len(text) > MAX_COMMAND_CHARS or "$" in text or "`" in text or "\\" in text:
        return None
    # ``2>&1`` only joins stderr into stdout, it writes no file (weak models use it often).
    text = _DISCARD_OUTPUT.sub(" ", _MERGE_STDERR.sub(" ", text))
    try:
        tokens = _tokenize(text)
    except ValueError:
        return None
    segments: list[list[str]] = [[]]
    for token in tokens:
        if _is_operator(token):
            if token not in _STRICT_SEPARATORS and not set(token) <= {";", "\n"}:
                return None
            segments.append([])
            continue
        segments[-1].append(token)
    result: list[Segment] = []
    for words in segments:
        if not words:
            continue
        if _is_env_assignment(words[0]) or posixpath.basename(words[0]) in _STRICT_REFUSED_NAMES:
            return None
        result.append(tuple(words))
    return result if 0 < len(result) <= MAX_SEGMENTS else None


__all__ = ["strict_argv"]
