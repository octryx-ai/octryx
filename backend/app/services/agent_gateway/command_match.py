"""Structural shell command matching for the agent gateway tool policy.

A Bash command is not matched as text. It is tokenized like a POSIX shell would
(``shlex`` with shell punctuation), split into simple-command segments on the
control operators (``&&``, ``||``, ``;``, ``|``, ``&``, newlines, subshell
parentheses, backticks), and each segment is normalized:

- leading ``NAME=value`` environment assignments are dropped;
- a small fixed set of transparent wrappers (``env``, ``sudo``, ``command``,
  ``exec``, ``nohup``, ``time``) is dropped when it directly precedes the command;
- redirection operators and their targets are dropped.

The first token of a segment is compared by basename (``/x/.venv/bin/python``
matches ``python``), every further prefix token exactly. Nested commands are
parsed as segments too: the string after ``sh -c`` / ``bash -c`` / ``zsh -c``,
``eval`` arguments and ``$(...)`` / backtick command substitutions inside words.

A command that cannot be tokenized (unbalanced quotes) is ``None``: callers decide
explicitly what an unparseable command means. Heredoc bodies are data; when a
command only fails to tokenize because of a heredoc body, the bodies are removed
and tokenization is retried.

This is a guardrail against mistakes, not a sandbox: a determined shell program
(variables, ``xargs``, aliases, scripts) can always express a command indirectly.
"""

from __future__ import annotations

import posixpath
from collections.abc import Sequence

from .command_tokens import (
    _REDIRECT_CHARS,
    _SEPARATOR_CHARS,
    _SHELLS,
    _WRAPPERS,
    MAX_COMMAND_CHARS,
    MAX_NESTING,
    MAX_SEGMENTS,
    Segment,
    _is_env_assignment,
    _is_operator,
    _strip_heredoc_bodies,
    _tokenize,
    without_data_heredocs,
)


def _normalize(words: list[str]) -> Segment:
    index = 0
    while index < len(words):
        if _is_env_assignment(words[index]):
            index += 1
        elif words[index] in _WRAPPERS:
            index += 1
        else:
            break
    return tuple(words[index:])


def _split(tokens: list[str]) -> list[list[str]]:
    segments: list[list[str]] = [[]]
    skip_target = False
    for token in tokens:
        if _is_operator(token):
            if any(char in _SEPARATOR_CHARS for char in token) or not any(char in _REDIRECT_CHARS for char in token):
                segments.append([])
                skip_target = False
            else:
                skip_target = True
            continue
        if skip_target:
            skip_target = False
            continue
        segments[-1].append(token)
    return [segment for segment in segments if segment]


def _substitutions(word: str) -> list[str]:
    """Inner command texts of ``$(...)`` and backtick substitutions inside one word."""

    inner: list[str] = []
    start = word.find("$(")
    if start >= 0:
        end = word.rfind(")")
        if end > start:
            inner.append(word[start + 2 : end])
    parts = word.split("`")
    inner.extend(parts[1:-1:2])
    return inner


def _nested(segment: Segment) -> list[str]:
    nested: list[str] = []
    if not segment:
        return nested
    name = posixpath.basename(segment[0])
    if name in _SHELLS and "-c" in segment[1:]:
        position = segment.index("-c", 1)
        if position + 1 < len(segment):
            nested.append(segment[position + 1])
    elif name == "eval" and len(segment) > 1:
        nested.append(" ".join(segment[1:]))
    for word in segment[1:]:
        if "$(" in word or "`" in word:
            nested.extend(_substitutions(word))
    return nested


def _parse(command: str, depth: int) -> list[Segment] | None:
    text = without_data_heredocs(command.replace("\\\n", " "))
    try:
        tokens = _tokenize(text)
    except ValueError:
        try:
            tokens = _tokenize(_strip_heredoc_bodies(text))
        except ValueError:
            return None
    segments = [segment for segment in (_normalize(words) for words in _split(tokens)) if segment]
    result: list[Segment] = list(segments)
    if depth < MAX_NESTING:
        for segment in segments:
            for inner in _nested(segment):
                parsed = _parse(inner, depth + 1)
                if parsed is None:
                    return None
                result.extend(parsed)
    return result


def _parse_raw(command: str, depth: int) -> list[Segment] | None:
    text = without_data_heredocs(command.replace("\\\n", " "))
    try:
        tokens = _tokenize(text)
    except ValueError:
        try:
            tokens = _tokenize(_strip_heredoc_bodies(text))
        except ValueError:
            return None
    segments = [tuple(words) for words in _split(tokens) if words]
    result: list[Segment] = list(segments)
    if depth < MAX_NESTING:
        for segment in segments:
            # The nested commands of the normalized form; a wrapper or assignment before them stays visible.
            for inner in _nested(_normalize(list(segment))):
                parsed = _parse_raw(inner, depth + 1)
                if parsed is None:
                    return None
                result.extend(parsed)
    return result


def raw_command_segments(command: str) -> list[Segment] | None:
    """The simple-command segments as written: environment assignments and wrappers NOT dropped.

    A read-only decision asks these before :func:`command_segments` normalizes them away
    (``HOME=/x kubectl …``, ``env PATH=/x kubectl …``, ``timeout 5 kubectl …``).
    """
    text = str(command or "")
    if len(without_data_heredocs(text)) > MAX_COMMAND_CHARS:  # a file's content written by a heredoc is no command
        return None
    segments = _parse_raw(text, 0)
    if segments is None or len(segments) > MAX_SEGMENTS:
        return None
    return segments


def is_env_assignment(token: str) -> bool:
    """``NAME=value`` as a shell reads it before a command."""
    return _is_env_assignment(token)


def command_segments(command: str) -> list[Segment] | None:
    """The normalized simple-command segments of a shell command, or ``None`` if unparseable."""

    text = str(command or "")
    if len(without_data_heredocs(text)) > MAX_COMMAND_CHARS:  # a file's content written by a heredoc is no command
        return None
    segments = _parse(text, 0)
    if segments is None or len(segments) > MAX_SEGMENTS:
        return None
    return segments


# git's global options before its subcommand (``git -C . -c k=v push``): the subcommand decides, not its position.
_GIT_OPTIONS_WITH_VALUE = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path",
                                     "--super-prefix", "--config-env", "--attr-source"})


def git_normalized(segment: Segment) -> Segment:
    """A ``git`` segment without its global options; any other segment unchanged."""

    if not segment or posixpath.basename(segment[0]) != "git":
        return segment
    index = 1
    while index < len(segment) and segment[index].startswith("-"):
        index += 2 if segment[index] in _GIT_OPTIONS_WITH_VALUE else 1
    return (segment[0], *segment[index:])


def segment_matches(segment: Segment, prefix: Sequence[str]) -> bool:
    """First token by basename, every further prefix token exactly (git after its global options)."""

    segment = git_normalized(segment) if prefix and prefix[0] == "git" else segment
    if not prefix or len(segment) < len(prefix):
        return False
    if posixpath.basename(segment[0]) != prefix[0]:
        return False
    return tuple(segment[1 : len(prefix)]) == tuple(prefix[1:])


def segment_has_argument(segment: Segment, argument: str) -> bool:
    """``argument`` as its own token or in ``argument=value`` form, after the command name."""

    return any(token == argument or token.startswith(f"{argument}=") for token in segment[1:])


def writes_by_redirection(command: str) -> bool | None:
    """Whether a shell command redirects output into a file (``>``, ``>>``, ``&>``); ``None`` if unparseable.

    Segments drop redirections (they are not part of the command), so a read-only classification
    asks this separately. Heredoc bodies are data. ``2>&1`` and ``>&2`` duplicate descriptors and
    write no file; ``<`` reads.
    """
    text = _strip_heredoc_bodies(str(command or ""))
    try:
        tokens = _tokenize(text)
    except ValueError:
        return None
    for index, token in enumerate(tokens):
        if not _is_operator(token) or ">" not in token:
            continue
        following = tokens[index + 1] if index + 1 < len(tokens) else ""
        if following.startswith("&") or (token.endswith("&") and following.isdigit()):
            continue
        return True
    return False


def first_matching_segment(segments: Sequence[Segment], prefix: Sequence[str]) -> Segment | None:
    return next((segment for segment in segments if segment_matches(segment, prefix)), None)


__all__ = [
    "command_segments",
    "first_matching_segment",
    "git_normalized",
    "segment_has_argument",
    "segment_matches",
    "writes_by_redirection",
]
