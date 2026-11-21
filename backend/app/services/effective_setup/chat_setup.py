"""Effective setup for a platform-chat turn: the dry run, read back as ordered parts."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..prompt_catalog.prompt_set import SOURCE_SEED
from ..skill_catalog.effective import candidates
from ..skill_catalog.extension import SURFACE_PLATFORM_CHAT
from ..tool_access_policy import explain_tool_project_policy_denial
from ..tool_approval_rules import tool_approval_requirement
from .dry_run import SetupDryRun, dry_run_setup
from .parts import (
    PART_AGENT,
    PART_APPROVALS,
    PART_INSTRUCTIONS,
    PART_SKILLS,
    PART_SYSTEM_TEXTS,
    PART_TOOLS,
    SetupPart,
    budget,
    tokens_of,
)
from .workflow_part import workflow_part

RUNTIME_CHAT = "chat"
PROMPT_TEXTS_TAB = "promptCatalog"
AGENTS_TAB = "agents"
INSTRUCTIONS_TAB = "instructions"
SKILLS_TAB = "skills"
TOOLS_TAB = "toolCatalog"
APPROVALS_TAB = "policies"


def _system_texts_part(run: SetupDryRun, *, other_tokens: int) -> SetupPart:
    used = (run.prompt_record.get("used") or {}) if isinstance(run.prompt_record, dict) else {}
    keys = [
        {
            "key": key,
            "ref": entry.get("ref"),
            "source": entry.get("source"),
            "overridden": entry.get("source") != SOURCE_SEED,
        }
        for key, entry in sorted(used.items())
        if isinstance(entry, dict)
    ]
    overridden = sum(1 for item in keys if item["overridden"])
    return SetupPart(
        id=PART_SYSTEM_TEXTS,
        title="System prompt texts",
        source_label="Settings → System prompt texts",
        source_tab=PROMPT_TEXTS_TAB,
        version=f"{len(keys)} keys · {overridden} overridden",
        tokens=max(tokens_of(run.system_prompt) - other_tokens, 0),
        details={"keys": keys, "scope": dict(run.prompt_record.get("scope") or {})},
    )


def _agent_part(run: SetupDryRun) -> SetupPart:
    resolution = run.agent_resolution
    definition = run.agent_definition or {}
    if resolution is None:
        return SetupPart(
            id=PART_AGENT, title="Agent instructions", source_label="No agent selected", source_tab=AGENTS_TAB,
            details={"selected": False, "agent_type": run.agent_type},
        )
    text = "\n\n".join(str(definition.get(name) or "") for name in ("systemPrompt", "goal", "outputPrompt"))
    return SetupPart(
        id=PART_AGENT,
        title="Agent instructions",
        source_label=f"Agents → {definition.get('name') or resolution.definition_id}",
        source_tab=AGENTS_TAB,
        version=f"r{resolution.revision_number}" if resolution.revision_number else resolution.source or "",
        tokens=tokens_of(text),
        details={
            "selected": True,
            "id": resolution.definition_id,
            "name": definition.get("name") or "",
            "status": resolution.status,
            "mode": resolution.mode,
            "agent_type": definition.get("agentType") or "",
            "instructions": str(definition.get("systemPrompt") or "")[:2000],
        },
    )


def _instructions_part(run: SetupDryRun) -> SetupPart:
    items = [item for item in run.instructions if isinstance(item, dict)]
    return SetupPart(
        id=PART_INSTRUCTIONS,
        title="Instructions",
        source_label=f"{len(items)} bound · agent → Workspace → workflow",
        source_tab=INSTRUCTIONS_TAB,
        enforced="guidance",
        tokens=sum(int(item.get("token_estimate") or 0) for item in items),
        details={
            "items": [
                {"key": item.get("key"), "version": item.get("version"), "layer": item.get("layer")} for item in items
            ],
        },
    )


async def _skills_part(db: AsyncSession, run: SetupDryRun, *, project_id: str | None) -> SetupPart:
    rows = await candidates(db, project_id=project_id, surface=SURFACE_PLATFORM_CHAT,
                            agent_definition=run.agent_definition)
    items = [
        {
            "name": row.skill.name,
            "version": row.version.version,
            "delivered": row.delivered,
            "reason": row.reason,
            "assigned_by": row.assigned_by,
        }
        for row in rows
    ]
    return SetupPart(
        id=PART_SKILLS,
        title="Skills",
        source_label="Skills · Workspace assignment, narrowed by agent",
        source_tab=SKILLS_TAB,
        version=f"{sum(1 for item in items if item['delivered'])} available",
        tokens=tokens_of(run.skills_prompt),
        details={"items": items, "delivery": "Loaded on demand with skill_search / skill_get."},
    )


def _tools_part(run: SetupDryRun) -> SetupPart:
    offered = set(run.offered_tools)
    candidates_named = set(run.tool_allowlist or []) | set(run.blocked_tools)
    forbidden = []
    for name in sorted(candidates_named - offered):
        reason = explain_tool_project_policy_denial(name, run.project_config)
        if name in run.blocked_tools:
            reason = reason or "Blocked for this turn."
        forbidden.append({"tool": name, "reason": reason or "Not available in this setup (connector, role or class)."})
    return SetupPart(
        id=PART_TOOLS,
        title="Tools offered / forbidden",
        source_label=f"Surface: {run.tool_surface.get('source') or 'none'}",
        source_tab=TOOLS_TAB,
        version=str(run.tool_surface.get("set") or ""),
        details={"offered": run.offered_tools, "forbidden": forbidden, "surface": run.tool_surface},
    )


def _approvals_part(run: SetupDryRun) -> SetupPart:
    required = []
    for name in run.offered_tools:
        requirement = tool_approval_requirement(name, run.project_config)
        if requirement.required:
            required.append({"tool": name, "reason": requirement.reason, "rule": requirement.matched_rule})
    return SetupPart(
        id=PART_APPROVALS,
        title="Approvals",
        source_label="Tool & approval policies · Approval rule",
        source_tab=APPROVALS_TAB,
        details={"required": required},
    )


async def chat_effective_setup(
    db: AsyncSession, *, user_id: str, project_id: str | None, agent_id: str = "", workflow_key: str = ""
) -> dict[str, Any]:
    run = await dry_run_setup(db, user_id=user_id, project_id=project_id, agent_id=agent_id, workflow_key=workflow_key)
    agent = _agent_part(run)
    instructions = _instructions_part(run)
    workflow = await workflow_part(db, resolution=run.workflow_resolution, run_capability=run.run_capability)
    skills = await _skills_part(db, run, project_id=project_id)
    system_texts = _system_texts_part(run, other_tokens=agent.tokens + instructions.tokens + skills.tokens)
    parts = [system_texts, agent, instructions, workflow, skills, _tools_part(run), _approvals_part(run)]
    profile = run.execution_profile
    return {
        "runtime": RUNTIME_CHAT,
        "summary": {
            "capability": {
                "class": run.run_capability.get("class") or "",
                "source": run.run_capability.get("source") or "",
            },
            "workflow_key": workflow.details.get("key") or "",
            "profile_status": profile.get("status") or "",
            "profile_reason": profile.get("reason") or "",
            "parts": len(parts),
        },
        "parts": [part.as_dict() for part in parts],
        "budget": budget(parts, limit=run.token_budget),
        "prompt_refs": run.prompt_refs,
        "catalog_refs": run.catalog_refs,
    }


__all__ = ["RUNTIME_CHAT", "chat_effective_setup"]
