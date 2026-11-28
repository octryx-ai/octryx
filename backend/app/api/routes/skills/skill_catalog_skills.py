"""Skill catalog entries and their versions: platform admins only."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....services.skill_catalog import catalog_view, lifecycle
from ....services.skill_catalog.bundle import bundle_files
from ....services.skill_catalog.delivery import delivery_preview
from ....services.skill_catalog.diff import bundle_diff
from ....services.skill_catalog.errors import SkillCatalogError
from .skill_catalog_deps import CATALOG_PREFIX, refused, require_platform_admin

router = APIRouter(prefix=CATALOG_PREFIX, tags=["skill-catalog"])


class SkillCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    category_id: str = Field(min_length=1, max_length=36)
    frontmatter: dict[str, Any] = Field(default_factory=dict)
    body: str = Field(default="", max_length=1_000_000)
    files: dict[str, str] = Field(default_factory=dict)
    extension: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list, max_length=20)
    available_platform_chat: bool = True
    available_octryx_claude: bool = True
    licence_spdx: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=500)


class DraftSave(BaseModel):
    skill_md: str | None = Field(default=None, max_length=1_000_000)
    frontmatter: dict[str, Any] | None = None
    body: str | None = Field(default=None, max_length=1_000_000)
    files: dict[str, str | None] | None = None
    extension: dict[str, Any] | None = None
    category_id: str | None = Field(default=None, max_length=36)
    available_platform_chat: bool | None = None
    available_octryx_claude: bool | None = None
    licence_spdx: str | None = Field(default=None, max_length=64)
    scripts_allowed: bool | None = None
    scripts_reason: str | None = Field(default=None, max_length=500)
    acknowledged_findings: list[str] | None = Field(default=None, max_length=200)
    launch_spec: dict[str, Any] | None = None
    resolutions: dict[str, Any] | None = None
    note: str | None = Field(default=None, max_length=500)


class PublishRequest(BaseModel):
    governance_approval_id: str | None = Field(default=None, max_length=36)
    # The single-step publish under the ``single_admin`` approval rule: approve the own pending review first.
    self_approve: bool = False


def _with_etag(response: Response, payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("state") == "draft":
        response.headers["ETag"] = f'"{payload["digest"]}"'
    return payload


@router.get("/skills")
async def list_skills(q: str | None = Query(default=None, max_length=200),
                      category_id: str | None = Query(default=None, max_length=36),
                      tag: str | None = Query(default=None, max_length=40),
                      state: str | None = Query(default=None, max_length=20),
                      surface: str | None = Query(default=None, max_length=20),
                      source_id: str | None = Query(default=None, max_length=36),
                      kind: str | None = Query(default=None, max_length=20),
                      _: User = Depends(require_platform_admin), db: AsyncSession = Depends(get_db)):
    return await catalog_view.list_rows(db, {"q": q, "category_id": category_id, "tag": tag, "state": state,
                                             "surface": surface, "source_id": source_id, "kind": kind})


@router.post("/skills", status_code=201)
async def create_skill(body: SkillCreate, response: Response, user: User = Depends(require_platform_admin),
                       db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        skill, row = await lifecycle.create_skill(db, body.model_dump(), actor_id=user.id)
    except SkillCatalogError as error:
        await db.rollback()
        raise refused(error) from None
    await db.commit()
    return {"skill_id": skill.id, **_with_etag(response, catalog_view.serialize_version(row))}


@router.get("/skills/{skill_id}")
async def get_skill(skill_id: str, user: User = Depends(require_platform_admin), db: AsyncSession = Depends(get_db)):
    try:
        skill = await lifecycle.get_skill(db, skill_id)
    except SkillCatalogError as error:
        raise refused(error) from None
    return await catalog_view.detail(db, skill, viewer_id=user.id)


@router.post("/skills/{skill_id}/edit")
async def edit(skill_id: str, response: Response, user: User = Depends(require_platform_admin),
               db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        row, created = await lifecycle.start_draft(db, await lifecycle.get_skill(db, skill_id), actor_id=user.id)
    except SkillCatalogError as error:
        await db.rollback()
        raise refused(error) from None
    await db.commit()
    return {"created": created, **_with_etag(response, catalog_view.serialize_version(row))}


async def _version(db: AsyncSession, skill_id: str, version: int):
    skill = await lifecycle.get_skill(db, skill_id)
    return skill, await lifecycle.get_version(db, skill, version)


@router.get("/skills/{skill_id}/versions/{version}")
async def get_version(skill_id: str, version: int, response: Response, _: User = Depends(require_platform_admin),
                      db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        _skill, row = await _version(db, skill_id, version)
    except SkillCatalogError as error:
        raise refused(error) from None
    return _with_etag(response, catalog_view.serialize_version(row))


@router.put("/skills/{skill_id}/versions/{version}")
async def save_version(skill_id: str, version: int, body: DraftSave, response: Response,
                       if_match: str | None = Header(default=None), user: User = Depends(require_platform_admin),
                       db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        skill, row = await _version(db, skill_id, version)
        await lifecycle.save_draft(db, skill, row, body.model_dump(exclude_unset=True), if_match=if_match,
                                   actor_id=user.id)
    except SkillCatalogError as error:
        await db.rollback()
        raise refused(error) from None
    await db.commit()
    return _with_etag(response, catalog_view.serialize_version(row))


@router.get("/skills/{skill_id}/versions/{version}/files")
async def get_file(skill_id: str, version: int, path: str = Query(min_length=1, max_length=500),
                   _: User = Depends(require_platform_admin), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        _skill, row = await _version(db, skill_id, version)
    except SkillCatalogError as error:
        raise refused(error) from None
    entry = next((item for item in row.files or [] if item["path"] == path), None)
    if entry is None:
        raise refused(SkillCatalogError("skill_file_not_found", 404, path=path))
    content = (await bundle_files(db, [entry]))[0].content
    return {**entry, "content": content}


@router.get("/skills/{skill_id}/versions/{version}/delivery")
async def get_delivery(skill_id: str, version: int, _: User = Depends(require_platform_admin),
                       db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        skill, row = await _version(db, skill_id, version)
    except SkillCatalogError as error:
        raise refused(error) from None
    return await delivery_preview(db, skill, row)


@router.get("/skills/{skill_id}/versions/{version}/diff")
async def get_diff(skill_id: str, version: int, against: str = Query(default="published", max_length=20),
                   _: User = Depends(require_platform_admin), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        skill, row = await _version(db, skill_id, version)
        base = (await lifecycle.published_version(db, skill) if against == "published"
                else await lifecycle.get_version(db, skill, int(against)) if against.isdigit() else None)
    except SkillCatalogError as error:
        raise refused(error) from None
    if against != "published" and not against.isdigit():
        raise refused(SkillCatalogError("skill_diff_against_invalid", 422))
    old = {item.path: item.content for item in await bundle_files(db, base.files)} if base is not None else {}
    new = {item.path: item.content for item in await bundle_files(db, row.files)}
    return {"version": row.version, "against": base.version if base is not None else None,
            "files": bundle_diff(old, new)}


@router.post("/skills/{skill_id}/versions/{version}/submit")
async def submit(skill_id: str, version: int, user: User = Depends(require_platform_admin),
                 db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        skill, row = await _version(db, skill_id, version)
        approval = await lifecycle.submit(db, skill, row, actor_id=user.id)
    except SkillCatalogError as error:
        await db.rollback()
        raise refused(error) from None
    await db.commit()
    return {**catalog_view.serialize_version(row, content=False), "governance_approval_id": approval.id}


@router.post("/skills/{skill_id}/versions/{version}/publish")
async def publish(skill_id: str, version: int, body: PublishRequest, user: User = Depends(require_platform_admin),
                  db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        skill, row = await _version(db, skill_id, version)
        gate = await lifecycle.publish(db, skill, row, approval_id=body.governance_approval_id, actor_id=user.id,
                                      self_approve=body.self_approve)
    except SkillCatalogError as error:
        await db.rollback()
        raise refused(error) from None
    await db.commit()
    return {**catalog_view.serialize_version(row, content=False), "approval_gate": gate.as_dict()}


@router.post("/skills/{skill_id}/versions/{version}/retire")
async def retire(skill_id: str, version: int, user: User = Depends(require_platform_admin),
                 db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        skill, row = await _version(db, skill_id, version)
        await lifecycle.retire(db, skill, row, actor_id=user.id)
    except SkillCatalogError as error:
        await db.rollback()
        raise refused(error) from None
    await db.commit()
    return catalog_view.serialize_version(row, content=False)


@router.post("/skills/{skill_id}/versions/{version}/rollback", status_code=201)
async def rollback(skill_id: str, version: int, response: Response, user: User = Depends(require_platform_admin),
                   db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        skill = await lifecycle.get_skill(db, skill_id)
        row = await lifecycle.rollback(db, skill, version, actor_id=user.id)
    except SkillCatalogError as error:
        await db.rollback()
        raise refused(error) from None
    await db.commit()
    return _with_etag(response, catalog_view.serialize_version(row))
