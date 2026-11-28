"""Code-owned rules that keep a governed session's tools away from the platform's credentials.
No Workspace can switch them off."""

from __future__ import annotations

import posixpath
from typing import Any

from .command_match import command_segments
from .tool_check import DECISION_DENY, PATH_FIELDS, ToolDecision

RULE_ID = "platform-credentials-protected"
REASON = "platform_credentials_protected"
LAUNCHER_COMMANDS = frozenset({"octryx-claude", "octryx_claude_entry.py"})
LAUNCHER_MODULE = "octryx_claude"
# Launcher subcommands that hold no token and read no state: a repository build step the platform's own code style
# tells the agent to run (code_style built_in.json, ``l10n.merge``: ``octryx-claude l10n-merge {format} ...``). Denying
# it makes the agent hand-edit the merged translation files.
# The command still must not name a protected marker (checked before the segments).
OPEN_SUBCOMMANDS = frozenset({"l10n-merge"})
PROTECTED_MARKERS = (
    "/api/v1/agent-gateway",
    "/api/v1/mcp/",
    "/api/v1/model-gateway",
    "/oauth/token",
    "/oauth/authorize",
    ".octryx/claude",
    "OCTRYX_CLAUDE_HOME",
)
_MESSAGE = (
    "Octryx protects its own credentials and control endpoints from the session's tools. "
    "Use the Octryx MCP tools instead; a workflow confirmation is asked in your permission prompt."
)


def _deny() -> ToolDecision:
    return ToolDecision(DECISION_DENY, "denied", REASON, RULE_ID, _MESSAGE)


def _launcher_segment(segment: tuple[str, ...]) -> bool:
    if not segment:
        return False
    if posixpath.basename(segment[0]) in LAUNCHER_COMMANDS:
        return not (len(segment) > 1 and segment[1] in OPEN_SUBCOMMANDS)
    return LAUNCHER_MODULE in segment[1:3] or any(
        LAUNCHER_MODULE in posixpath.basename(token) for token in segment[1:3]
    )


def self_protection_decision(hook_input: dict[str, Any], *, state_root: str | None = None) -> ToolDecision | None:
    markers = (*PROTECTED_MARKERS, state_root) if state_root else PROTECTED_MARKERS

    def _names_protected(text: str) -> bool:
        return any(marker in text for marker in markers)

    tool_name = str(hook_input.get("tool_name") or "")
    tool_input = hook_input.get("tool_input") if isinstance(hook_input.get("tool_input"), dict) else {}
    if tool_name == "Bash":
        command = str(tool_input.get("command") or "")
        if _names_protected(command):
            return _deny()
        segments = command_segments(command) or []
        if any(_launcher_segment(segment) for segment in segments):
            return _deny()
        return None
    for field in PATH_FIELDS:
        value = tool_input.get(field)
        if isinstance(value, str) and _names_protected(value):
            return _deny()
    return None


__all__ = ["REASON", "RULE_ID", "self_protection_decision"]
