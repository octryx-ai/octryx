"""``POST /api/v1/secure-work/work-items/{work_item_id}/close``: the explicit Close action. Transport only.

Body (optional): ``{"reason": "..."}``. ``200`` is closed: ``{closed: true, mode, write_back: {enabled, reason},
jira, event, work_state, source_status, ...}`` with ``mode`` ``source_transition`` (Jira was transitioned into a
done-category status), ``local_only`` (write-back is not configured for it; ``write_back.reason`` says why) or
``already_closed``. A refused source close leaves the item open: ``409``/``422``/``502`` with
``detail: {closed: false, mode: "source_transition", code, message}`` (``services/secure_work/work_item_close``).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import User
from ...services.auth import get_current_user
from ...services.secure_work.access import require_work_operator
from ...services.secure_work.work_item_close import close_work_item
from ._secure_work_scope import require_secure_work_scope

router = APIRouter(
    prefix="/api/v1/secure-work", tags=["secure-work"], dependencies=[Depends(require_secure_work_scope)]
)


@router.post("/work-items/{work_item_id}/close")
async def post_work_item_close(
    work_item_id: str,
    payload: dict[str, Any] | None = Body(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await require_work_operator(db, current_user)
    result = await close_work_item(db, work_item_id=work_item_id, current_user=current_user, payload=payload or {})
    await db.commit()
    return result
