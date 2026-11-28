"""``POST /api/v1/secure-work/work-items``: create a platform-native Work item over REST."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....schemas.core.workspace_ref import WorkspaceId
from ....services.access_control import require_visible_workspace
from ....services.auth import get_current_user
from ....services.secure_work.platform_items import create_platform_work_item
from ._secure_work_scope import require_secure_work_scope

router = APIRouter(
    prefix="/api/v1/secure-work", tags=["secure-work"], dependencies=[Depends(require_secure_work_scope)]
)


class PlatformItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: WorkspaceId = Field(min_length=1, max_length=36)
    title: str = Field(min_length=1, max_length=500)
    description: str = ""
    issue_type: str = "task"
    epic_key: str = ""
    labels: list[str] = Field(default_factory=list)
    priority: str = "normal"


@router.post("/work-items", status_code=201)
async def post_platform_work_item(
    body: PlatformItemRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await require_visible_workspace(db, current_user.id, body.project_id)
    item = await create_platform_work_item(db, current_user=current_user, **body.model_dump())
    await db.commit()
    return {"id": item.id, "source_key": item.source_key, "issue_type": item.issue_type, "title": item.title,
            "work_state": item.work_state, "epic_key": item.epic_key, "project_id": item.project_id}
