"""The built-in Coding agent row and the lookup of built-in agents by ``builtin_key``.

The platform agents (``services/platform_agents``: Assistant, Engineer, Reviewer) are the platform's built-ins.
The boot does not create the Coding agent: :func:`ensure_builtin_agents` creates it once (``builtin_key =
"coding"``, an explicit ``coding_delivery`` execution mode), and the test fixtures call it. An existing row
is kept as is. :func:`builtin_agent` finds a built-in row by its key.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AgentDefinition, AgentStep, User
from .agent_builtin_definitions import CODING_AGENT_DEFINITION
from .agent_definition_authoring import governs_agent_definition_write
from .agent_definition_payload import CODING_DELIVERY_EXECUTION_MODE
from .agent_definition_writers import AgentDefinitionWriter

BUILTIN_CODING = "coding"
CODING_AGENT_NAME = "Coding agent"
CODING_AGENT_DEFAULT_WORKFLOW = "coding-change-tdd"



async def builtin_agent(db: AsyncSession, key: str) -> AgentDefinition | None:
    return (await db.execute(select(AgentDefinition).where(AgentDefinition.builtin_key == key))).scalar_one_or_none()


@governs_agent_definition_write(AgentDefinitionWriter.BOOTSTRAP_BUILTIN_AGENTS, actor_param="admin_user")
async def ensure_builtin_agents(db: AsyncSession, *, admin_user: User) -> AgentDefinition:
    """Create the built-in Coding agent once; an existing row (admin-edited included) is kept as is."""
    existing = await builtin_agent(db, BUILTIN_CODING)
    if existing is not None:
        return existing
    definition = CODING_AGENT_DEFINITION
    agent = AgentDefinition(
        id=str(uuid.uuid4()),
        owner_id=admin_user.id,
        project_id=None,
        builtin_key=BUILTIN_CODING,
        name=CODING_AGENT_NAME,
        description=str(definition["description"]),
        goal=str(definition["goal"]),
        agent_type=str(definition["agent_type"]),
        thinking_level=str(definition["thinking_level"]),
        branch_prefix=str(definition.get("branch_prefix") or "octryx"),
        require_self_review=bool(definition.get("require_self_review")),
        system_prompt=str(definition["system_prompt"]),
        output_prompt=str(definition["output_prompt"]),
        capability_ceiling="deliver",
        default_workflow_key=CODING_AGENT_DEFAULT_WORKFLOW,
        execution_mode=CODING_DELIVERY_EXECUTION_MODE,
        is_active=True,
    )
    db.add(agent)
    await db.flush()
    for index, step in enumerate(definition["steps"], start=1):
        db.add(AgentStep(
            id=str(uuid.uuid4()), agent_id=agent.id, position=index, name=step["name"], step_type=step["step_type"],
            instructions=step["instructions"], success_criteria=step["success_criteria"],
            allowed_tools=step.get("allowed_tools") or [], step_config=step.get("step_config") or {}, is_enabled=True,
        ))
    await db.flush()
    return agent


__all__ = [
    "BUILTIN_CODING",
    "CODING_AGENT_DEFAULT_WORKFLOW",
    "CODING_AGENT_NAME",
        "builtin_agent",
    "ensure_builtin_agents",
]
