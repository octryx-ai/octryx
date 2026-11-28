"""The task a chat's task extraction produced: its prompt, the parsed definition and the stored task."""

import json
import re
import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import (
    Project,
    Task,
    User,
)
from ...models import (
    Session as AgentSession,
)
from ...models.project.task import TASK_DEFINITION_BINDING
from ...services.error_facts import error_text

__all__ = [
    "TASK_EXTRACTION_SYSTEM_PROMPT",
    "_parse_generated_task",
    "_persist_generated_task",
]

TASK_EXTRACTION_SYSTEM_PROMPT = (
    "You are a task extraction assistant. Based on the conversation, create a structured task definition.\n"
    "Return ONLY valid JSON (no markdown) with this structure:\n"
    '{"name":"Short task name","description":"What this task should accomplish",'
    '"agent_type":"diagnosis","steps":[{"name":"Step name","step_type":"analysis","instructions":"What to do"}]}\n'
    "agent_type should reference an existing mode key. "
    "Use a diagnosis-style mode for read-only tasks or a change-style mode for tasks that modify things. "
    "step_type options: analysis, tooling, documentation, change, connector_fetch, output. Maximum 6 steps."
)


def _parse_generated_task(content: str) -> dict:
    content = re.sub(r"```(?:json)?\s*", "", content).strip()
    json_match = re.search(r"\{.*\}", content, re.DOTALL)
    if not json_match:
        raise HTTPException(status_code=422, detail="AI could not generate a valid task structure")

    task_data: dict = {}
    raw_json = json_match.group()
    try:
        task_data = json.loads(raw_json)
    except json.JSONDecodeError:
        try:
            open_braces = raw_json.count("{") - raw_json.count("}")
            open_brackets = raw_json.count("[") - raw_json.count("]")
            patched = raw_json.rstrip(",\n ") + "]" * max(0, open_brackets) + "}" * max(0, open_braces)
            task_data = json.loads(patched)
        except (json.JSONDecodeError, Exception) as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid JSON from AI. {error_text('ai_task_json_invalid', exc)}",
            ) from exc
    return task_data


async def _persist_generated_task(db: AsyncSession, *, session: AgentSession, user: User, task_data: dict) -> Task:
    from ...models import TaskStep as _TaskStep
    from ...time_utils import utc_now as _utc_now

    proj_result = await db.execute(
        select(Project).where(Project.id == session.project_id) if session.project_id else select(Project).limit(1)
    )
    proj = proj_result.scalars().first()
    if not proj:
        raise HTTPException(status_code=400, detail="No project found")

    task = Task(
        id=str(uuid.uuid4()),
        project_id=proj.id,
        name=str(task_data.get("name") or "Generated Task")[:200],
        description=str(task_data.get("description") or ""),
        task_type="agent_run",
        agent_type=str(task_data.get("agent_type") or "diagnosis"),
        config={},
        is_active=False,
        owner_id=user.id,
        created_at=_utc_now(),
        # The generated Action runs its own generated step pipeline.
        dispatch_binding=TASK_DEFINITION_BINDING,
    )
    db.add(task)
    await db.flush()

    for i, step_data in enumerate(task_data.get("steps") or [], 1):
        step = _TaskStep(
            task_id=task.id,
            position=i,
            name=str(step_data.get("name") or f"Step {i}"),
            step_type=str(step_data.get("step_type") or "analysis"),
            instructions=str(step_data.get("instructions") or ""),
            connector_params_json=json.dumps({}),
            runtime_selector_json=json.dumps({}),
            context_fields_json=json.dumps([]),
            allowed_tools_json=json.dumps([]),
            spawn_strategy="per_item",
            max_fix_attempts=2,
            agent_timeout_seconds=300,
            is_enabled=True,
        )
        db.add(step)

    await db.commit()
    return task
