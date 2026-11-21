"""Load, save and publish an Agent Definition through the visual Agent Designer.

The designer itself is a static artifact with no network access and no credential;
the admin host page carries its document to and from these functions. Saving goes
through the governed write boundary as one writer scope, so the definition
and all of its steps become exactly one immutable revision and one audit row.
Publication reuses ``publish_revision``, which re-validates the snapshot.

Scope: the same as the admin panel agent builder — the definition's owner, reached
only through an authenticated global-admin panel route.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.services.agent_definition_revision_publish import publish_revision
from app.services.agent_definition_revision_store import list_agent_definition_revisions, serialize_revision

from ...models import AgentDefinition, AgentStep
from ..agent_definition_authoring import governed_agent_definition_write
from ..agent_definition_execution import describe_execution_source
from ..agent_definition_writers import AgentDefinitionWriter
from .document import definition_from_document, document_from_definition
from .document_model import DESIGNER_CONFIG_KEY, DesignerDefinition

_NEW_STEP_TYPE = "analysis"


async def _owned_definition(db: AsyncSession, *, user_id: str, agent_id: str) -> AgentDefinition:
    agent = (
        await db.execute(
            select(AgentDefinition)
            .options(selectinload(AgentDefinition.steps))
            .where(AgentDefinition.id == agent_id, AgentDefinition.owner_id == user_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


def _ordered_steps(agent: AgentDefinition) -> list[AgentStep]:
    return sorted(agent.steps, key=lambda step: (int(step.position or 0), str(step.id)))


async def _latest_revision(db: AsyncSession, agent_id: str) -> dict[str, Any] | None:
    revisions = await list_agent_definition_revisions(db, agent_id)
    return serialize_revision(revisions[0]) if revisions else None


async def load_designer_document(db: AsyncSession, *, user_id: str, agent_id: str) -> dict[str, Any]:
    """Return the designer document for the live definition and its newest revision."""
    agent = await _owned_definition(db, user_id=user_id, agent_id=agent_id)
    document = document_from_definition(
        name=str(agent.name or ""),
        description=str(agent.description or ""),
        steps=[
            {"id": step.id, "name": step.name, "instructions": step.instructions, "step_config": step.step_config}
            for step in _ordered_steps(agent)
        ],
    )
    return {
        "agent_id": agent.id,
        "document": document,
        "revision": await _latest_revision(db, agent.id),
        "execution": await describe_execution_source(db, agent.id),
    }


async def _apply(agent: AgentDefinition, designed: DesignerDefinition, db: AsyncSession) -> None:
    if designed.name:
        agent.name = designed.name
    agent.description = designed.description
    existing = {step.id: step for step in agent.steps}
    kept: set[str] = set()
    for position, designed_step in enumerate(designed.steps, start=1):
        step = existing.get(designed_step.step_id)
        if step is None:
            step = AgentStep(
                id=str(uuid.uuid4()),
                agent_id=agent.id,
                step_type=_NEW_STEP_TYPE,
                success_criteria="",
                allowed_tools=[],
                is_enabled=True,
            )
            db.add(step)
        kept.add(step.id)
        step.position = position
        step.name = designed_step.name
        step.instructions = designed_step.instructions
        # Merge: runtime keys authored elsewhere survive; only the designer's own block is replaced.
        step.step_config = {**step.step_config, DESIGNER_CONFIG_KEY: designed_step.designer_config}
    for step_id, step in existing.items():
        if step_id not in kept:
            agent.steps.remove(step)
            await db.delete(step)


async def save_designer_document(db: AsyncSession, *, user_id: str, agent_id: str, document: Any) -> dict[str, Any]:
    """Validate and store a designer document as one governed write; refuse with 422.

    The result says whether the save created a revision (``changed``) or matched the
    newest one exactly (the boundary then records ``unchanged`` and appends nothing).
    """
    designed = definition_from_document(document)
    await _owned_definition(db, user_id=user_id, agent_id=agent_id)
    before = await _latest_revision(db, agent_id)
    async with governed_agent_definition_write(
        db, writer=AgentDefinitionWriter.AGENT_DESIGNER_DOCUMENT, actor_id=user_id
    ):
        agent = await _owned_definition(db, user_id=user_id, agent_id=agent_id)
        await _apply(agent, designed, db)
        await db.flush()
    await db.commit()
    loaded = await load_designer_document(db, user_id=user_id, agent_id=agent_id)
    after = loaded["revision"]
    loaded["changed"] = bool(after) and (before is None or after["id"] != before["id"])
    return loaded


async def publish_displayed_revision(
    db: AsyncSession, *, user_id: str, agent_id: str, revision_id: str
) -> dict[str, Any]:
    """Publish exactly the revision the person was shown, and only while it is still the newest.

    A newer revision written meanwhile by any other writer is never published unseen: 409.
    """
    await _owned_definition(db, user_id=user_id, agent_id=agent_id)
    revisions = await list_agent_definition_revisions(db, agent_id)
    if not revisions:
        raise HTTPException(status_code=409, detail="No revision to publish")
    if revisions[0].id != revision_id:
        raise HTTPException(status_code=409, detail="A newer revision exists; reload before publishing")
    published = await publish_revision(db, revision=revisions[0], published_by=user_id)
    await db.commit()
    return serialize_revision(published)


__all__ = ["load_designer_document", "publish_displayed_revision", "save_designer_document"]
