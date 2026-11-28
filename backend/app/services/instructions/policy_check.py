"""The "forbidden by Policy" finding of an instruction: deterministic, no model."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Role, UserProject
from ...models.runtime.instruction import INSTRUCTION_SCOPE_WORKSPACE, Instruction

FINDING_CODE = "tool_forbidden_by_policy"
SYNTHETIC_USER = "instruction-policy-check"
MAX_PRINCIPALS = 50
DENY_REASONS = frozenset({"denylist", "deny_patterns"})


def _deny_list_reason(tool: str, project_config: dict[str, Any]) -> dict[str, str] | None:
    from ..tool_access_policy import tool_project_policy_decision

    decision = tool_project_policy_decision(tool, project_config)
    if decision.allowed or decision.reason not in DENY_REASONS:
        return None
    rule = "deny list" if decision.reason == "denylist" else "deny pattern"
    return {"kind": "tool_policy", "policy": f"Tool policy {rule}", "detail": decision.error_message or ""}


async def _role_sets(db: AsyncSession, instruction: Instruction) -> list[tuple[tuple[str, ...], tuple[str, ...]]]:
    from ..policy_engine.principals import user_roles_and_groups

    sets: list[tuple[tuple[str, ...], tuple[str, ...]]] = [((), ())]
    if instruction.scope_type == INSTRUCTION_SCOPE_WORKSPACE and instruction.scope_id:
        members = (await db.execute(
            select(UserProject.user_id).where(UserProject.project_id == instruction.scope_id)
        )).scalars().all()
        for user_id in members:
            roles = await user_roles_and_groups(db, str(user_id))
            if roles not in sets:
                sets.append(roles)
    else:
        for name in (await db.execute(select(Role.name))).scalars().all():
            if ((str(name),), ()) not in sets:
                sets.append(((str(name),), ()))
    return sets[:MAX_PRINCIPALS]


async def _cedar_reason(
    tool: str, section: dict[str, Any], custom: str, role_sets: list[tuple[tuple[str, ...], tuple[str, ...]]],
) -> dict[str, str] | None:
    from ..policy_engine.engine import compile_policy_set, evaluate
    from ..policy_engine.entities import principal_entities
    from ..policy_engine.points import tool_query
    from ..policy_engine.test_bench import policy_source_text

    determining: tuple[str, ...] = ()
    text = ""
    for roles, groups in role_sets:
        principal = principal_entities(SYNTHETIC_USER, roles=roles, groups=groups,
                                       platform_admin="admin" in {role.lower() for role in roles})
        query = tool_query(tool, section, None, principal=principal)
        text = query.policies + ("\n" + custom if custom else "")
        evaluation = evaluate(compile_policy_set(text), query.requests, query.entities)
        if evaluation.allowed:
            return None
        determining = determining or evaluation.determining
    policy_id = determining[0] if determining else ""
    return {"kind": "cedar", "policy": f"Cedar policy {policy_id}".strip(),
            "detail": policy_source_text(text, policy_id) if policy_id else "denied for every role in scope"}


async def forbidden_tool_findings(db: AsyncSession, instruction: Instruction, tools: list[str]) -> list[dict[str, Any]]:
    if not tools:
        return []
    from ..classification_tool_policy import CLASSIFICATION_TOOL_POLICY_KEY
    from ..policy_engine.test_bench import SOURCE_PUBLISHED, custom_text
    from ..project.service import get_project_config

    workspace_id = instruction.scope_id if instruction.scope_type == INSTRUCTION_SCOPE_WORKSPACE else None
    project_config = await get_project_config(workspace_id, db)
    section = project_config.get(CLASSIFICATION_TOOL_POLICY_KEY) if workspace_id else None
    section = dict(section) if isinstance(section, dict) else {"level": None}
    custom = (await custom_text(db, SOURCE_PUBLISHED)).text
    role_sets = await _role_sets(db, instruction)
    findings = []
    for tool in tools:
        reason = _deny_list_reason(tool, project_config) or await _cedar_reason(tool, section, custom, role_sets)
        if reason is not None:
            findings.append({"code": FINDING_CODE, "names": [tool], **reason})
    return findings


__all__ = ["FINDING_CODE", "forbidden_tool_findings"]
