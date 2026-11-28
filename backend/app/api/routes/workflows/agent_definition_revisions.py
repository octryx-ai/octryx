"""API routes for immutable Agent Definition revisions."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_definition_revision_publish import publish_revision, validate_revision
from app.services.agent_definition_revision_store import list_agent_definition_revisions, serialize_revision

from ....db import get_db
from ....models import User
from ....services.agent_definition_access import resolve_definition, resolve_revision
from ....services.agent_definition_revisions import create_draft_revision, restore_revision
from ....services.auth import get_current_user

router = APIRouter(prefix="/api/v1/agent-definitions", tags=["agent-definition-revisions"])


@router.get("/revisions/{revision_id}")
async def get_revision(
    revision_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    revision, _ = await resolve_revision(
        db, current_user=current_user, revision_id=revision_id
    )
    return serialize_revision(revision)


@router.post("/revisions/{revision_id}/validate")
async def validate_revision_endpoint(
    revision_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    revision, _ = await resolve_revision(
        db, current_user=current_user, revision_id=revision_id
    )
    result = await validate_revision(db, revision=revision)
    return {"revision": serialize_revision(revision), "validation": result.as_dict()}


@router.post("/revisions/{revision_id}/publish")
async def publish_revision_endpoint(
    revision_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    revision, _ = await resolve_revision(
        db, current_user=current_user, revision_id=revision_id
    )
    published = await publish_revision(
        db, revision=revision, published_by=current_user.id
    )
    return serialize_revision(published)


@router.post("/revisions/{revision_id}/restore")
async def restore_revision_endpoint(
    revision_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    revision, definition = await resolve_revision(
        db, current_user=current_user, revision_id=revision_id
    )
    restored = await restore_revision(
        db, revision=revision, definition=definition, current_user=current_user
    )
    return serialize_revision(restored)


@router.get("/{definition_id}/revisions")
async def list_revisions(
    definition_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    definition = await resolve_definition(
        db, current_user=current_user, definition_id=definition_id
    )
    rows = await list_agent_definition_revisions(db, definition.id)
    return {
        "definition_id": definition.id,
        "items": [serialize_revision(row) for row in rows],
        "count": len(rows),
    }


@router.post("/{definition_id}/revisions")
async def create_revision(
    definition_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    definition = await resolve_definition(
        db, current_user=current_user, definition_id=definition_id
    )
    revision = await create_draft_revision(
        db, definition=definition, created_by=current_user.id
    )
    return serialize_revision(revision)
