"""The structural shell parser of the device's hard-deny list (``run_shell``), a copy of the server's
``agent_gateway.command_match`` (stdlib only, no I/O): a command's segments, nested shells and substitutions
included, and heredoc bodies that are data."""

from __future__ import annotations

import posixpath
import re
import shlex
from collections.abc import Sequence

Segment = tuple[str, ...]

# --- agent_gateway.command_match ------------------------------------------------------------------------------------

MAX_COMMAND_CHARS = 64_000
MAX_SEGMENTS = 400
MAX_NESTING = 3
_PUNCTUATION = ";&|()<>\n`"
_SEPARATOR_CHARS = frozenset("();|\n`")
_REDIRECT_CHARS = frozenset("<>")
_SHELLS = frozenset({"sh", "bash", "zsh", "dash"})
_WRAPPERS = frozenset({"env", "sudo", "command", "exec", "nohup", "time"})
_HEREDOC = re.compile(r"(?<!<)<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
_SHELL_INPUT_WORDS = _SHELLS | {"eval", "source", ".", "xargs"}


def _tokenize(command: str) -> list[str]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=_PUNCTUATION)
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def _feeds_a_shell(line: str) -> bool:
    return any(posixpath.basename(word.strip("'\"()")) in _SHELL_INPUT_WORDS
               for word in re.split(r"[\s;&|]+", line) if word)


def _strip_heredoc_bodies(command: str, *, keep_shell_input: bool = False) -> str:
    lines = command.split("\n")
    kept: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        kept.append(line)
        index += 1
        if keep_shell_input and _feeds_a_shell(line):
            continue
        for match in _HEREDOC.finditer(line):
            delimiter = match.group(2)
            end = next((i for i in range(index, len(lines)) if lines[i].strip() == delimiter), None)
            if end is not None:
                index = end + 1
    return "\n".join(kept)


def without_data_heredocs(command: str) -> str:
    """The command without the bodies of its heredocs that are data; a body a shell reads stays."""
    return _strip_heredoc_bodies(str(command or ""), keep_shell_input=True)


def _is_operator(token: str) -> bool:
    return bool(token) and all(char in _PUNCTUATION for char in token)


def _is_env_assignment(token: str) -> bool:
    name, sep, _ = token.partition("=")
    return bool(sep) and bool(name) and (name[0].isalpha() or name[0] == "_") and all(
        char.isalnum() or char == "_" for char in name)


def _normalize(words: list[str]) -> Segment:
    index = 0
    while index < len(words) and (_is_env_assignment(words[index]) or words[index] in _WRAPPERS):
        index += 1
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
            inner.append(word[start + 2: end])
    inner.extend(word.split("`")[1:-1:2])
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


def command_segments(command: str) -> list[Segment] | None:
    """The normalized simple-command segments of a shell command, or ``None`` if unparseable."""
    text = str(command or "")
    if len(without_data_heredocs(text)) > MAX_COMMAND_CHARS:
        return None
    segments = _parse(text, 0)
    if segments is None or len(segments) > MAX_SEGMENTS:
        return None
    return segments


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
    if not prefix or len(segment) < len(prefix) or posixpath.basename(segment[0]) != prefix[0]:
        return False
    return tuple(segment[1:len(prefix)]) == tuple(prefix[1:])
