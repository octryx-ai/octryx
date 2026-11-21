"""Effective setup for an octryx-claude session (Claude Code over MCP).

Claude Code keeps its own system prompt and loop. What Octryx contributes is
read from the same functions the MCP surface and the hooks use: the server instructions
(prompt catalog, Workspace scope), the workflow selection, the skill manifest filter (surface
``octryx_claude``) and the capability gate rules.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..mcp_knowledge_instructions import INSTRUCTIONS_KEY
from ..mcp_workflow_tools import MCP_EVIDENCE_TOOLS
from ..prompt_catalog import resolve_prompt_set
from ..skill_catalog.effective import candidates
from ..skill_catalog.extension import SURFACE_OCTRYX_CLAUDE
from ..workflow_routing.explicit_selection import resolve_explicit_workflow_selection
from .chat_setup import APPROVALS_TAB, PROMPT_TEXTS_TAB, SKILLS_TAB, TOOLS_TAB
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

RUNTIME_OCTRYX_CLAUDE = "octryx_claude"
# Claude Code's native tools the PreToolUse hook classifies (agent_gateway/capability.py).
NATIVE_GATED_TOOLS = ("Read", "Glob", "Grep", "Edit", "Write", "MultiEdit", "NotebookEdit", "Bash")


async def _instructions_text_part(db: AsyncSession, *, project_id: str | None) -> SetupPart:
    prompt_set = await resolve_prompt_set(db, workspace_id=project_id or None)
    prompt = prompt_set.resolved(INSTRUCTIONS_KEY)
    return SetupPart(
        id=PART_SYSTEM_TEXTS,
        title="Launcher rules + MCP instructions",
        source_label="Prompt catalog · octryx-claude launcher",
        source_tab=PROMPT_TEXTS_TAB,
        version=prompt.ref,
        tokens=tokens_of(prompt.body),
        details={
            "keys": [{"key": prompt.key, "ref": prompt.ref, "source": prompt.source,
                      "overridden": prompt.source != "seed"}],
            "note": "Claude Code keeps its own system prompt; Octryx adds the launcher rules and the "
            "MCP server instructions.",
        },
    )


async def _workflow_resolution(db: AsyncSession, *, project_id: str | None, clean_key: str) -> dict[str, Any]:
    """The explicit selection of ``clean_key`` (none for no workflow)."""
    if not clean_key or clean_key == "none":
        return {}
    return await resolve_explicit_workflow_selection(db, workflow_key=clean_key, project_id=project_id)


def _skills_part(rows: list[Any]) -> SetupPart:
    return SetupPart(
        id=PART_SKILLS,
        title="Skills",
        source_label="Skills · delivered as files to the session config directory",
        source_tab=SKILLS_TAB,
        version=f"{sum(1 for row in rows if row.delivered)} delivered",
        details={"items": [
            {"name": row.skill.name, "version": row.version.version, "delivered": row.delivered, "reason": row.reason,
             "assigned_by": row.assigned_by}
            for row in rows
        ]},
    )


def _tools_and_approvals_parts(capability: str) -> list[SetupPart]:
    return [
        SetupPart(
            id=PART_TOOLS,
            title="Tools offered / forbidden",
            source_label="PreToolUse → tool-check (capability class)",
            source_tab=TOOLS_TAB,
            details={
                "offered": sorted(MCP_EVIDENCE_TOOLS),
                "native_gated": list(NATIVE_GATED_TOOLS),
                "forbidden": [],
            },
        ),
        SetupPart(
            id=PART_APPROVALS,
            title="Approvals",
            source_label="Workflow confirmation · Approval rule",
            source_tab=APPROVALS_TAB,
            details={"required": [] if capability == "read_only" else [
                {"tool": "workflow_select", "reason": f"The user confirms the {capability} workflow first.",
                 "rule": "workflow_confirmation"}
            ]},
        ),
    ]


async def external_effective_setup(
    db: AsyncSession, *, project_id: str | None, workflow_key: str = "", user_roles: list[str] | None = None
) -> dict[str, Any]:
    clean_key = str(workflow_key or "").strip()
    resolution = await _workflow_resolution(db, project_id=project_id, clean_key=clean_key)
    workflow = await workflow_part(db, resolution=resolution, run_capability=None)
    declared = str(workflow.details.get("declared_class") or "read_only") if workflow.details.get("selected") else ""
    capability = declared or "read_only"
    rows = await candidates(db, project_id=project_id, surface=SURFACE_OCTRYX_CLAUDE, user_roles=user_roles)
    skills = _skills_part(rows)
    parts = [
        await _instructions_text_part(db, project_id=project_id),
        SetupPart(id=PART_AGENT, title="Agent instructions", source_label="Claude Code (no platform agent)",
                  enforced="guidance", details={"selected": False}),
        SetupPart(id=PART_INSTRUCTIONS, title="Instructions", source_label="Not delivered to octryx-claude",
                  enforced="guidance", details={"items": []}),
        workflow,
        skills,
        *_tools_and_approvals_parts(capability),
    ]
    return {
        "runtime": RUNTIME_OCTRYX_CLAUDE,
        "summary": {
            "capability": {"class": capability, "source": "confirmed_workflow" if declared else "default_read_only"},
            "workflow_key": workflow.details.get("key") or "",
            "profile_status": str(resolution.get("status") or ""),
            "profile_reason": str(resolution.get("unmatched_reason") or ""),
            "parts": len(parts),
        },
        "parts": [part.as_dict() for part in parts],
        "budget": budget(parts, limit=0),
        "prompt_refs": {item["key"]: {"ref": item["ref"], "source": item["source"], "digest": ""}
                        for item in parts[0].details["keys"]},
    }


__all__ = ["RUNTIME_OCTRYX_CLAUDE", "external_effective_setup"]
