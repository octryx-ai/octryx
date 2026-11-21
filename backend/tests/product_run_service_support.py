"""Shared helpers for the test_product_run_service_* modules."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project, User
from app.models import Session as ChatSession
from app.models.runtime.product_run import ProductRunTransition
from app.services.knowledge.identity.workspace import WorkspaceId
from app.services.product_run.service import GateFacts, open_run

ALLOWED = GateFacts(status="allowed", decision_source="execution_profile")


DENIED = GateFacts(status="denied", decision_source="execution_profile")


async def _workspace_session(db: AsyncSession, owner: User) -> tuple[Project, ChatSession]:
    project = Project(name=f"product-run-{uuid.uuid4().hex[:10]}", config={}, is_active=True)
    db.add(project)
    await db.flush()
    session = ChatSession(user_id=owner.id, project_id=project.id)
    db.add(session)
    await db.flush()
    return project, session


async def _open(db: AsyncSession, owner: User):
    project, session = await _workspace_session(db, owner)
    handle = await open_run(
        db,
        workspace_id=WorkspaceId.parse(project.id),
        owner_user_id=owner.id,
        session_id=session.id,
        origin="chat_turn",
    )
    return project, session, handle


async def _audit(db: AsyncSession, run_id: str) -> list[tuple[int, str | None, str, str | None]]:
    rows = await db.execute(
        select(
            ProductRunTransition.sequence,
            ProductRunTransition.from_state,
            ProductRunTransition.to_state,
            ProductRunTransition.end_reason,
        )
        .where(ProductRunTransition.run_id == run_id)
        .order_by(ProductRunTransition.sequence)
    )
    return [tuple(row) for row in rows]
