"""The capability of a governed Claude Code session outside a workflow run, enforced on every PreToolUse.

A session that is not bound to a workflow run is
**read-only**, always. A run-bound session never reaches this module (``workflow_runs.octryx.hooks.run_pre_tool_use``
decides with the phase's class, tools and path rules first). An approved ``workflow_confirmation:<key>`` raises
nothing: changes happen only inside a B or C run (``workflow_select`` with a Work
item starts or attaches one).

:func:`effective_capability` records the class on the gateway session (``metadata.effective_capability``);
:func:`capability_decision` enforces it with closed tool classes:

- **read tools** (Read, Grep, Glob, WebFetch, Task, ...) and the platform's own MCP tools: allowed.
  The platform MCP tools are governed server-side.
- **file mutations** (Edit, Write, MultiEdit, NotebookEdit): denied, ``capability_read_only``.
- **Bash**:
  - every class: a destructive pattern of the exec policy is denied, ``destructive_command``;
  - ``read_only``: every segment must pass the platform's read-only command rules
    (``security_analyzer.builtins.read_only_command_finding``, the same rules a platform
    diagnosis run uses), and the command must not redirect into a file. Anything else is
    ``capability_read_only``.
- **any other tool**: ``tool_not_classified`` (deny by default).

Every denial carries the hint to start a workflow run for a Work item, so the user knows the next step.
"""

from __future__ import annotations

import posixpath
import re
import shlex
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.tools.capability_requirements import CAPABILITY_CHANGE, CAPABILITY_DELIVER, CAPABILITY_READ_ONLY

from ...models import Session
from ..exec_policy import get_effective_exec_policy_config
from ..run_capability.classes import CAPABILITY_CLASSES
from ..security_analyzer.builtins import read_only_command_finding
from ..security_analyzer.invocation import read_only_invocation_refusal
from .capability_session import EffectiveCapability, _bound_root, _mode, effective_capability
from .command_match import command_segments, segment_matches, writes_by_redirection
from .command_tokens import without_data_heredocs
from .tool_check import DECISION_DENY, ToolDecision, candidate_paths

PLATFORM_MCP_TOOL_PREFIX = "mcp__octryx-knowledge__"
FILE_MUTATION_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})
SHELL_TOOLS = frozenset({"Bash"})
READ_TOOLS = frozenset(
    {
        "Read", "Glob", "Grep", "LS", "NotebookRead", "WebFetch", "WebSearch", "TodoWrite", "TodoRead",
        "Task", "Agent", "ExitPlanMode", "EnterPlanMode", "BashOutput", "KillShell", "KillBash",
        "TaskOutput", "TaskStop", "AskUserQuestion", "Skill", "SlashCommand", "ListMcpResourcesTool",
        "ReadMcpResourceTool", "ToolSearch",
        # Claude Code's message to a subagent it started (it continues an ``Agent``; the subagent's own tool calls go
        # through this check). Without this entry it is refused as unclassified and costs a retry.
        "SendMessage",
    }
)
CONFIRM_HINT = ("This session only reads in plan mode or in a Workspace that keeps sessions read-only: leave plan "
                "mode, or start feature delivery or bug fix for a Work item (workflow_catalog, then workflow_select).")

REASON_READ_ONLY = "capability_read_only"
REASON_OUTSIDE_ROOT = "outside_repository_root"
REASON_ROOT_UNKNOWN = "repository_root_unknown"
REASON_DESTRUCTIVE = "destructive_command"
REASON_UNCLASSIFIED = "tool_not_classified"
REASON_UNPARSEABLE = "command_unparseable"
REASON_DELIVER = "capability_deliver_required"
REASON_BYPASS_DISABLED = "bypass_disabled_in_workspace"
# Commands that leave the workspace (push, pull requests): ``deliver``, never ``change``.
DELIVER_COMMAND_PREFIXES: tuple[tuple[str, ...], ...] = (
    ("git", "push"),
    ("gh", "pr", "create"),
    ("gh", "pr", "merge"),
    ("glab", "mr", "create"),
    ("glab", "mr", "merge"),
)

_MESSAGES = {
    REASON_BYPASS_DISABLED: "This Workspace does not allow bypass mode; switch to another permission mode.",
    "bypass_requires_workspace_owner": "Only the Workspace's owners may use bypass mode; switch to another permission "
                                       "mode.",
    REASON_READ_ONLY: "This session is read-only: {tool} would change files or state.",
    REASON_OUTSIDE_ROOT: "The confirmed workflow allows changes only inside the bound repository {root}.",
    REASON_ROOT_UNKNOWN: "No repository root is bound to this session, so changes cannot be scoped.",
    REASON_DESTRUCTIVE: "This command matches a destructive pattern of the Workspace execution policy.",
    REASON_UNCLASSIFIED: "Octryx does not classify the tool {tool}, so it is denied.",
    REASON_UNPARSEABLE: "Octryx could not parse this shell command safely.",
    REASON_DELIVER: "Pushing or opening a pull request needs a confirmed deliver workflow.",
}


def _rank(capability_class: str) -> int:
    return CAPABILITY_CLASSES.index(capability_class) if capability_class in CAPABILITY_CLASSES else -1


def _deny(reason: str, **values: str) -> ToolDecision:
    message = _MESSAGES[reason].format(**values)
    return ToolDecision(DECISION_DENY, "denied", reason, reason.replace("_", "-"),
                        f"{message} {CONFIRM_HINT}")


def _within(path: str, root: str) -> bool:
    normalized, base = posixpath.normpath(path), posixpath.normpath(root)
    return normalized == base or normalized.startswith(base.rstrip("/") + "/")


def _destructive(command: str, patterns: list[str]) -> bool:
    """A destructive pattern in the command itself; the text a heredoc writes into a file is data, not a command
    (``command_match.without_data_heredocs``)."""
    text = without_data_heredocs(command)
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _delivers(command: str) -> bool:
    return any(
        segment_matches(segment, prefix)
        for segment in command_segments(command) or []
        for prefix in DELIVER_COMMAND_PREFIXES
    )


def _bash_read_only(command: str, config: dict[str, Any]) -> ToolDecision | None:
    segments = command_segments(command)
    redirects = writes_by_redirection(command)
    if segments is None or redirects is None:
        return _deny(REASON_UNPARSEABLE)
    if redirects:
        return _deny(REASON_READ_ONLY, tool="Bash")
    # Segments drop ``NAME=value`` prefixes and wrappers; the shared invocation rule judges the raw
    # segments first (``HOME=``/``PATH=``/``KUBECONFIG=``, ``env``/``timeout``/``sudo`` …, ``/x/kubectl``).
    if read_only_invocation_refusal(command) is not None:
        return _deny(REASON_READ_ONLY, tool="Bash")
    for segment in segments:
        # Open scope boundary: ``--context`` names any context of the client's own kubeconfig,
        # which the gateway policy requires (``kubectl-requires-context``); no allowed-context binding
        # exists yet. Every other override stays refused.
        finding = read_only_command_finding(shlex.join(segment), config, kubectl_context_selectable=True)
        if segment and finding.action != "allow":
            return _deny(REASON_READ_ONLY, tool="Bash")
    return None


def unknown_tool_decision(tool_name: str, defaults: dict[str, Any] | None) -> ToolDecision:
    """A tool no class names: allowed and logged by default (otherwise Codex's ``web.run`` and ``spawn_agent``
    would be refused); the Workspace's ``tool_defaults.unknown_tools: deny`` refuses it, with the one-click fix
    of allowing this one tool (``allowed_tools``)."""
    from .tool_check import allowed_by_default, setting_remedy  # noqa: PLC0415

    name = tool_name[:80] or "unknown"
    if defaults is not None and (defaults.get("unknown_tools") != "deny" or tool_name in
                                 set(defaults.get("allowed_tools") or [])):
        return allowed_by_default("unknown_tools")
    decision = _deny(REASON_UNCLASSIFIED, tool=name)
    if defaults is None:
        return decision
    return ToolDecision(decision.decision, decision.state, decision.reason, decision.rule_id,
                        decision.message + " A Workspace admin can allow it (Workspace settings › Coding tools & "
                        "devices › Tool defaults).",
                        remedy=setting_remedy("allowed_tools", [tool_name], tool_name))


def capability_decision(
    capability: EffectiveCapability, hook_input: dict[str, Any], exec_config: dict[str, Any],
    defaults: dict[str, Any] | None = None,
) -> ToolDecision | None:
    """The denial of one PreToolUse under ``capability``; ``None`` means no objection. Pure. With the Workspace's
    ``defaults`` (``device_runs.tool_defaults``), an unclassified tool follows them: an allow carrying
    ``allowed_by_default``, or a denial with its remedy."""
    tool_name = str(hook_input.get("tool_name") or "")
    tool_input = hook_input.get("tool_input") if isinstance(hook_input.get("tool_input"), dict) else {}
    cwd = str(hook_input.get("cwd") or "")
    may_change = _rank(capability.capability_class) >= _rank(CAPABILITY_CHANGE)
    if tool_name in READ_TOOLS or tool_name.startswith(PLATFORM_MCP_TOOL_PREFIX):
        return None
    if tool_name in FILE_MUTATION_TOOLS:
        if not may_change:
            return _deny(REASON_READ_ONLY, tool=tool_name)
        if capability.root is None:
            return _deny(REASON_ROOT_UNKNOWN)
        raw = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        paths = candidate_paths(str(raw), cwd)[-1:] if raw else []
        if not paths or not _within(paths[0], capability.root) or posixpath.normpath(paths[0]) == posixpath.normpath(
            capability.root
        ):
            return _deny(REASON_OUTSIDE_ROOT, root=capability.root)
        return None
    if tool_name in SHELL_TOOLS:
        command = str(tool_input.get("command") or "")
        if _destructive(command, list(exec_config.get("always_deny_patterns") or [])):
            return _deny(REASON_DESTRUCTIVE)
        if may_change and capability.root is not None and cwd.startswith("/") and _within(cwd, capability.root):
            if _rank(capability.capability_class) < _rank(CAPABILITY_DELIVER) and _delivers(command):
                return _deny(REASON_DELIVER)
            return None
        return _bash_read_only(command, exec_config)
    return unknown_tool_decision(tool_name, defaults)


# Shared with the workflow run decision of a run-bound session (``workflow_runs/octryx/tool_policy``).
bash_read_only_denial = _bash_read_only
bound_root = _bound_root
within_root = _within


async def enforce_capability(
    db: AsyncSession, *, session: Session, session_key: str, hook_input: dict[str, Any]
) -> ToolDecision | None:
    from ...models import Project  # noqa: PLC0415
    from .role_modes import (  # noqa: PLC0415
        CEILING_BYPASS,
        CEILING_READ_ONLY,
        REASON_BYPASS_OWNER_ONLY,
        session_ceiling,
        workspace_ceiling,
    )

    # The person's role in the Workspace caps the session (viewer reads, member edits, owner also
    # bypass), on top of the Workspace's own switches (free_sessions read_only, bypass_permissions disabled).
    ceiling = await session_ceiling(db, user_id=session.user_id, workspace_id=session.project_id)
    capability = await effective_capability(
        db, session=session, session_key=session_key, hook_input=hook_input,
        free_sessions="read_only" if ceiling == CEILING_READ_ONLY else "follow_permission_mode")
    if _mode(hook_input) == "bypassPermissions" and ceiling != CEILING_BYPASS:
        # The platform enforces it, not only the client's settings.
        project = await db.get(Project, session.project_id) if session.project_id else None
        return _deny(REASON_BYPASS_DISABLED if workspace_ceiling(project) != CEILING_BYPASS else
                     REASON_BYPASS_OWNER_ONLY)
    config = await get_effective_exec_policy_config(db, project_id=session.project_id)
    # A working session may use the person's own tools (other MCP servers, ...): logged as allowed by default unless
    # the Workspace denies unknown tools. A read-only session (plan mode, a read-only Workspace) keeps refusing them.
    defaults = None
    if capability.capability_class != CAPABILITY_READ_ONLY:
        from ..devices.device_runs_keys import device_runs_section, tool_defaults  # noqa: PLC0415
        from .policy import load_workspace_policy  # noqa: PLC0415

        loaded = await load_workspace_policy(db, session.project_id) if session.project_id else None
        raw = loaded.policy.raw if loaded is not None and loaded.policy is not None else {}
        defaults = tool_defaults(device_runs_section(raw))
    return capability_decision(capability, hook_input, config, defaults)


__all__ = [
    "CONFIRM_HINT",
    "FILE_MUTATION_TOOLS",
    "READ_TOOLS",
    "bash_read_only_denial",
    "bound_root",
    "capability_decision",
    "enforce_capability",
    "unknown_tool_decision",
    "within_root",
]
