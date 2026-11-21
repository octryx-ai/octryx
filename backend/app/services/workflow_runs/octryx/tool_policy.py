"""The PreToolUse decision of an octryx-claude session bound to a workflow run.

The run's current state decides, never the session's own confirmation:

- **paused** (a loop limit, a budget, a timeout): every change or deliver tool is denied ``run_paused`` — the
  person continues, changes the plan or aborts in the platform (the answer names the link);
- **waiting** (a confirmation, an approval, a watched state, the reviewer) or between phases: change and deliver
  tools are denied ``run_waiting`` with what it waits for and who decides it (a requester decision in
  the terminal through ``workflow_decide`` or in the platform, four-eyes only in the platform);
- **at a phase**: the phase's capability class replaces the session's (``capability.capability_decision`` with the
  bound repository root), and the phase's tools apply to Claude Code's own tools too: Edit / Write / MultiEdit /
  NotebookEdit need a write tool of the phase; the shell follows ``shell_rules`` — free ``bash`` only in a deliver
  phase without path rules, everywhere else plain argv test and read-only commands, and in a phase that runs tests
  the repository's declared test / lint command verbatim (the run contract's ``preparation.environment``). Edits
  follow the phase's path rules (``protected_paths``: the write patterns, git's own files, and with
  ``protect_confirmed_tests`` the confirmed tests and the test runner's configuration), case-folded and also by the
  path the launcher resolved (symlinks). Relaxed for the common read-only and test forms a weak model uses
  (``shell_rules``: pytest options that only change output or selection, ``2>/dev/null``, readers at the end of a
  pipe, ``cd`` into the repository, the declared command piped into ``tail``; before a CI pipeline step also
  ``pytest -q``) after many refusals of harmless commands in benchmark runs;
- **always during a run**: ``git push`` never runs on the device — the platform pushes the reviewed change
  (``workflow_action_request``); SCM and Jira clients (``gh``, ``glab``, ``hub``, ``jira``, ``acli``) and HTTP
  clients aimed at an SCM or Jira host are denied. In a free-shell phase these text rules are a guardrail
  against mistakes, not a boundary: the developer's own credentials are on the device.

Reads pass in every state. Pure decisions over the run, the hook input and the Workspace's hosts.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.agent_gateway.capability_session import EffectiveCapability

from ....models import Session, WorkflowRun
from ...agent_gateway.capability import (
    CONFIRM_HINT,
    FILE_MUTATION_TOOLS,
    PLATFORM_MCP_TOOL_PREFIX,
    READ_TOOLS,
    SHELL_TOOLS,
    bound_root,
    capability_decision,
)
from ...agent_gateway.tool_check import DECISION_DENY, ToolDecision, allowed_by_default
from ...work_role_model.commands import role_command_denial
from ..run_texts import run_text
from ..states import STATUS_PAUSED, STATUS_RUNNING
from .browser_tools import browser_tool_decision, is_browser_tool
from .declared_commands import declared_commands
from .facts import FACTS_KEY
from .phase_rules import _agent_tools_deny, _hard_core, _mutates, _path_decision, _tool_decision
from .removal_rules import (
    _folder_decision,
    _removal_decision,
    recursive_removal_paths,
    removal_paths,
    tracked_only_removal,
)
from .scm_rules import _bash_run_rules
from .shell_rules import free_shell
from .tool_denial import (
    REASON_OUTSIDE_PHASE_TOOLS,
    REASON_ROLE_COMMAND,
    REASON_RUN_PAUSED,
    REASON_RUN_WAITING,
    _allows,
    _deny,
    _with_remedy,
)

# Codex's web search as its hooks name it: the standalone ``web.run`` (sent through the device's seat proxy and
# admitted there, ``codex_seat_search``) and the ChatGPT apps search tool Codex offers next to it.
CODEX_SEARCH_TOOLS = frozenset({"webrun", "web.run", "web__run", "mcp__codex_apps__search_service__web_run"})


def _command_refusal(command: str, hook_input: dict[str, Any], session: Session, *, exec_config: dict[str, Any],
                     hosts: frozenset[str]) -> ToolDecision | None:
    """The rules every shell command of a run obeys, in any state: delivery, the work role, the hard core."""
    refused = _bash_run_rules(command, hosts=hosts)
    if refused is not None:
        return refused
    role_denied = role_command_denial(command, exec_config)
    if role_denied is not None:
        return _deny(REASON_ROLE_COMMAND, role_denied)
    return _hard_core(command, str(hook_input.get("cwd") or ""), bound_root(session))


def _allowed_with_folders(phase: dict[str, Any], tool_name: str, command: str, hook_input: dict[str, Any],
                          session: Session, allowed: ToolDecision, defaults: dict[str, Any] | None) -> ToolDecision:
    """An allowing decision, unless a recursive removal fails the folder rule."""
    # The default's free shell never removes a folder outright (only tracked files, which
    # git can restore): a recursive removal still goes through the folder rule.
    folders = recursive_removal_paths(command) if tool_name in SHELL_TOOLS else None
    if not folders:
        return allowed
    decided = _folder_decision(phase, folders, str(hook_input.get("cwd") or ""), bound_root(session),
                               tracked_only=tracked_only_removal(command), defaults=defaults)
    return decided if decided is not None else allowed


def _phase_refusal(phase: dict[str, Any], tool_name: str, tool_input: dict[str, Any], command: str,
                   hook_input: dict[str, Any], root: str | None, refused: ToolDecision | None,
                   defaults: dict[str, Any] | None) -> tuple[bool, ToolDecision | None]:
    """``(decided, decision)``: the phase's removal, folder and path rules over the tool decision ``refused``."""
    removed = removal_paths(command) if refused is not None and tool_name in SHELL_TOOLS else None
    if removed:
        refused = _removal_decision(phase, removed, str(hook_input.get("cwd") or ""), root)
        if refused is None:
            return True, None  # the phase's own file removal: the path rules decided, no free shell is opened
    folders = recursive_removal_paths(command) if refused is not None and tool_name in SHELL_TOOLS else None
    if folders:
        refused = _folder_decision(phase, folders, str(hook_input.get("cwd") or ""), root,
                                   tracked_only=tracked_only_removal(command), defaults=defaults)
        if refused is None or _allows(refused):
            return True, refused  # a generated folder, one wholly inside the phase's paths, or a tracked-only git rm -r
    if refused is None and tool_name in FILE_MUTATION_TOOLS:
        facts = hook_input.get(FACTS_KEY) if isinstance(hook_input.get(FACTS_KEY), dict) else {}
        refused = _path_decision(phase, tool_input, str(hook_input.get("cwd") or ""), root, facts, defaults)
    return refused is not None, refused


def _capability_in_run(run: WorkflowRun, phase: dict[str, Any], root: str | None, hook_input: dict[str, Any],
                       exec_config: dict[str, Any], defaults: dict[str, Any] | None) -> ToolDecision | None:
    """The phase's capability class decides the call (its hint names the run, not plan mode)."""
    capability = EffectiveCapability(phase["capability_class"], run.workflow_key, None, root)
    decided = capability_decision(capability, hook_input, exec_config, defaults)
    if decided is not None and decided.decision == DECISION_DENY and decided.message.endswith(CONFIRM_HINT):
        # The capability's hint ("leave plan mode, or start a workflow") is wrong inside a run.
        from dataclasses import replace

        base = decided.message.removesuffix(CONFIRM_HINT).strip()
        return replace(decided, message=run_text("block.capability_in_run", detail=base, phase=phase["title"]))
    return decided


def run_tool_decision(
    run: WorkflowRun, contract: dict[str, Any], session: Session, hook_input: dict[str, Any], *,
    exec_config: dict[str, Any], hosts: frozenset[str], test_prefixes: tuple[tuple[str, ...], ...],
    defaults: dict[str, Any] | None = None,
) -> ToolDecision | None:
    """The denial of one PreToolUse of a run-bound session; ``None`` means no objection. With the Workspace's
    ``defaults`` (``device_runs.tool_defaults``), a call only a default admits is an allow carrying
    ``allowed_by_default`` (the caller logs it), and a denial a setting decides carries its one-click remedy."""
    from .contract import contract_summary

    tool_name = str(hook_input.get("tool_name") or "")
    tool_input = hook_input.get("tool_input") if isinstance(hook_input.get("tool_input"), dict) else {}
    command = str(tool_input.get("command") or "") if tool_name in SHELL_TOOLS else ""
    phase = contract.get("phase")
    if command:
        refused = _command_refusal(command, hook_input, session, exec_config=exec_config, hosts=hosts)
        if refused is not None:
            return refused
    if run.status != STATUS_RUNNING or phase is None:
        if not _mutates(tool_name, command, exec_config):
            return None
        reason = REASON_RUN_PAUSED if run.status == STATUS_PAUSED else REASON_RUN_WAITING
        return _deny(reason, run_text("block.run_not_running", run_state=contract_summary(contract)))
    refused = _agent_tools_deny(phase, tool_name)
    if refused is not None:
        return refused
    if tool_name in WEB_TOOLS:
        return web_tool_decision(phase, defaults)
    if tool_name in READ_TOOLS or tool_name.startswith(PLATFORM_MCP_TOOL_PREFIX):
        return None
    if is_browser_tool(tool_name):
        return browser_tool_decision(tool_name, tool_input, defaults)  # loopback, and public pages by default
    environment = dict(contract.get("preparation") or {}).get("environment")
    refused = _tool_decision(phase, tool_name, command, test_prefixes, declared_commands(environment), exec_config,
                             defaults, str(dict(environment or {}).get("app_folder") or ""))
    if _allows(refused):
        return _allowed_with_folders(phase, tool_name, command, hook_input, session, refused, defaults)
    root = bound_root(session)
    decided, refused = _phase_refusal(phase, tool_name, tool_input, command, hook_input, root, refused, defaults)
    if decided:
        return refused
    if tool_name in FILE_MUTATION_TOOLS and free_shell(phase) and claude_scratch(tool_input):
        return None  # Claude Code's own temp folder: the free shell writes there anyway
    return _capability_in_run(run, phase, root, hook_input, exec_config, defaults)


# Web search and fetch of both engines (Claude Code's WebSearch / WebFetch, Codex's web.run and its apps search).
# in every phase by default (Codex's search was refused three times); ``tool_defaults.web_tools``
# narrows it to the research phases (``device_runs.research_phases``) or switches it off.
WEB_TOOLS = frozenset({"WebSearch", "WebFetch", *CODEX_SEARCH_TOOLS})


def web_tool_decision(phase: dict[str, Any], defaults: dict[str, Any] | None) -> ToolDecision | None:
    mode = (defaults or {}).get("web_tools", "all")
    if phase.get("research") and mode != "off":
        return None
    if mode == "all":
        return allowed_by_default("web_tools") if defaults is not None else None
    if mode == "research_only":
        return _with_remedy(_deny(REASON_OUTSIDE_PHASE_TOOLS, run_text("block.web_research_only",
                                                                       phase=phase["title"])),
                            "web_tools", "all", defaults)
    return _with_remedy(_deny(REASON_OUTSIDE_PHASE_TOOLS, run_text("block.web_off")), "web_tools", "all", defaults)


# Claude Code's own temporary folder (``/tmp/claude-<uid>/``, where its sandbox points ``TMPDIR``). Without it,
# three Writes of scratch files there (a shared contract for the subagents, a data
# script) were refused as outside the repository, although the same session's free shell writes there; each cost a
# retry through a heredoc.
# Some Claude Code versions (2.1.318) set the sandbox ``TMPDIR`` to ``/tmp/claude/``,
# without the uid, and a Write of a scratch check script there was refused the same way.
_CLAUDE_SCRATCH = re.compile(r"^(?:/private)?/tmp/claude(?:-\d+)?/(?!(?:.*/)?\.\.(?:/|$))")


def claude_scratch(tool_input: dict[str, Any]) -> bool:
    path = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
    return bool(_CLAUDE_SCRATCH.match(path))


__all__ = ["CODEX_SEARCH_TOOLS", "WEB_TOOLS", "claude_scratch", "run_tool_decision", "web_tool_decision"]
