"""Personal eligible handoff offers, with current preview rights and no sender-thread links."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import User
from ....models.runtime.workflow_handoff import WorkflowHandoff
from ....time_utils import utc_now
from ...secure_work.access import work_scope_project_ids
from .authority import candidates
from .service import preview_handoff


async def _rights(**kwargs):
    from .permissions import rights_evaluator

    return await rights_evaluator(**kwargs)


async def inbox_items(db: AsyncSession, user: User) -> list[dict]:
    scope = await work_scope_project_ids(db, user)
    if scope == set():
        return []
    query = select(WorkflowHandoff).where(WorkflowHandoff.state == "offered",
                                        WorkflowHandoff.expires_at > utc_now())
    if scope is not None:
        query = query.where(WorkflowHandoff.workspace_id.in_(scope))
    rows = (await db.execute(query.order_by(WorkflowHandoff.issued_at.desc()).limit(50))).scalars().all()
    result = []
    for row in rows:
        if user.id not in await candidates(db, row):
            continue
        try:
            preview = await preview_handoff(db, row.id, user, rights_evaluator=_rights)
        except HTTPException as error:
            if error.status_code not in {403, 404, 409, 410}:
                raise
            continue
        result.append({"kind": "workflow_handoff", "id": row.id, "title": "Team handoff needs your decision",
            "created_at": row.issued_at.isoformat(), "subtitle": preview["acceptance"],
            "handoff_action": {"handoff_id": row.id}, "link": {"label": "Open this handoff"}})
    return result
