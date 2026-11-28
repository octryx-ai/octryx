"""The PreToolUse decision of an octryx-claude session bound to a workflow run."""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from app.services.agent_gateway.capability_session import EffectiveCapability
from app.tools.capability_requirements import CAPABILITY_READ_ONLY

from ....models import Session, WorkflowRun
from ...agent_gateway.capability import (
    CONFIRM_HINT,
    FILE_MUTATION_TOOLS,
    PLATFORM_MCP_TOOL_PREFIX,
    READ_TOOLS,
    SHELL_TOOLS,
    bound_root,
    capability_decision,
    unknown_tool_decision,
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

# Codex's web search as its hooks name it: the standalone ``web.run`` and the ChatGPT apps search tool.
CODEX_SEARCH_TOOLS = frozenset({"webrun", "web.run", "web__run", "mcp__codex_apps__search_service__web_run"})


def _command_refusal(command: str, hook_input: dict[str, Any], session: Session, *, exec_config: dict[str, Any],
                     hosts: frozenset[str]) -> ToolDecision | None:
    refused = _bash_run_rules(command, hosts=hosts)
    if refused is not None:
        return refused
    role_denied = role_command_denial(command, exec_config)
    if role_denied is not None:
        return _deny(REASON_ROLE_COMMAND, role_denied)
    return _hard_core(command, str(hook_input.get("cwd") or ""), bound_root(session))


def _allowed_with_folders(phase: dict[str, Any], tool_name: str, command: str, hook_input: dict[str, Any],
                          session: Session, allowed: ToolDecision, defaults: dict[str, Any] | None) -> ToolDecision:
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
    removed = removal_paths(command) if refused is not None and tool_name in SHELL_TOOLS else None
    if removed:
        refused = _removal_decision(phase, removed, str(hook_input.get("cwd") or ""), root)
        if refused is None:
            return True, None
    folders = recursive_removal_paths(command) if refused is not None and tool_name in SHELL_TOOLS else None
    if folders:
        refused = _folder_decision(phase, folders, str(hook_input.get("cwd") or ""), root,
                                   tracked_only=tracked_only_removal(command), defaults=defaults)
        if refused is None or _allows(refused):
            return True, refused
    if refused is None and tool_name in FILE_MUTATION_TOOLS:
        facts = hook_input.get(FACTS_KEY) if isinstance(hook_input.get(FACTS_KEY), dict) else {}
        refused = _path_decision(phase, tool_input, str(hook_input.get("cwd") or ""), root, facts, defaults)
    return refused is not None, refused


def _unknown_tool_defaults(phase: dict[str, Any] | None,
                           defaults: dict[str, Any] | None) -> dict[str, Any] | None:
    # Read-only is an explicit restriction: like a read-only session, it refuses unknown tools whatever the defaults.
    if phase is not None and phase.get("capability_class") == CAPABILITY_READ_ONLY:
        return None
    return defaults


def _in_run(decided: ToolDecision | None, phase: dict[str, Any] | None) -> ToolDecision | None:
    hint = f" {CONFIRM_HINT}"
    if decided is None or decided.decision != DECISION_DENY or hint not in decided.message:
        return decided
    # The capability's hint ("leave plan mode, or start a workflow") is wrong inside a run.
    detail = decided.message.replace(hint, "", 1)
    if phase is None:
        return replace(decided, message=detail)
    return replace(decided, message=run_text("block.capability_in_run", detail=detail, phase=phase["title"]))


def _classified_while_idle(tool_name: str) -> bool:
    return tool_name in READ_TOOLS or tool_name in SHELL_TOOLS or tool_name.startswith(PLATFORM_MCP_TOOL_PREFIX)


def _outward_while_idle(tool_name: str, tool_input: dict[str, Any], phase: dict[str, Any] | None,
                        defaults: dict[str, Any] | None) -> ToolDecision | None:
    # Web and browser tools reach outside the machine: a paused run keeps its phase's limits on them.
    if phase is None:
        return _in_run(unknown_tool_decision(tool_name, defaults), phase)
    if tool_name in WEB_TOOLS:
        return web_tool_decision(phase, defaults)
    return browser_tool_decision(tool_name, tool_input, defaults)


def _capability_in_run(run: WorkflowRun, phase: dict[str, Any], root: str | None, hook_input: dict[str, Any],
                       exec_config: dict[str, Any], defaults: dict[str, Any] | None) -> ToolDecision | None:
    capability = EffectiveCapability(phase["capability_class"], run.workflow_key, None, root)
    decided = capability_decision(capability, hook_input, exec_config, _unknown_tool_defaults(phase, defaults))
    return _in_run(decided, phase)


def run_tool_decision(
    run: WorkflowRun, contract: dict[str, Any], session: Session, hook_input: dict[str, Any], *,
    exec_config: dict[str, Any], hosts: frozenset[str], test_prefixes: tuple[tuple[str, ...], ...],
    defaults: dict[str, Any] | None = None,
) -> ToolDecision | None:
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
        if _mutates(tool_name, command, exec_config):
            reason = REASON_RUN_PAUSED if run.status == STATUS_PAUSED else REASON_RUN_WAITING
            return _deny(reason, run_text("block.run_not_running", run_state=contract_summary(contract)))
        if tool_name in WEB_TOOLS or is_browser_tool(tool_name):
            return _outward_while_idle(tool_name, tool_input, phase, _unknown_tool_defaults(phase, defaults))
        if _classified_while_idle(tool_name):
            return None
        return _in_run(unknown_tool_decision(tool_name, _unknown_tool_defaults(phase, defaults)), phase)
    refused = _agent_tools_deny(phase, tool_name)
    if refused is not None:
        return refused
    if tool_name in WEB_TOOLS:
        return web_tool_decision(phase, defaults)
    if tool_name in READ_TOOLS or tool_name.startswith(PLATFORM_MCP_TOOL_PREFIX):
        return None
    if is_browser_tool(tool_name):
        return browser_tool_decision(tool_name, tool_input, defaults)
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


# Web search and fetch of both engines are allowed in every phase by default; ``tool_defaults.web_tools`` narrows them.
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


# Claude Code's own temporary folder, where its sandbox points TMPDIR (with or without the uid, by version); the free
# shell writes there anyway.
_CLAUDE_SCRATCH = re.compile(r"^(?:/private)?/tmp/claude(?:-\d+)?/(?!(?:.*/)?\.\.(?:/|$))")


def claude_scratch(tool_input: dict[str, Any]) -> bool:
    path = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
    return bool(_CLAUDE_SCRATCH.match(path))


__all__ = ["CODEX_SEARCH_TOOLS", "WEB_TOOLS", "claude_scratch", "run_tool_decision", "web_tool_decision"]
