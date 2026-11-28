"""The path and shell rules of a local tool decision (``local_decisions.decide``). Stdlib only.
"""

from __future__ import annotations

import os
import posixpath
import re
from typing import Any

from . import run_shell

ALLOW, DENY, SERVER = "allow", "deny", "server"
WRITES = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})
PATH_FIELDS = ("file_path", "path", "notebook_path")
# The server's ``protected_paths``: git's own files and environment folders are never edited in a phase.
_PROTECTED_PARTS = frozenset({".git", ".venv", "venv", ".tox", "node_modules", "site-packages", "__pypackages__"})
_CLAUDE_SCRATCH = re.compile(r"^(?:/private)?/tmp/claude(?:-\d+)?/(?!(?:.*/)?\.\.(?:/|$))")


def _inside(path: str, root: str) -> bool:
    try:
        resolved = os.path.realpath(path)
    except (OSError, ValueError):
        return False
    return resolved == root or resolved.startswith(root.rstrip("/") + "/")


def _absolute(raw: str, cwd: str) -> str:
    expanded = os.path.expanduser(raw)
    return posixpath.normpath(expanded if expanded.startswith("/") else posixpath.join(cwd or "/", expanded))


def _glob_hit(path: str, root: str, globs: list[str]) -> bool:
    from fnmatch import fnmatchcase  # noqa: PLC0415

    relative = posixpath.relpath(path, root) if _inside(path, root) else path
    home = os.path.expanduser("~")
    for pattern in globs:
        probe = pattern.replace("~", home, 1) if pattern.startswith("~") else pattern
        if fnmatchcase(relative, probe) or fnmatchcase(path, probe) or (
                probe.startswith("**/") and fnmatchcase(relative, probe[3:])):
            return True
    return False


def _path_decision(tool_name: str, tool_input: dict[str, Any], cwd: str, policy: dict[str, Any]) -> str:
    root, state_root = str(policy["root"]), str(policy.get("state_root") or "")
    raw = next((str(tool_input[field]) for field in PATH_FIELDS if isinstance(tool_input.get(field), str)
                and tool_input[field]), "")
    if not raw and tool_name in WRITES:
        return SERVER
    path = _absolute(raw, cwd) if raw else posixpath.normpath(cwd or "/")
    if run_shell.names_platform_credentials(path, state_root):
        return SERVER
    if _glob_hit(path, root, list(policy.get("server_path_globs") or [])):
        return SERVER
    if tool_name in WRITES and _CLAUDE_SCRATCH.match(path):
        return ALLOW  # Claude Code's own temp folder: the free shell writes there anyway (tool_policy.claude_scratch)
    if not _inside(path, root):
        return SERVER
    if tool_name in WRITES and _PROTECTED_PARTS & set(posixpath.relpath(os.path.realpath(path), root).split("/")):
        return SERVER  # git's own files or an environment folder: the server names the rule
    return ALLOW


def _bash_decision(command: str, cwd: str, policy: dict[str, Any]) -> tuple[str, str, str]:
    state_root = str(policy.get("state_root") or "")
    if run_shell.names_platform_credentials(command, state_root):
        return SERVER, "", ""
    segments = run_shell.command_segments(command)
    if segments is None:
        return _unparseable_decision(command, cwd, policy)
    if run_shell.runs_the_launcher(segments):
        return SERVER, "", ""
    text = run_shell.without_data_heredocs(command)
    for pattern in policy.get("deny_patterns") or []:
        try:
            if re.search(pattern, text, flags=re.IGNORECASE):
                return DENY, "destructive_command", "The Workspace's command safety blocks this command."
        except re.error:
            return SERVER, "", ""
    refused = run_shell.bash_run_rules(command, hosts=frozenset(policy.get("scm_hosts") or ()))
    if refused is not None:
        return DENY, refused[0], refused[1]
    for prefix in policy.get("server_commands") or []:
        if prefix == ["*"] or any(run_shell.segment_matches(segment, prefix) for segment in segments if segment):
            return SERVER, "", ""  # a Workspace or role command rule names it: the server applies the rule
    if not cwd or not _inside(cwd, str(policy["root"])):
        return SERVER, "", ""
    return ALLOW, "", ""


# The words of every command the hard-deny list and the run rules name: an unparseable command that contains none of
# them as a word cannot run one.
_HARD_WORDS = re.compile(r"(?<![\w.-])(?:git|curl|wget|scp|sftp|ftp|nc|ncat|netcat|socat|rsync|rm|gh|glab|hub|jira|"
                         r"acli|bb|security|printenv|env|http|https|xh|httpie|ssh|eval|source|xargs|kubectl)(?![\w-])")


def _unparseable_decision(command: str, cwd: str, policy: dict[str, Any]) -> tuple[str, str, str]:
    text = run_shell.without_data_heredocs(command)
    if run_shell.hard_denied(command) is not None or _HARD_WORDS.search(text):
        return SERVER, "", ""
    for pattern in policy.get("deny_patterns") or []:
        try:
            if re.search(pattern, text, flags=re.IGNORECASE):
                return SERVER, "", ""
        except re.error:
            return SERVER, "", ""
    if not cwd or not _inside(cwd, str(policy["root"])):
        return SERVER, "", ""
    return ALLOW, "", ""
