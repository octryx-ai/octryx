"""Structural shell command matching for the gateway tool policy: a guardrail against mistakes, not a sandbox."""

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
    text = str(command or "")
    if len(without_data_heredocs(text)) > MAX_COMMAND_CHARS:  # a file's content written by a heredoc is no command
        return None
    # Wrappers and assignments stay: a read-only decision must see ``env PATH=/x kubectl``.
    segments = _parse_raw(text, 0)
    if segments is None or len(segments) > MAX_SEGMENTS:
        return None
    return segments


def is_env_assignment(token: str) -> bool:
    return _is_env_assignment(token)


def command_segments(command: str) -> list[Segment] | None:
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
    if not segment or posixpath.basename(segment[0]) != "git":
        return segment
    index = 1
    while index < len(segment) and segment[index].startswith("-"):
        index += 2 if segment[index] in _GIT_OPTIONS_WITH_VALUE else 1
    return (segment[0], *segment[index:])


def segment_matches(segment: Segment, prefix: Sequence[str]) -> bool:
    segment = git_normalized(segment) if prefix and prefix[0] == "git" else segment
    if not prefix or len(segment) < len(prefix):
        return False
    if posixpath.basename(segment[0]) != prefix[0]:
        return False
    return tuple(segment[1 : len(prefix)]) == tuple(prefix[1:])


def segment_has_argument(segment: Segment, argument: str) -> bool:
    return any(token == argument or token.startswith(f"{argument}=") for token in segment[1:])


def writes_by_redirection(command: str) -> bool | None:
    text = _strip_heredoc_bodies(str(command or ""))
    try:
        tokens = _tokenize(text)
    except ValueError:
        return None
    for index, token in enumerate(tokens):
        if not _is_operator(token) or ">" not in token:
            continue
        following = tokens[index + 1] if index + 1 < len(tokens) else ""
        # ``2>&1`` and ``>&2`` duplicate a descriptor and write no file.
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
