"""Publish an edit of a platform agent the governed way (draft revision, then a second admin publishes it)."""

from __future__ import annotations

from app.models import AgentDefinition
from app.services.agent_definition_revision_publish import publish_revision
from app.services.agent_definition_revisions import create_draft_revision
from tests.prompt_catalog_publish_support import second_admin


async def draft_edit(db, row: AgentDefinition, *, instructions: str):
    row.system_prompt = instructions
    await db.flush()
    return await create_draft_revision(db, definition=row, created_by=row.owner_id)


async def publish_edit(db, row: AgentDefinition, *, instructions: str):
    draft = await draft_edit(db, row, instructions=instructions)
    return await publish_revision(db, revision=draft, published_by=(await second_admin(db)).id)
