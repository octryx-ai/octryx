"""Skill catalog import, sources and settings: platform admins only."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....http_multipart_route import BoundedFormRoute
from ....models import User
from ....services.skill_catalog import importer, sources
from ....services.skill_catalog.archive import MAX_UPLOAD_BYTES
from ....services.skill_catalog.errors import SkillCatalogError
from ....services.skill_catalog.settings import load_settings, save_settings
from .skill_catalog_deps import CATALOG_PREFIX, refused, require_platform_admin

router = APIRouter(prefix=CATALOG_PREFIX, tags=["skill-catalog"], route_class=BoundedFormRoute)


class InspectRequest(BaseModel):
    url: str = Field(min_length=1, max_length=500)
    ref: str = Field(default="HEAD", max_length=200)
    path: str = Field(default="", max_length=500)
    named_connection_id: str | None = Field(default=None, max_length=36)
    marketplace_plugin: str | None = Field(default=None, max_length=100)


class ImportItem(BaseModel):
    kind: str = Field(default="skill", max_length=20)
    path: str = Field(default="", max_length=500)
    name: str | None = Field(default=None, max_length=100)
    category_id: str = Field(min_length=1, max_length=36)
    tracking_mode: str = Field(default="pinned", max_length=10)
    tags: list[str] = Field(default_factory=list, max_length=20)


class ImportRequest(InspectRequest):
    commit: str = Field(min_length=40, max_length=40)
    trust: str | None = Field(default=None, max_length=16)
    label: str | None = Field(default=None, max_length=200)
    items: list[ImportItem] = Field(min_length=1, max_length=50)


class SourceUpdate(BaseModel):
    trust: str | None = Field(default=None, max_length=16)
    label: str | None = Field(default=None, max_length=200)
    named_connection_id: str | None = Field(default=None, max_length=36)


class SettingsRequest(BaseModel):
    licence_allowlist: list[str] | None = Field(default=None, max_length=100)
    allowed_hosts: list[str] | None = Field(default=None, max_length=50)
    update_check_hours: int | None = None


@router.post("/import/inspect")
async def inspect(body: InspectRequest, _: User = Depends(require_platform_admin),
                  db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        return await importer.inspect_git(db, body.model_dump())
    except SkillCatalogError as error:
        raise refused(error) from None


@router.post("/import/git", status_code=201)
async def import_git(body: ImportRequest, user: User = Depends(require_platform_admin),
                     db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        result = await importer.import_git(db, body.model_dump(), actor_id=user.id)
    except SkillCatalogError as error:
        await db.rollback()
        raise refused(error) from None
    await db.commit()
    return result


@router.post("/import/upload", status_code=201)
async def import_upload(file: UploadFile = File(...), category_id: str = Form(..., max_length=36),
                        tags: str = Form(default="", max_length=1000), user: User = Depends(require_platform_admin),
                        db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    try:
        result = await importer.import_upload(
            db, filename=file.filename or "SKILL.md", data=data, category_id=category_id,
            tags=[item for item in tags.split(",") if item.strip()], actor_id=user.id)
    except SkillCatalogError as error:
        await db.rollback()
        raise refused(error) from None
    await db.commit()
    return result


@router.get("/sources")
async def list_sources(_: User = Depends(require_platform_admin), db: AsyncSession = Depends(get_db)):
    return {"sources": await sources.list_sources(db), "settings": (await load_settings(db)).as_dict()}


@router.patch("/sources/{source_id}")
async def patch_source(source_id: str, body: SourceUpdate, _: User = Depends(require_platform_admin),
                       db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        source = await sources.update_source(db, await sources.get_source(db, source_id),
                                             body.model_dump(exclude_unset=True))
    except SkillCatalogError as error:
        raise refused(error) from None
    await db.commit()
    return sources.serialize_source(source)


@router.get("/settings")
async def get_settings(_: User = Depends(require_platform_admin), db: AsyncSession = Depends(get_db)):
    return (await load_settings(db)).as_dict()


@router.put("/settings")
async def put_settings(body: SettingsRequest, user: User = Depends(require_platform_admin),
                       db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        saved = await save_settings(db, body.model_dump(exclude_none=True), actor_id=user.id)
    except SkillCatalogError as error:
        raise refused(error) from None
    await db.commit()
    return saved.as_dict()
