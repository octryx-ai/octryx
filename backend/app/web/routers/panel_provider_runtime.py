"""Admin panel routes for a provider's local runtime and its models."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.admin.admin_provider_panel import (
    ProviderModelCreateRequest,
    ProviderModelUpdateRequest,
)
from app.services.admin.provider._admin_provider_models import add_model as admin_add_model
from app.services.admin.provider._admin_provider_models import update_model as admin_update_model
from app.web._helpers.api_guards import _require_admin_api

from .panel_runtime_settings import router as panel_runtime_settings_router

router = APIRouter()


@router.put("/chat/api/panel/providers/{provider_id}/models/{model_id}")
async def panel_update_model(
    provider_id: str,
    model_id: str,
    payload: ProviderModelUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    return JSONResponse(
        await admin_update_model(
            db,
            provider_id=provider_id,
            model_id=model_id,
            payload=payload.model_dump(exclude_unset=True),
            actor_user_id=admin.id,
        )
    )


@router.post("/chat/api/panel/providers/{provider_id}/models")
async def panel_add_model(
    provider_id: str,
    payload: ProviderModelCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    return JSONResponse(
        await admin_add_model(
            db,
            provider_id=provider_id,
            payload=payload.model_dump(),
            actor_user_id=admin.id,
        )
    )


router.include_router(panel_runtime_settings_router)
