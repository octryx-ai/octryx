"""Skill catalog categories and tags: platform admins only. Logic in ``services/skill_catalog``.

- ``GET  /categories`` — the two-level tree with published-skill counts, the tag cloud, and per category key the
  number of Workspaces that assign the whole category (``assigned_in``).
- ``POST /categories`` ``{key, label, description?, parent_id?, sort_order?}`` — a child key may be given as the
  short name (``terraform`` under ``iac`` → ``iac.terraform``).
- ``PATCH /categories/{id}`` ``{label?, description?, sort_order?}`` — key and parent are immutable.
- ``POST /categories/{id}/archive`` (409 ``skill_category_not_empty``) and ``/restore``.
- ``PUT  /skills/{skill_id}/tags`` ``{tags}`` — identity metadata, not reviewed.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import Skill, User
from ...services.skill_catalog import categories
from ...services.skill_catalog.errors import SkillCatalogError
from .skill_catalog_deps import CATALOG_PREFIX, refused, require_platform_admin

router = APIRouter(prefix=CATALOG_PREFIX, tags=["skill-catalog"])


class CategoryCreate(BaseModel):
    key: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    parent_id: str | None = Field(default=None, max_length=36)
    sort_order: int = 0


class CategoryUpdate(BaseModel):
    key: str | None = Field(default=None, max_length=80)
    parent_id: str | None = Field(default=None, max_length=36)
    label: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    sort_order: int | None = None


class TagsRequest(BaseModel):
    tags: list[str] = Field(default_factory=list, max_length=50)


async def _catalog(db: AsyncSession) -> dict[str, Any]:
    return {"categories": await categories.tree(db), "tags": await categories.tag_counts(db),
            "assigned_in": await categories.whole_category_assignments(db)}


@router.get("/categories")
async def get_categories(_: User = Depends(require_platform_admin), db: AsyncSession = Depends(get_db)):
    return await _catalog(db)


@router.post("/categories", status_code=201)
async def post_category(body: CategoryCreate, user: User = Depends(require_platform_admin),
                        db: AsyncSession = Depends(get_db)):
    try:
        category = await categories.create_category(db, body.model_dump(), actor_id=user.id)
    except SkillCatalogError as error:
        raise refused(error) from None
    await db.commit()
    return categories.serialize_category(category)


@router.patch("/categories/{category_id}")
async def patch_category(category_id: str, body: CategoryUpdate, user: User = Depends(require_platform_admin),
                         db: AsyncSession = Depends(get_db)):
    try:
        category = await categories.get_category(db, category_id)
        await categories.update_category(db, category, body.model_dump(exclude_unset=True), actor_id=user.id)
    except SkillCatalogError as error:
        raise refused(error) from None
    await db.commit()
    return categories.serialize_category(category)


@router.post("/categories/{category_id}/archive")
async def archive(category_id: str, user: User = Depends(require_platform_admin), db: AsyncSession = Depends(get_db)):
    try:
        category = await categories.archive_category(db, await categories.get_category(db, category_id),
                                                     actor_id=user.id)
    except SkillCatalogError as error:
        raise refused(error) from None
    await db.commit()
    return categories.serialize_category(category)


@router.post("/categories/{category_id}/restore")
async def restore(category_id: str, user: User = Depends(require_platform_admin), db: AsyncSession = Depends(get_db)):
    try:
        category = await categories.restore_category(db, await categories.get_category(db, category_id),
                                                     actor_id=user.id)
    except SkillCatalogError as error:
        raise refused(error) from None
    await db.commit()
    return categories.serialize_category(category)


@router.put("/skills/{skill_id}/tags")
async def put_tags(skill_id: str, body: TagsRequest, user: User = Depends(require_platform_admin),
                   db: AsyncSession = Depends(get_db)):
    skill = await db.get(Skill, skill_id)
    if skill is None:
        raise HTTPException(status_code=404, detail={"code": "skill_not_found"})
    try:
        tags = await categories.set_tags(db, skill, body.tags, actor_id=user.id)
    except SkillCatalogError as error:
        raise refused(error) from None
    await db.commit()
    return {"skill_id": skill.id, "tags": tags}
