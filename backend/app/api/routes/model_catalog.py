"""The Model catalog admin API (Runtime → Models → Model catalog). Transport only; logic in
``services/model_catalog``. Platform admins only; the admin surface dependencies (CSRF for cookie sessions) apply.

- ``GET  /api/v1/admin/model-catalog`` — every row, the provider filter options, clearance levels, capability keys.
- ``GET  /api/v1/admin/model-catalog/overview`` — Global › Models: providers with their model counts, every model
  with price and what the workspaces made of it (``services/workspace_models/overview``).
- ``GET  /api/v1/admin/model-catalog/models/{id}`` — one row.
- ``PATCH /api/v1/admin/model-catalog/models/{id}`` — General / Data / Generation / Cost fields; 422 with a code.
- ``POST /api/v1/admin/model-catalog/sync`` — refresh from the providers; answers proposals (new upstream),
  gone-upstream rows and gateway models without an alias.
- ``POST /api/v1/admin/model-catalog/sync/add`` ``{selected: [{provider_id, model_id}]}`` — add proposals inactive.
- ``POST /api/v1/admin/model-catalog/models/{id}/alias`` — "Add to catalog" for a gateway model without an alias.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import User
from ...services.access_control import _user_is_admin
from ...services.auth import get_current_user
from ...services.control_plane_service import build_provider_client_kwargs_async
from ...services.model_catalog.contract import ModelCatalogError
from ...services.model_catalog.sync import add_alias_for, add_selected, catalog_attention, sync_catalog
from ...services.model_catalog.update import update_catalog_model
from ...services.model_catalog.views import catalog_row, list_catalog
from ...services.workspace_models.overview import models_overview

router = APIRouter(prefix="/api/v1/admin/model-catalog", tags=["model-catalog"])

ADMIN_FORBIDDEN = "Platform admin role required"
MAX_SELECTED = 200


class SelectedModel(BaseModel):
    provider_id: str = Field(min_length=1, max_length=36)
    model_id: str = Field(min_length=1, max_length=200)


class AddSelectedRequest(BaseModel):
    selected: list[SelectedModel] = Field(min_length=1, max_length=MAX_SELECTED)


async def _admin(db: AsyncSession, user: User) -> User:
    if not await _user_is_admin(db, user.id):
        raise HTTPException(status_code=403, detail=ADMIN_FORBIDDEN)
    return user


def _refused(error: ModelCatalogError) -> HTTPException:
    return HTTPException(status_code=error.status, detail={"code": error.code})


@router.get("")
async def get_model_catalog(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    await _admin(db, user)
    return await list_catalog(db)


@router.get("/overview")
async def get_models_overview(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    await _admin(db, user)
    return await models_overview(db)


@router.get("/models/{model_id}")
async def get_catalog_model(
    model_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    await _admin(db, user)
    try:
        return await catalog_row(db, model_id)
    except ModelCatalogError as error:
        raise _refused(error) from None


@router.patch("/models/{model_id}")
async def patch_catalog_model(
    model_id: str,
    body: dict[str, Any] = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _admin(db, user)
    try:
        await update_catalog_model(db, model_id=model_id, payload=body, actor_id=user.id)
    except ModelCatalogError as error:
        await db.rollback()
        raise _refused(error) from None
    await db.commit()
    return await catalog_row(db, model_id)


@router.post("/sync")
async def post_catalog_sync(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    await _admin(db, user)
    result = await sync_catalog(db, build_kwargs=build_provider_client_kwargs_async, actor_id=user.id)
    await db.commit()
    return result


@router.post("/sync/add")
async def post_catalog_add_selected(
    body: AddSelectedRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    await _admin(db, user)
    created = await add_selected(
        db, selected=[item.model_dump() for item in body.selected],
        build_kwargs=build_provider_client_kwargs_async, actor_id=user.id,
    )
    await db.commit()
    return {"created": len(created), **await catalog_attention(db)}


@router.post("/models/{model_id}/alias")
async def post_catalog_alias(
    model_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    await _admin(db, user)
    try:
        await add_alias_for(db, model_id=model_id, actor_id=user.id)
    except ModelCatalogError as error:
        await db.rollback()
        raise _refused(error) from None
    await db.commit()
    return await catalog_row(db, model_id)


__all__ = ["router"]
