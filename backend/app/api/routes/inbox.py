"""``GET /api/v1/inbox``: the signed-in user's personal Inbox (observability O6). Read-only."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import User
from ...services.auth import get_current_user
from ...services.inbox.service import personal_inbox

router = APIRouter(prefix="/api/v1/inbox", tags=["inbox"])


@router.get("")
async def get_inbox(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await personal_inbox(db, current_user)
