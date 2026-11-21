"""Prompt catalog admin API (``/api/v1/prompt-catalog``).

Thin transport over ``services/prompt_catalog``: list the registered keys, view one
key (seed, templates, versions), write a new global draft version, diff a version
against the body it would replace, submit it for four-eyes review (every key), publish,
retire and revert a key to its shipped text. Global admins only; refusals are closed codes.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import User
from ...services.auth import get_current_user
from ...services.prompt_catalog import lifecycle, views
from ...services.worker.admin import require_admin

router = APIRouter(prefix="/api/v1/prompt-catalog", tags=["prompt-catalog"])


class CreateDraftRequest(BaseModel):
    # global, workspace (its owners / admins) or workflow (its owner) (``scope_rights``).
    scope_type: str = Field(default="global", max_length=24)
    scope_id: str | None = Field(default=None, max_length=60)  # a Workspace id or a workflow key
    body: str = Field(min_length=1, max_length=60_000)
    change_note: str = Field(default="", max_length=500)


class PublishRequest(BaseModel):
    governance_approval_id: str | None = Field(default=None, max_length=36)
    # The single-step publish under the ``single_admin`` approval rule: approve the own pending review first.
    self_approve: bool = False


@contextmanager
def _refusals() -> Iterator[None]:
    try:
        yield
    except lifecycle.PromptCatalogRefusal as refusal:
        raise HTTPException(status_code=refusal.status, detail=refusal.as_detail()) from None


async def _admin(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> User:
    await require_admin(db, current_user)
    return current_user


async def _reader(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> User:
    """A platform admin, a Workspace owner / admin or a workflow owner (they write their scope's
    texts); the lifecycle checks each write against the version's scope (``scope_rights``)."""
    from ...services.prompt_catalog.scope_rights import may_read_catalog

    if not await may_read_catalog(db, current_user.id):
        raise HTTPException(status_code=403, detail={"code": "prompt_catalog_forbidden"})
    return current_user


@router.get("")
async def list_prompts(
    area: str | None = Query(default=None, max_length=40),
    _user: User = Depends(_reader),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """One area's keys, or every area except the collapsed tool / MCP description areas."""
    items = await views.list_catalog(db, area=area or None)
    return {
        "items": items,
        "count": len(items),
        "areas": views.catalog_areas(),
        "collapsed_areas": sorted(views.COLLAPSED_AREAS),
    }


@router.get("/keys/{key}")
async def get_prompt(key: str, user: User = Depends(_reader), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    from ...services.admin.governance.admin_access_service import is_global_admin
    from ...services.prompt_catalog.scope_rights import writable_scopes

    with _refusals():
        detail = await views.catalog_detail(db, key,
                                            reader_id=None if await is_global_admin(db, user.id) else user.id)
    # The scopes this user may write, with labels, for the editor's scope selector.
    return {**detail, "writable_scopes": await writable_scopes(db, user.id)}


@router.post("/keys/{key}/drafts", status_code=201)
async def create_draft(
    key: str, body: CreateDraftRequest, user: User = Depends(_reader), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    with _refusals():
        _template, version = await lifecycle.create_draft(
            db,
            key=key,
            scope_type=body.scope_type,
            scope_id=body.scope_id,
            body=body.body,
            change_note=body.change_note,
            user=user,
        )
        await db.commit()
    return views.serialize_version(version)


@router.get("/versions/{version_id}/diff")
async def diff_version(
    version_id: str, user: User = Depends(_reader), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    with _refusals():
        template, _version = await lifecycle.load_version(db, version_id)
        if template.scope_type != "global":
            await lifecycle.require_rights(db, user, template.scope_type, template.scope_id)
        return await views.version_diff(db, version_id)


@router.post("/versions/{version_id}/submit")
async def submit_version(
    version_id: str, user: User = Depends(_reader), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    with _refusals():
        version = await lifecycle.submit_for_review(db, version_id=version_id, user=user)
        await db.commit()
    return views.serialize_version(version)


@router.post("/versions/{version_id}/publish")
async def publish_version(
    version_id: str, body: PublishRequest, user: User = Depends(_reader), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    with _refusals():
        version, gate = await lifecycle.publish(
            db, version_id=version_id, user=user, approval_id=body.governance_approval_id,
            self_approve=body.self_approve,
        )
        await db.commit()
    return {"version": views.serialize_version(version), "approval_gate": gate}


@router.post("/versions/{version_id}/retire")
async def retire_version(
    version_id: str, user: User = Depends(_reader), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    with _refusals():
        version = await lifecycle.retire(db, version_id=version_id, user=user)
        await db.commit()
    return views.serialize_version(version)


@router.post("/keys/{key}/revert")
async def revert_to_shipped(
    key: str, user: User = Depends(_admin), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    with _refusals():
        version = await lifecycle.revert_to_shipped(db, key=key, user=user)
        await db.commit()
    return views.serialize_version(version)
