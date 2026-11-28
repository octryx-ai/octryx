"""A plain shell read inside the bound repository root as read evidence (both engines)."""

from __future__ import annotations

import posixpath
import re
import shlex

from .command_match import raw_command_segments, writes_by_redirection
from .stored_types import ShellRead
from .tool_check import candidate_paths

READ_FILE = "read_workspace_file"
GREP = "grep_workspace"
LIST = "list_workspace_directory"
GLOB = "glob_workspace_files"
READERS = {"cat": READ_FILE, "head": READ_FILE, "tail": READ_FILE, "nl": READ_FILE, "wc": READ_FILE,
           "sed": READ_FILE, "grep": GREP, "rg": GREP, "ls": LIST, "tree": LIST, "find": GLOB}
_SHELLS = frozenset({"sh", "bash", "zsh", "dash"})
# A command with several readers (``ls src && cat README.md``) counts as its strongest read: a file read is what a
# phase's "the code was read" asks for (``read_workspace_file``).
_STRENGTH = {LIST: 0, GLOB: 1, GREP: 2, READ_FILE: 3}
_FIND_ACTIONS = frozenset({"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprint0", "-fprintf", "-fls"})
_SED_PRINT = re.compile(r"^\d+(,\d+)?p$")
# Options of these readers that take a value (the value is no path).
_VALUE_OPTIONS = {
    "head": {"-n", "-c"}, "tail": {"-n", "-c"}, "grep": {"-e", "-f", "-m", "-A", "-B", "-C", "--include", "--exclude"},
    "rg": {"-e", "-g", "-t", "-T", "-m", "-A", "-B", "-C", "--glob", "--type", "--max-count"},
    "tree": {"-L", "-I", "-P"}, "ls": set(), "cat": set(), "nl": set(), "wc": set(), "sed": set(),
}
_PATTERN_FIRST = frozenset({"grep", "rg"})


def unwrap(command: str) -> str:
    try:
        words = shlex.split(command)
    except ValueError:
        return command
    if len(words) == 3 and posixpath.basename(words[0]) in _SHELLS and re.fullmatch(r"-[a-z]*c[a-z]*", words[1]):
        return words[2]
    return command


def _paths(name: str, args: list[str]) -> list[str] | None:
    if name == "find":
        if any(arg in _FIND_ACTIONS for arg in args):
            return None
        paths: list[str] = []
        for arg in args:  # the start points come first; the expression (tests) follows
            if arg.startswith("-") or arg in ("(", ")", "!"):
                break
            paths.append(arg)
        return paths
    if name == "sed":
        options = [arg for arg in args if arg.startswith("-")]
        rest = [arg for arg in args if not arg.startswith("-")]
        if options != ["-n"] or not rest or not _SED_PRINT.match(rest[0]):
            return None  # only ``sed -n 'N[,M]p' file``: no in-place edit, no script that writes or runs
        return rest[1:]
    value_options = _VALUE_OPTIONS.get(name, set())
    positional: list[str] = []
    skip = False
    for arg in args:
        if skip:
            skip = False
            continue
        if arg in value_options:
            skip = True
            continue
        if arg.startswith("-") and arg != "-":
            continue
        positional.append(arg)
    if name in _PATTERN_FIRST and not any(arg in ("-e", "-f") for arg in args):
        positional = positional[1:]  # the first positional argument is the pattern
    return positional


def shell_read(command: str, cwd: str, root: str | None) -> ShellRead | None:
    script = unwrap(str(command or ""))
    if "$" in script or "`" in script or writes_by_redirection(script) is not False:
        return None
    segments = raw_command_segments(script)
    if not segments:
        return None
    read_tool = ""
    targets: list[str] = []
    strongest: list[str] = []  # the paths of the strongest reader (its first one names the target)
    for segment in segments:
        name = posixpath.basename(segment[0])
        if name not in READERS or "=" in segment[0]:
            return None  # a writer, ``cd``, a wrapper or an environment assignment: not a plain read
        paths = _paths(name, list(segment[1:]))
        if paths is None:
            return None
        if not read_tool or _STRENGTH[READERS[name]] > _STRENGTH[read_tool]:
            read_tool, strongest = READERS[name], paths
        targets.extend(paths)
    if not root or not cwd.startswith("/"):
        return {"read_tool": read_tool, "in_root": False, "path": ""}
    def absolute(path: str) -> str:
        found = candidate_paths(path, cwd)
        return found[-1] if found else ""

    resolved = [absolute(path) for path in targets] or [cwd]
    base = posixpath.normpath(root)
    inside = all(path.startswith("/") and (posixpath.normpath(path) == base or posixpath.normpath(path).startswith(
        base.rstrip("/") + "/")) for path in resolved)
    named = absolute(strongest[0]) if strongest else cwd
    relative = posixpath.relpath(posixpath.normpath(named), base) if inside else ""
    return {"read_tool": read_tool, "in_root": inside, "path": relative[:500]}


__all__ = ["READERS", "shell_read", "unwrap"]
