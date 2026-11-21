"""The conflict check of an instruction version: deterministic, no model, run at submit.

Closed findings, each with the names that triggered it:

- ``unknown_workflow``: the bound key names no published phased workflow;
- ``tool_not_in_workflow``: the body names a platform tool the bound workflow does not offer;
- ``tool_against_capability``: the body names a changing tool while the bound workflow (or, for an
  agent instruction, the agent's ceiling) is read-only;
- ``duplicates_skill``: the title equals a published skill's name, or the body overlaps a published
  skill body by more than 80 % (word 5-shingles);
- ``over_budget``: the layer's published instructions plus this one exceed the layer budget;
- ``tool_forbidden_by_policy``: the scope's effective policy (tool policy deny lists, Cedar) forbids a named tool,
  with the forbidding policy (``policy_check``).

Tool names are matched as whole words against the platform's tool definitions; nothing interprets
the text. A finding blocks publish until the submitter accepts it (``lifecycle.submit_for_review``).
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AgentDefinition, Skill, SkillVersion
from ...models.runtime.instruction import INSTRUCTION_SCOPE_WORKSPACE, Instruction, InstructionVersion
from .contract import LAYER_BUDGETS, layer_of, token_estimate
from .policy_check import forbidden_tool_findings

SHINGLE_SIZE = 5
OVERLAP_LIMIT = 0.8
_WORD = re.compile(r"[A-Za-z0-9_]+")


def _words(text: str) -> list[str]:
    return [word.lower() for word in _WORD.findall(str(text or ""))]


def _shingles(text: str) -> set[tuple[str, ...]]:
    words = _words(text)
    return {tuple(words[index:index + SHINGLE_SIZE]) for index in range(max(0, len(words) - SHINGLE_SIZE + 1))}


def overlap(body: str, other: str) -> float:
    mine, theirs = _shingles(body), _shingles(other)
    return len(mine & theirs) / len(mine) if mine and theirs else 0.0


def named_tools(body: str) -> list[str]:
    from ...tools.definitions import get_all_definitions

    known = set(get_all_definitions())
    return sorted({word for word in _WORD.findall(str(body or "")) if word in known})


def _phase_tools(config: dict[str, Any]) -> set[str]:
    """Every tool one phase names: its tool allowlist, its contract's allowed tools and its step tools."""
    from ..workflow_checks.steps import workflow_steps
    from ..workflow_routing.tool_policy import normalized_tool_policy

    contract = dict(config.get("workflow_contract") or {})
    return {
        *normalized_tool_policy(dict(config.get("tool_policy") or {}))["allowlist"],
        *(str(name) for name in contract.get("allowed_tools") or [] if str(name or "").strip()),
        *(step["tool"] for step in workflow_steps(contract)),
    }


async def _workflow(db: AsyncSession, key: str, project_id: str | None) -> dict[str, Any] | None:
    """The tools and highest class of the published phased workflow ``key``, or ``None``."""
    from ..run_admission.phased_catalog import highest_class
    from ..workflow_runs.engine import published_phased_flow

    found = await published_phased_flow(db, key, project_id)
    if found is None:
        return None
    definition = dict(found[1].definition_json or {})
    tools: set[str] = set()
    for node in definition.get("nodes") or []:
        if isinstance(node, dict) and node.get("type") == "phase":
            tools |= _phase_tools(dict(node.get("config") or {}))
    return {"tools": tools, "capability_class": highest_class(definition)}


def _finding(code: str, names: list[str] | None = None, **facts: object) -> dict[str, Any]:
    return {"code": code, "names": list(names or []), **facts}


async def check_conflicts(db: AsyncSession, instruction: Instruction, body: str) -> list[dict[str, Any]]:
    from ..safety_gate import MUTATING_TOOL_NAMES

    findings: list[dict[str, Any]] = []
    tools = named_tools(body)
    read_only = False
    if instruction.workflow_key:
        project_id = instruction.scope_id if instruction.scope_type == INSTRUCTION_SCOPE_WORKSPACE else None
        workflow = await _workflow(db, instruction.workflow_key, project_id)
        if workflow is None:
            findings.append(_finding("unknown_workflow", [instruction.workflow_key]))
        else:
            outside = [name for name in tools if name not in workflow["tools"]]
            if outside:
                findings.append(_finding("tool_not_in_workflow", outside))
            read_only = workflow["capability_class"] == "read_only"
    if instruction.scope_type == "agent" and instruction.scope_id:
        agent = await db.get(AgentDefinition, instruction.scope_id)
        read_only = read_only or str(getattr(agent, "capability_ceiling", "") or "") == "read_only"
    changing = [name for name in tools if name in MUTATING_TOOL_NAMES]
    if read_only and changing:
        findings.append(_finding("tool_against_capability", changing))
    skills = (await db.execute(
        select(Skill.name, SkillVersion.body).join(SkillVersion, SkillVersion.id == Skill.published_version_id))).all()
    title = str(instruction.title or "").strip().lower()
    duplicates = [
        str(name) for name, content in skills
        if (title and str(name or "").strip().lower() == title) or overlap(body, str(content or "")) > OVERLAP_LIMIT
    ]
    if duplicates:
        findings.append(_finding("duplicates_skill", sorted(duplicates)))
    findings.extend(await _budget(db, instruction, body))
    # The tools the scope's effective policy forbids (deny lists and Cedar; ``policy_check``).
    findings.extend(await forbidden_tool_findings(db, instruction, tools))
    return findings


async def _budget(db: AsyncSession, instruction: Instruction, body: str) -> list[dict[str, Any]]:
    layer = layer_of(instruction)
    siblings = (
        await db.execute(
            select(Instruction, InstructionVersion)
            .join(InstructionVersion, InstructionVersion.instruction_id == Instruction.id)
            .where(
                InstructionVersion.state == "published",
                Instruction.id != instruction.id,
                Instruction.status == "active",
                Instruction.scope_type == instruction.scope_type,
                Instruction.scope_id.is_(None) if instruction.scope_id is None
                else Instruction.scope_id == instruction.scope_id,
            )
        )
    ).all()
    used = sum(
        int(version.token_estimate or 0) for item, version in siblings
        if layer_of(item) == layer and item.workflow_key == instruction.workflow_key
    )
    total = used + token_estimate(body)
    if total <= LAYER_BUDGETS[layer]:
        return []
    return [_finding("over_budget", [layer], tokens=total, budget=LAYER_BUDGETS[layer])]


__all__ = ["OVERLAP_LIMIT", "check_conflicts", "named_tools", "overlap"]
