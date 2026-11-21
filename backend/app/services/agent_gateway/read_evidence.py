"""Claude Code's own reads (Read, Grep, Glob, LS) as read evidence of a governed session.

A workflow phase that asks "the code was read" names the platform's read tools (``read_workspace_file``,
``grep_workspace``, ...). An octryx-claude session reads with Claude Code's native tools instead, on the device.
Such a read counts only when the server recorded it, never because the model says so:

1. the launcher's PostToolUse hook reported the call (``POST sessions/tool-executed``): the server derives the
   read target from the hook payload's ``tool_input`` and ``cwd`` and records whether it lies inside the
   session's bound repository root (:func:`read_target`, ``parameters["read_target"]``) — the path is computed
   here, nothing the client labels is trusted;
2. the execution outcome is the hook's ``succeeded`` (a failed or refused read is no evidence);
3. the model gateway recorded the same ``tool_use`` in the proxied conversation (``block_index``): the model
   really asked for it.

Only then :func:`native_read_use` yields the platform read tool's name as a succeeded use. A read outside the
root, without a bound root, without the hook or without the transcript row is recorded as not succeeded.
"""

from __future__ import annotations

import posixpath
from collections.abc import Mapping
from typing import Any

from ...models import Session, ToolCall
from ..workflow_checks.library import ToolUse
from .capability import bound_root, within_root
from .contract import EXECUTION_OUTCOME_SUCCEEDED, TOOL_CALL_EXECUTED_KEY, TOOL_CALL_SOURCE_HOOK
from .shell_read import shell_read
from .tool_check import candidate_paths

READ_TARGET_KEY = "read_target"
# Claude Code's read tool → the platform read tool a phase's checks name.
NATIVE_READ_EVIDENCE = {
    "Read": "read_workspace_file",
    "Grep": "grep_workspace",
    "Glob": "glob_workspace_files",
    "LS": "list_workspace_directory",
}
# The field of each tool's input that names what it reads; without one the tool reads the cwd.
_TARGET_FIELD = {"Read": "file_path", "Grep": "path", "Glob": "path", "LS": "path"}
MAX_TARGET_CHARS = 500
SHELL_TOOL = "Bash"  # the hooks' name of a shell call, for Claude Code and Codex alike


def _escapes(pattern: Any) -> bool:
    text = str(pattern or "")
    return text.startswith(("/", "~")) or ".." in text.split("/")


def read_target(session: Session, hook_input: Mapping[str, Any]) -> dict[str, Any] | None:
    """The server's view of one native read: the tool, whether it stays in the bound root, the relative path.

    A plain shell read (``Bash``, both engines; ``shell_read``) is one too, with the platform read tool it stands
    for (``read_tool``)."""
    tool = str(hook_input.get("tool_name") or "")
    if tool == SHELL_TOOL:
        tool_input = hook_input.get("tool_input") if isinstance(hook_input.get("tool_input"), Mapping) else {}
        shell = shell_read(str(tool_input.get("command") or ""), str(hook_input.get("cwd") or ""),
                           bound_root(session))
        return {"tool": SHELL_TOOL, **shell} if shell is not None else None
    if tool not in NATIVE_READ_EVIDENCE:
        return None
    tool_input = hook_input.get("tool_input") if isinstance(hook_input.get("tool_input"), Mapping) else {}
    cwd = str(hook_input.get("cwd") or "")
    raw = str(tool_input.get(_TARGET_FIELD[tool]) or "") or cwd
    root = bound_root(session)
    paths = candidate_paths(raw, cwd) if raw and not raw.startswith("~") else []
    target = paths[-1] if paths else ""
    inside = bool(root and target.startswith("/") and within_root(target, root))
    if tool == "Glob" and _escapes(tool_input.get("pattern")):
        inside = False  # a pattern that climbs out of (or replaces) the searched directory
    relative = posixpath.relpath(posixpath.normpath(target), posixpath.normpath(root)) if inside and root else ""
    return {"tool": tool, "in_root": inside, "path": relative[:MAX_TARGET_CHARS]}


def native_read_use(row: ToolCall) -> ToolUse | None:
    """The platform read tool use one recorded native read stands for; ``None`` for any other tool.

    A plain shell read counts under the same three conditions: the hook's target says a plain read inside the root
    (``read_tool``), the hook reported success, and the gateway recorded the call (``block_index``). The row's own
    name is the model's (``Bash`` for Claude Code, ``exec_command``/``shell`` for Codex)."""
    tool = str(row.tool_name or "")
    parameters = row.parameters if isinstance(row.parameters, Mapping) else {}
    target = parameters.get(READ_TARGET_KEY) if isinstance(parameters.get(READ_TARGET_KEY), Mapping) else {}
    if target.get("tool") == SHELL_TOOL and target.get("read_tool") in NATIVE_READ_EVIDENCE.values():
        tool = SHELL_TOOL
    elif tool not in NATIVE_READ_EVIDENCE:
        return None
    executed = parameters.get(TOOL_CALL_EXECUTED_KEY) if isinstance(parameters.get(TOOL_CALL_EXECUTED_KEY),
                                                                     Mapping) else {}
    succeeded = (
        executed.get("source") == TOOL_CALL_SOURCE_HOOK
        and executed.get("outcome") == EXECUTION_OUTCOME_SUCCEEDED
        and target.get("tool") == tool
        and target.get("in_root") is True
        and "block_index" in parameters
    )
    platform_tool = str(target["read_tool"]) if tool == SHELL_TOOL else NATIVE_READ_EVIDENCE[tool]
    return ToolUse(platform_tool, succeeded, None, {"path": target.get("path")})


# Claude Code's own web tools → the platform web tools a research phase's checks name (a server whose egress is
# restricted fails the platform's ``web_search`` / ``web_fetch`` with ``transport``, so a device session researches
# with the engine's own tools, which leave from the device).
NATIVE_WEB_EVIDENCE = {"WebSearch": "web_search", "WebFetch": "web_fetch"}


def native_web_use(row: ToolCall) -> ToolUse | None:
    """The platform web tool use one recorded native web call stands for; ``None`` for any other tool.

    Counts under the same conditions as a read, without a target: the launcher's PostToolUse hook reported success
    and the gateway recorded the call in the proxied conversation (``block_index``)."""
    tool = str(row.tool_name or "")
    if tool not in NATIVE_WEB_EVIDENCE:
        return None
    parameters = row.parameters if isinstance(row.parameters, Mapping) else {}
    executed = parameters.get(TOOL_CALL_EXECUTED_KEY) if isinstance(parameters.get(TOOL_CALL_EXECUTED_KEY),
                                                                     Mapping) else {}
    succeeded = (executed.get("source") == TOOL_CALL_SOURCE_HOOK
                 and executed.get("outcome") == EXECUTION_OUTCOME_SUCCEEDED and "block_index" in parameters)
    return ToolUse(NATIVE_WEB_EVIDENCE[tool], succeeded, None, {"native": tool})


__all__ = ["NATIVE_READ_EVIDENCE", "NATIVE_WEB_EVIDENCE", "READ_TARGET_KEY", "native_read_use", "native_web_use",
           "read_target"]
