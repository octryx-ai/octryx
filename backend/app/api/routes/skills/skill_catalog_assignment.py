"""Workspace → Skills: assignment by skill and by whole category, surfaces, readiness."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....services.access_control import require_existing_workspace
from ....services.skill_catalog.assignment import assignment_view, save_assignment
from ....services.skill_catalog.errors import SkillCatalogError
from ....services.skill_catalog.reach import skill_reach
from .skill_catalog_deps import CATALOG_PREFIX, refused, require_platform_admin

router = APIRouter(prefix=CATALOG_PREFIX, tags=["skill-catalog"])


class AssignmentRequest(BaseModel):
    mode: str = Field(min_length=1, max_length=20)
    skill_ids: list[str] = Field(default_factory=list, max_length=500)
    category_keys: list[str] = Field(default_factory=list, max_length=200)
    blocked_skill_ids: list[str] = Field(default_factory=list, max_length=500)
    surfaces: dict[str, bool] = Field(default_factory=dict)


@router.get("/workspaces/{project_id}/skills")
async def get_assignment(project_id: str, response: Response, user: User = Depends(require_platform_admin),
                         db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    await require_existing_workspace(db, user.id, project_id)  # before the first read seeds the Workspace foundation
    view = await assignment_view(db, project_id)
    await db.commit()  # the Workspace foundation may have been seeded on first read
    response.headers["ETag"] = f'"{view["digest"]}"'
    return view


@router.put("/workspaces/{project_id}/skills")
async def put_assignment(project_id: str, body: AssignmentRequest, response: Response,
                         if_match: str | None = Header(default=None), user: User = Depends(require_platform_admin),
                         db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    await require_existing_workspace(db, user.id, project_id)
    try:
        view = await save_assignment(db, project_id, body.model_dump(), if_match=if_match, actor_id=user.id)
    except SkillCatalogError as error:
        await db.rollback()
        raise refused(error) from None
    await db.commit()
    response.headers["ETag"] = f'"{view["digest"]}"'
    return view


@router.get("/skills/{skill_id}/workspaces")
async def get_skill_workspaces(skill_id: str, _: User = Depends(require_platform_admin),
                               db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return {"skill_id": skill_id, "workspaces": (await skill_reach(db, skill_id=skill_id)).get(skill_id, [])}
