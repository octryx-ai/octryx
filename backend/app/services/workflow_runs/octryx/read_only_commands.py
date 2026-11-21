"""The closed set of read-only shell commands, with their writing or executing options refused."""

from __future__ import annotations

import posixpath
import re

from app.services.agent_gateway.command_tokens import Segment

# Read-only commands and the options that would make them write or run something.
READ_ONLY: dict[str, frozenset[str]] = {
    "ls": frozenset(), "cat": frozenset(), "head": frozenset(), "tail": frozenset(), "wc": frozenset(),
    "pwd": frozenset(), "stat": frozenset(), "diff": frozenset(), "echo": frozenset(), "which": frozenset(),
    "true": frozenset(), "grep": frozenset(),
    "rg": frozenset({"--pre", "--pre-glob", "--search-zip", "-z"}),
    "find": frozenset({"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprint0", "-fprintf", "-fls"}),
    "tree": frozenset({"-o"}),
    "file": frozenset({"-C", "--compile", "-m", "--magic-file"}),
    "sort": frozenset({"-o", "--output", "-T", "--temporary-directory", "--compress-program", "--files0-from"}),
    "cut": frozenset(), "tr": frozenset(), "nl": frozenset(), "basename": frozenset(), "dirname": frozenset(),
    "realpath": frozenset(), "du": frozenset(), "jq": frozenset(), "uniq": frozenset(),
}
_REPO_FOLDER = re.compile(r"^[A-Za-z0-9_.][A-Za-z0-9_./-]*$")
GIT_READ_ONLY = frozenset({"status", "diff", "log", "show", "ls-files", "rev-parse", "blame"})
GIT_REFUSED = frozenset({"--output", "--ext-diff", "--textconv", "-O", "--open-files-in-pager", "--exec"})


# A path-qualified first word runs only when it names an interpreter of a virtual environment or the system.
_KNOWN_BINARY = re.compile(
    r"^(?:(?:\./)?\.?venv/bin/|/usr/bin/|/usr/local/bin/|/opt/homebrew/bin/)(?:python3?(?:\.\d+)?|pytest)$")


def _refused(token: str, refused: frozenset[str]) -> bool:
    if token in refused or token.split("=", 1)[0] in refused:
        return True
    return any(len(option) == 2 and token.startswith(option) and not token.startswith("--") for option in refused)


def _command_name(segment: Segment) -> str | None:
    """The command's name, or ``None`` for a path-qualified word that is no known interpreter (``./ls``)."""
    first = segment[0]
    if "/" in first and not _KNOWN_BINARY.match(first):
        return None
    return posixpath.basename(first)


def _repo_folder(segment: Segment) -> bool:
    """``cd <folder>`` into the repository: one relative path without ``..`` (no ``~``, ``-`` or absolute path)."""
    return len(segment) == 2 and bool(_REPO_FOLDER.match(segment[1])) and ".." not in segment[1].split("/")


def read_only(segment: Segment) -> bool:
    name = _command_name(segment)
    if name == "cd":
        return _repo_folder(segment)
    if name == "uniq" and len([token for token in segment[1:] if not token.startswith("-")]) > 1:
        return False  # ``uniq in out`` writes ``out``
    if name == "sed":
        # Print-only scripts (``sed -n '44,66p;217,251p' SPEC.md``), checked by the read-command grammar. When
        # sed was refused, every implement session read the whole specification
        # (21K tokens) instead of the sections its work item names, and read it again after each compaction.
        from ...security_analyzer.read_only_options import read_option_refusal

        return read_option_refusal(("sed", *segment[1:])) is None
    if name == "git":
        return (len(segment) > 1 and segment[1] in GIT_READ_ONLY
                and not any(_refused(token, GIT_REFUSED) for token in segment[2:]))
    refused = READ_ONLY.get(name or "")
    return refused is not None and not any(_refused(token, refused) for token in segment[1:])


_PYTHON_NAME = re.compile(r"^python(?:\d+(?:\.\d+)?)?$")
