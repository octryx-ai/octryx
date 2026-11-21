from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import AgentWorker, User
from ..admin.governance.admin_access_service import is_global_admin


async def require_admin(db: AsyncSession, current_user: User) -> None:
    if not await is_global_admin(db, current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")


async def get_worker_with_relations(db: AsyncSession, worker_id: str) -> AgentWorker | None:
    return (
        await db.execute(
            select(AgentWorker)
            .options(
                selectinload(AgentWorker.onboarding),
                selectinload(AgentWorker.runtime_state),
                selectinload(AgentWorker.trust_events),
            )
            .where(AgentWorker.id == worker_id)
        )
    ).scalar_one_or_none()
