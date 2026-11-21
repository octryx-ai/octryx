"""Phase rules of the run-bound PreToolUse decision: the phase's tools, path rules and hard-core paths."""

from __future__ import annotations

import posixpath
import shlex
from typing import Any

from app.services.agent_gateway.command_strict import strict_argv

from ...agent_gateway.capability import FILE_MUTATION_TOOLS, PLATFORM_MCP_TOOL_PREFIX, SHELL_TOOLS, within_root
from ...agent_gateway.command_match import segment_matches, writes_by_redirection
from ...agent_gateway.tool_check import ToolDecision, allowed_by_default, candidate_paths
from ...work_role_model.commands import role_command_allowed
from ..protected_paths import KIND_CONFIRMED_TEST, path_matches, protected_kind, protected_message
from ..run_texts import run_text
from .declared_commands import declared_command, declared_part, declared_with_readers
from .pytest_args import pytest_without_test_names
from .read_only_commands import read_only
from .shell_rules import SHELL_STRICT, free_shell, strict_shell_allows
from .tool_denial import (
    PLATFORM_WRITE_TOOLS,
    REASON_AGENT_TOOLS_DENY,
    REASON_CONFIRMED_TEST,
    REASON_OUTSIDE_PHASE_TOOLS,
    REASON_PHASE_PATH,
    REASON_PROTECTED_PATH,
    TEST_TOOLS,
    _deny,
    _with_remedy,
)


def _mutates(tool_name: str, command: str, exec_config: dict[str, Any]) -> bool:
    if tool_name in FILE_MUTATION_TOOLS:
        return True
    if tool_name in SHELL_TOOLS:
        segments = strict_argv(command)
        return segments is None or not all(read_only(segment) for segment in segments)
    # a tool the platform does not know is no change by default (it was refused while the run
    # waited); only file tools and shell commands that write count.
    return False


def _relative(path: str, root: str | None) -> str | None:
    if root is None or not within_root(path, root):
        return None
    return posixpath.relpath(posixpath.normpath(path), posixpath.normpath(root))


def _path_decision(phase: dict[str, Any], tool_input: dict[str, Any], cwd: str, root: str | None,
                   facts: dict[str, Any], defaults: dict[str, Any] | None = None) -> ToolDecision | None:
    raw = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    paths = candidate_paths(str(raw), cwd)[-1:] if raw else []
    relative = _relative(paths[0], root) if paths else None
    if relative is None:
        return None  # outside the root: the capability decision denies it
    # The launcher resolves the path on the device (symlinks) and says whether it exists: both names must pass.
    resolved = facts.get("resolved_path")
    names = [relative] + ([str(resolved)] if isinstance(resolved, str) and resolved else [])
    # Every file tool may create a file (Edit with an empty old_string does): only the launcher's fact that the
    # target exists makes it an existing file; a missing fact is a new file. A new file also needs the launcher's
    # word that it shadows no installed distribution.
    exists = facts.get("target_exists") is True
    shadows = facts.get("shadows_installed") is not False
    if any(name == ".." or name.startswith("../") or name.startswith("/") for name in names[1:]):
        return _deny(REASON_PHASE_PATH, run_text("block.path_outside", path=relative))
    contract_file = str(phase.get("contract_file") or "")
    if contract_file and not phase.get("allow_contract_change") and contract_file in names:
        # The run's environment file is its contract (otherwise an agent could rewrite it and be judged by it).
        return _deny(REASON_PROTECTED_PATH, run_text("block.contract_file", path=contract_file, phase=phase["title"]))
    protect = bool(phase["path_rules"].get("protect_confirmed_tests"))
    # A flat repository on the device: its confirmed tests sit at the top level, so its modules do too.
    flat = any("/" not in str(name) for name in phase.get("protected_files") or [])
    for name in names:
        kind = protected_kind(name, confirmed_files=phase.get("protected_files") or [], protect_tests=protect,
                              exists=exists, create=phase["path_rules"].get("create") or [], shadows=shadows,
                              flat=flat, tests_free=phase["path_rules"].get("write_tests") is True)
        if kind == KIND_CONFIRMED_TEST:
            from .format_only import formatting_only

            if formatting_only(tool_input, name):
                continue  # the formatter's wish changes no test (format_only)
        if kind is not None:
            reason = REASON_CONFIRMED_TEST if kind == KIND_CONFIRMED_TEST else REASON_PROTECTED_PATH
            return _deny(reason, run_text("block.protected", detail=protected_message(
                kind, name, phase["title"], str(phase.get("protected_by") or "person"))))
    patterns = list(phase["path_rules"].get("write") or [])
    if patterns and not all(any(path_matches(name, pattern) for pattern in patterns) for name in names):
        if (defaults or {}).get("path_rules", "log") == "log" and defaults is not None:
            return allowed_by_default("path_rules")  # logged in the run, not refused
        refused = _deny(REASON_PHASE_PATH, run_text("block.path_rules", phase=phase["title"],
                                                    patterns=", ".join(patterns)))
        return _with_remedy(refused, "path_rules", "log", defaults)
    return None


def pytest_with_names(command: str, test_prefixes: tuple[tuple[str, ...], ...]) -> dict[str, Any] | None:
    """A single pytest command with ``-v`` instead of ``-q``: the input Claude Code runs instead (corrected, not
    refused). ``None`` when the command is not one plain segment."""
    segments = strict_argv(command) or []
    if len(segments) != 1:
        return None
    segment = list(segments[0])
    prefix = next((item for item in test_prefixes if segment_matches(segments[0], item)), None)
    if prefix is None or "pytest" not in prefix:
        return None
    arguments = [token for token in segment[len(prefix):] if token not in ("-q", "-qq", "--quiet")]
    return {"command": shlex.join([*segment[:len(prefix)], "-v", *arguments])}


def _tool_decision(phase: dict[str, Any], tool_name: str, command: str,
                   test_prefixes: tuple[tuple[str, ...], ...], declared: tuple[str, ...] = (),
                   exec_config: dict[str, Any] | None = None,
                   defaults: dict[str, Any] | None = None, app_folder: str = "") -> ToolDecision | None:
    allowed = set(phase["tools"].get("allow") or [])
    denied = set(phase["tools"].get("deny") or [])
    runs_tests = bool((allowed - denied) & TEST_TOOLS)
    if tool_name in FILE_MUTATION_TOOLS and not (allowed - denied) & PLATFORM_WRITE_TOOLS:
        return _deny(REASON_OUTSIDE_PHASE_TOOLS, run_text("block.no_write_tools", phase=phase["title"]))
    if runs_tests and tool_name in SHELL_TOOLS and (declared_command(command, declared)
                                                     or declared_with_readers(command, declared)
                                                     or declared_part(command, declared, app_folder)):
        # The repository's declared test / lint command, verbatim or one ``&&`` step of it (piped into a reader,
        # after a ``cd`` into the app folder).
        return None
    # Before a CI pipeline step the agent's own test output is no evidence the platform reads (the pipeline writes
    # its own JUnit report): ``pytest -q`` is fine there (otherwise the agent was asked again with -v
    # over and over. Elsewhere (TDD gates over the agent's runs) the platform still needs the names.
    if runs_tests and tool_name in SHELL_TOOLS and not phase.get("pipeline_after") and pytest_without_test_names(
            command, test_prefixes):
        if defaults is not None and defaults.get("shell") != "strict":
            return allowed_by_default("shell", updated_input=pytest_with_names(command, test_prefixes))
        return _deny(REASON_OUTSIDE_PHASE_TOOLS, run_text("block.pytest_names"))
    if tool_name in SHELL_TOOLS and role_command_allowed(command, exec_config):
        return None  # a work role's command rule admits it; the Workspace's blocked patterns still apply afterwards
    if tool_name in SHELL_TOOLS and not free_shell(phase) and not strict_shell_allows(
            command, runs_tests=runs_tests, test_prefixes=test_prefixes,
            protected=bool(phase["path_rules"].get("protect_confirmed_tests")), exec_config=exec_config):
        # a phase that changes files runs any command in its folder by default (logged); the hard
        # rules, the Workspace's destructive patterns and the push / SCM rules still apply. A read-only phase keeps
        # its read-only shell (its contract is to change nothing; no evidence checks that yet). A phase that
        # protects confirmed tests runs the default
        # shell too; the confirmed tests are guarded by evidence (their digests, ``confirmed_test_drift``, judged by
        # the gates) and the environment file by its pin, not by parsing commands. The strict shell is the team's
        # choice: the Workspace's ``tool_defaults.shell: strict`` or the node's ``shell: strict``.
        writes = bool(allowed & PLATFORM_WRITE_TOOLS)
        opens = writes and phase.get("shell") != SHELL_STRICT
        if defaults is not None and defaults.get("shell") != "strict" and opens:
            return allowed_by_default("shell")
        key = "shell.write_refused" if writes and writes_by_redirection(command) else "shell.strict_refused"
        refused = _deny(REASON_OUTSIDE_PHASE_TOOLS, run_text(key, phase=phase["title"]))
        return _with_remedy(refused, "shell", "free", defaults) if opens else refused
    return None


def _hard_core(command: str, cwd: str, root: str | None) -> ToolDecision | None:
    """A path the command writes or removes that no setting opens (``hard_core``: git's files, environments,
    outside the repository); a confirmed test and the environment file are left to the evidence and the pin."""
    from .hard_core import refusal

    found = refusal(command, cwd, root)
    if found is None:
        return None
    kind, path = found
    if kind == "outside":
        return _deny(REASON_PHASE_PATH, run_text("block.path_outside", path=path))
    return _deny(REASON_PROTECTED_PATH, run_text("block.protected", detail=protected_message(kind, path, "this run")))


def _agent_tools_deny(phase: dict[str, Any], tool_name: str) -> ToolDecision | None:
    """A platform MCP tool the phase denies, or a native tool that stands for one the published agent denies
    (the explicit ``NATIVE_EQUIVALENTS`` table, never a name heuristic)."""
    from ...agent_tools_deny import native_tool_denied

    if tool_name.startswith(PLATFORM_MCP_TOOL_PREFIX):
        platform_name = tool_name.removeprefix(PLATFORM_MCP_TOOL_PREFIX)
        if platform_name in set(phase["tools"].get("deny") or []):
            return _deny(REASON_AGENT_TOOLS_DENY, run_text("block.agent_tool", phase=phase["title"],
                                                           tool=platform_name))
        return None
    denied_as = native_tool_denied(tool_name, dict(phase.get("agent") or {}).get("tools_deny") or [])
    if denied_as is not None:
        return _deny(REASON_AGENT_TOOLS_DENY, run_text("block.agent_native_tool", denied_as=denied_as,
                                                       tool=tool_name))
    return None
