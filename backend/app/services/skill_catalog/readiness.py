"""Readiness of an assigned skill in a Workspace: read-only, never a grant."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Project
from ...models.agent.skill_catalog import SKILL_KIND_MCP_SERVER
from ..agent_gateway.policy import resolve_policy_from_config
from ..agent_gateway.tool_check import evaluate_tool_check
from ..mcp_access_policy import mcp_server_access_decision
from ..tool_access_policy import tool_project_policy_decision
from .effective import Candidate
from .extension import SURFACE_OCTRYX_CLAUDE, SURFACE_PLATFORM_CHAT, normalize_extension

_PATTERN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)(?:\((.*)\))?$")
_PATH_TOOLS = {"Read", "Edit", "Write", "MultiEdit", "NotebookEdit", "Glob", "Grep"}


def synthetic_hook_input(pattern: str) -> dict[str, Any] | None:
    match = _PATTERN.match(str(pattern or "").strip())
    if match is None:
        return None
    tool, argument = match.group(1), (match.group(2) or "").strip()
    tool_input: dict[str, Any] = {}
    if tool == "Bash" and argument:
        tool_input["command"] = argument
    elif tool in _PATH_TOOLS and argument:
        tool_input["file_path"] = argument.removeprefix("//") if argument.startswith("//") else argument
    return {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input, "cwd": "/workspace"}


def _chat(extension: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    refusals = []
    for tool in extension["tools"][SURFACE_PLATFORM_CHAT]["required"]:
        decision = tool_project_policy_decision(tool, config)
        if not decision.allowed:
            refusals.append({"tool": tool, "policy": decision.policy, "reason": decision.reason,
                             "rule": decision.matched_rule})
    return refusals


def _claude(extension: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    load = resolve_policy_from_config(config)
    refusals = []
    for pattern in extension["tools"][SURFACE_OCTRYX_CLAUDE]["required"]:
        hook_input = synthetic_hook_input(pattern)
        if hook_input is None:
            refusals.append({"tool": pattern, "policy": "pattern", "reason": "pattern_unreadable", "rule": None})
            continue
        if load.policy is None:
            refusals.append({"tool": pattern, "policy": "agent_gateway_policy", "reason": load.reason or load.source,
                             "rule": None})
            continue
        if pattern in load.policy.deny_permissions:
            refusals.append({"tool": pattern, "policy": "permissions.deny", "reason": "denied_permission",
                             "rule": pattern})
            continue
        decision = evaluate_tool_check(load.policy, hook_input)
        if decision.decision != "allow":
            refusals.append({"tool": pattern, "policy": "tool_rules", "reason": decision.reason,
                             "rule": decision.rule_id})
    return refusals


def readiness(candidate: Candidate, project: Project | None, surface: str) -> dict[str, Any]:
    config = dict(project.config or {}) if project is not None else {}
    if candidate.skill.kind == SKILL_KIND_MCP_SERVER:
        decision = mcp_server_access_decision(candidate.skill.name, config)
        return {"state": "ready" if decision.allowed else "needs_mcp_policy", "refusals": [] if decision.allowed else [
            {"tool": candidate.skill.name, "policy": "mcp_policy", "reason": decision.reason, "rule": None}]}
    extension = normalize_extension(candidate.version.extension)
    refusals = _chat(extension, config) if surface == SURFACE_PLATFORM_CHAT else _claude(extension, config)
    return {"state": "restricted" if refusals else "ready", "refusals": refusals}


async def project_of(db: AsyncSession, project_id: str | None) -> Project | None:
    return await db.get(Project, project_id) if project_id else None


__all__ = ["project_of", "readiness", "synthetic_hook_input"]
