import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentStep

AgentStepSpec = tuple[str, str, str, str, list[str]]


async def sync_agent_steps(
    db: AsyncSession,
    *,
    agent_id: str,
    step_specs: list[AgentStepSpec],
    delete_extra_steps: bool,
) -> None:
    existing_steps = (
        (await db.execute(select(AgentStep).where(AgentStep.agent_id == agent_id).order_by(AgentStep.position.asc())))
        .scalars()
        .all()
    )
    for position, step_spec in enumerate(step_specs, start=1):
        name, step_type, instructions, success_criteria, allowed_tools = step_spec
        step = existing_steps[position - 1] if position - 1 < len(existing_steps) else None
        if step is None:
            step = AgentStep(
                id=str(uuid.uuid4()),
                agent_id=agent_id,
                position=position,
            )
            db.add(step)
        step.position = position
        step.name = name
        step.step_type = step_type
        step.instructions = instructions
        step.success_criteria = success_criteria
        step.allowed_tools = allowed_tools
        step.is_enabled = True

    if not delete_extra_steps:
        return

    for step in existing_steps[len(step_specs) :]:
        await db.delete(step)
