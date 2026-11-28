"""Structured shell parsing: a command split into simple-command segments with their redirections."""

from __future__ import annotations

import shlex
from dataclasses import dataclass

_PUNCTUATION = "();<>|&`\n"
_REDIRECT_CHARS = frozenset("<>")


@dataclass(frozen=True, slots=True)
class CommandSegment:
    words: tuple[str, ...]
    output_targets: tuple[str, ...] = ()
    # The files a ``<`` redirection reads (not ``<<``/``<<<``: their word is a delimiter or a string).
    input_targets: tuple[str, ...] = ()


def _tokens(command: str) -> list[str] | None:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=_PUNCTUATION)
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        return None


def _is_operator(token: str) -> bool:
    return bool(token) and all(char in _PUNCTUATION for char in token)


def _segment(tokens: list[str]) -> CommandSegment:
    words: list[str] = []
    targets: list[str] = []
    inputs: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if _is_operator(token) and _REDIRECT_CHARS & set(token):
            target = tokens[index + 1] if index + 1 < len(tokens) else ""
            # ``>`` / ``>>`` / ``&>`` write a file; ``>&`` followed by a descriptor duplicates one;
            # ``<`` / ``<<`` read a file or a here-document delimiter.
            if ">" in token and not (token.endswith("&") and target.isdigit()):
                targets.append(target)
            elif token in {"<", "<>", "<&"} and not target.isdigit():
                inputs.append(target)
            # A descriptor number before a redirection (``2>``) is part of it, not an argument.
            if words and words[-1].isdigit():
                words.pop()
            index += 2
            continue
        words.append(token)
        index += 1
    return CommandSegment(words=tuple(words), output_targets=tuple(targets), input_targets=tuple(inputs))


def shell_command_segments(command: str | list[str]) -> list[CommandSegment] | None:
    if isinstance(command, list):
        words = tuple(str(part) for part in command)
        return [CommandSegment(words=words)] if words else []
    tokens = _tokens(str(command or ""))
    if tokens is None:
        return None
    segments: list[CommandSegment] = []
    current: list[str] = []
    for token in tokens:
        if _is_operator(token) and not (_REDIRECT_CHARS & set(token)):
            if current:
                segments.append(_segment(current))
            current = []
            continue
        current.append(token)
    if current:
        segments.append(_segment(current))
    return [segment for segment in segments if segment.words or segment.output_targets or segment.input_targets]


__all__ = ["CommandSegment", "shell_command_segments"]
