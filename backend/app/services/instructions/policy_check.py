"""The "forbidden by Policy" finding of an instruction: deterministic, no model.

For every registered tool the instruction's body names (exact name, connector tools included; ``conflicts.named_tools``)
the effective policy of the instruction's scope decides whether the agent could ever call it:

- the **tool policy deny lists**: the effective project configuration (platform tool configs merged with the
  Workspace's ``tool_policy`` / ``blocked_tools`` / deny patterns, ``tool_access_policy``); for a global instruction
  only the platform part;
- **Cedar**: the published policy set (baseline + custom policies) for the tool-call action, asked as the test bench
  asks it (``points.tool_query``) for representative principals: a synthetic member without platform roles (the
  lowest role) and, for a Workspace, one principal per distinct role/group set of its members (for a global
  instruction, one per platform role). The tool is forbidden only when Cedar denies **every** one of them.

The approval policy is not a source: it only decides which calls need a person's approval (``require_for_tools``),
it never forbids one, and it has no block list.

Each forbidden tool yields one ``tool_forbidden_by_policy`` finding naming the tool and the policy that forbids it
(the deny rule, or the deciding Cedar policy id and its text). Like every finding it blocks submit and publish
until the submitter accepts it.
"""

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
    """The representative principals: no roles first (the lowest), then the scope's distinct role/group sets."""
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
    """The deciding Cedar policy when every representative principal is denied the tool; ``None`` otherwise."""
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
    """One finding per named tool the scope's effective policy forbids (see the module docstring)."""
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
