"""Skill catalog upstream renewal: platform admins only."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import Skill, User
from ....services.skill_catalog import catalog_view, lifecycle, sources, upstream
from ....services.skill_catalog.errors import SkillCatalogError
from .skill_catalog_deps import CATALOG_PREFIX, refused, require_platform_admin

router = APIRouter(prefix=CATALOG_PREFIX, tags=["skill-catalog"])


class PathRequest(BaseModel):
    path: str | None = Field(default=None, max_length=500)


class TrackingRequest(BaseModel):
    tracking_mode: str = Field(min_length=1, max_length=10)


@router.post("/skills/{skill_id}/upstream/check")
async def check(skill_id: str, body: PathRequest | None = None, user: User = Depends(require_platform_admin),
                db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        skill = await lifecycle.get_skill(db, skill_id)
        status = await upstream.check_skill(db, skill, actor_id=user.id, path_override=(body or PathRequest()).path)
    except SkillCatalogError as error:
        await db.commit()  # the refusal is recorded on the source and the skill
        raise refused(error) from None
    await db.commit()
    return status


@router.post("/skills/{skill_id}/upstream/update", status_code=201)
async def update(skill_id: str, response: Response, body: PathRequest | None = None,
                 user: User = Depends(require_platform_admin), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        skill = await lifecycle.get_skill(db, skill_id)
        row = await upstream.update_from_upstream(db, skill, actor_id=user.id, audit_user=user.id,
                                                  path_override=(body or PathRequest()).path)
        await upstream.check_skill(db, skill, actor_id=None, path_override=row.upstream_path)
    except SkillCatalogError as error:
        await db.rollback()
        raise refused(error) from None
    await db.commit()
    response.headers["ETag"] = f'"{row.digest}"'
    return catalog_view.serialize_version(row)


@router.put("/skills/{skill_id}/tracking")
async def tracking(skill_id: str, body: TrackingRequest, user: User = Depends(require_platform_admin),
                   db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        skill = await upstream.set_tracking(db, await lifecycle.get_skill(db, skill_id), body.tracking_mode,
                                            actor_id=user.id)
    except SkillCatalogError as error:
        await db.rollback()
        raise refused(error) from None
    await db.commit()
    return {"skill_id": skill.id, "tracking_mode": skill.tracking_mode, "pinned_commit": skill.pinned_commit}


@router.post("/sources/{source_id}/check")
async def check_source(source_id: str, user: User = Depends(require_platform_admin),
                       db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        source = await sources.get_source(db, source_id)
    except SkillCatalogError as error:
        raise refused(error) from None
    results = []
    skill_ids = list((await db.execute(select(Skill.id).where(Skill.source_id == source.id))).scalars())
    for skill_id in skill_ids:
        skill = await db.get(Skill, skill_id)
        try:
            results.append({"skill_id": skill.id, "name": skill.name,
                            **await upstream.check_skill(db, skill, actor_id=user.id)})
        except SkillCatalogError as error:
            results.append({"skill_id": skill.id, "name": skill.name, "error": error.code})
        await db.commit()
    return {"source_id": source_id, "results": results}


@router.post("/sources/check-all")
async def check_all(_: User = Depends(require_platform_admin), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return await upstream.run_scheduled_checks(db, force=True)
