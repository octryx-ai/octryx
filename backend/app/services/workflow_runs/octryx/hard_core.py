"""The hard core of a run's shell: what no default and no team setting lets a command change."""

from __future__ import annotations

import posixpath

from app.services.agent_gateway.command_tokens import _is_operator, _strip_heredoc_bodies, _tokenize

from ...agent_gateway.command_match import command_segments
from ..protected_paths import protected_kind

TEMP_ROOTS = ("/tmp/", "/private/tmp/", "/var/folders/", "/private/var/folders/", "/dev/null")
_TARGET_LAST = frozenset({"cp", "mv", "install", "ln"})
_ALL_ARGS = frozenset({"tee", "touch", "truncate"})
_IN_PLACE = frozenset({"sed", "gsed", "perl"})
_MODE = frozenset({"chmod", "chown", "chgrp"})
_GIT_CONFIG_READS = frozenset({"--get", "--get-all", "--get-regexp", "--list", "-l", "--show-origin", "--name-only",
                               "--get-urlmatch", "--show-scope"})
_GIT_REMOTE_WRITES = frozenset({"add", "set-url", "rename", "remove", "rm", "set-head", "set-branches"})
GIT_CONFIG = ".git/config"


def _redirect_targets(command: str) -> list[str]:
    try:
        tokens = _tokenize(_strip_heredoc_bodies(str(command or "")))
    except ValueError:
        return []
    found = []
    for index, token in enumerate(tokens):
        if not _is_operator(token) or ">" not in token:
            continue
        following = tokens[index + 1] if index + 1 < len(tokens) else ""
        if not following or following.startswith("&") or (token.endswith("&") and following.isdigit()):
            continue
        found.append(following)
    return found


def _operands(segment: tuple[str, ...]) -> list[str]:
    return [word for word in segment[1:] if not word.startswith("-")]


def _segment_targets(segment: tuple[str, ...]) -> list[str]:
    name = posixpath.basename(segment[0]) if segment else ""
    operands = _operands(segment)
    if name in _ALL_ARGS:
        return operands
    if name in _TARGET_LAST and operands:
        directory = [segment[i + 1] for i, word in enumerate(segment[:-1]) if word in ("-t", "--target-directory")]
        moved = operands[:-1] if name == "mv" else []
        return [*directory, *([] if directory else [operands[-1]]), *moved]
    if name in _IN_PLACE and any(word == "-i" or word.startswith(("-i", "--in-place")) or (
            name == "perl" and word.startswith("-") and "i" in word[1:]) for word in segment[1:]):
        scripted = any(word in ("-e", "-f") for word in segment[1:])
        files = operands if scripted else operands[1:]
        return [word for word in files if "/" in word or "." in word]
    if name in _MODE and len(operands) > 1:
        return operands[1:]
    if name == "dd":
        return [word[3:] for word in segment[1:] if word.startswith("of=")]
    if name == "git":
        from ...agent_gateway.command_match import git_normalized

        words = git_normalized(segment)
        if words[1:2] == ("config",) and not any(word in _GIT_CONFIG_READS for word in words[2:]) and len(
                _operands(words[1:])) >= 2:
            return [GIT_CONFIG]  # a value set (``git config key value``), not a read
        if words[1:2] == ("remote",) and len(words) > 2 and words[2] in _GIT_REMOTE_WRITES:
            return [GIT_CONFIG]
    return []


def written_paths(command: str) -> list[str]:
    from .removal_rules import removal_paths

    paths = _redirect_targets(command)
    for segment in command_segments(command) or []:
        paths += _segment_targets(tuple(segment))
    paths += removal_paths(command) or []
    return list(dict.fromkeys(path for path in paths if path))


def refusal(command: str, cwd: str, root: str | None) -> tuple[str, str] | None:
    if root is None:
        return None  # no bound repository to judge against: the capability decision and the sandbox hold
    for path in written_paths(command):
        if path.startswith("~") or path.startswith("$"):
            return "outside", path
        absolute = posixpath.normpath(path if path.startswith("/") else posixpath.join(cwd or root, path))
        if absolute.startswith(TEMP_ROOTS) or absolute == "/dev/null":
            continue
        normal_root = posixpath.normpath(root)
        if absolute != normal_root and not absolute.startswith(normal_root + "/"):
            return "outside", path
        relative = posixpath.relpath(absolute, normal_root)
        kind = protected_kind(relative, confirmed_files=(), protect_tests=False)
        if kind is not None:
            return kind, relative
    return None


__all__ = ["GIT_CONFIG", "TEMP_ROOTS", "refusal", "written_paths"]
