"""Auto-extracted router module: panel_providers."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.admin.admin_provider_panel import (
    ProviderCreateRequest,
    ProviderUpdateRequest,
)
from app.services.admin.provider.admin_provider_service import (
    create_provider as admin_create_provider,
)
from app.services.admin.provider.admin_provider_service import (
    delete_provider as admin_delete_provider,
)
from app.services.admin.provider.admin_provider_service import (
    list_provider_models as admin_list_provider_models,
)
from app.services.admin.provider.admin_provider_service import (
    list_providers as admin_list_providers,
)
from app.services.admin.provider.admin_provider_service import (
    sync_provider_models as admin_sync_provider_models,
)
from app.services.admin.provider.admin_provider_service import (
    update_provider as admin_update_provider,
)
from app.services.control_plane_service import (
    build_provider_client_kwargs_async,
)
from app.services.secret import set_secret_value
from app.services.setup_guide import get_setup_guide_status
from app.web._helpers.api_guards import _require_admin_api
from app.web._helpers.panel_serializers import _serialize_provider

from .panel_provider_runtime import router as panel_provider_runtime_router

router = APIRouter()


@router.get("/chat/api/panel/setup-guide")
async def panel_get_setup_guide(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await get_setup_guide_status(db))


@router.get("/chat/api/panel/providers")
async def panel_list_providers(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await admin_list_providers(db, serialize_provider=_serialize_provider))


@router.post("/chat/api/panel/providers")
async def panel_create_provider(
    payload: ProviderCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    return JSONResponse(
        await admin_create_provider(
            db,
            payload=payload.model_dump(),
            serialize_provider=_serialize_provider,
            set_secret_value_func=set_secret_value,
            actor_user_id=admin.id,
        )
    )


@router.put("/chat/api/panel/providers/{provider_id}")
async def panel_update_provider(
    provider_id: str,
    payload: ProviderUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    return JSONResponse(
        await admin_update_provider(
            db,
            provider_id=provider_id,
            payload=payload.model_dump(exclude_none=True),
            serialize_provider=_serialize_provider,
            set_secret_value_func=set_secret_value,
            actor_user_id=admin.id,
        )
    )


@router.delete("/chat/api/panel/providers/{provider_id}")
async def panel_delete_provider(provider_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    admin = await _require_admin_api(request, db)
    return JSONResponse(await admin_delete_provider(db, provider_id=provider_id, actor_user_id=admin.id))


@router.get("/chat/api/panel/providers/{provider_id}/models")
async def panel_list_provider_models(provider_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await admin_list_provider_models(db, provider_id=provider_id))


@router.post("/chat/api/panel/providers/{provider_id}/sync")
async def panel_sync_provider_models(provider_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    admin = await _require_admin_api(request, db)
    return JSONResponse(
        await admin_sync_provider_models(
            db,
            provider_id=provider_id,
            build_provider_client_kwargs_async_func=build_provider_client_kwargs_async,
            actor_user_id=admin.id,
        )
    )



router.include_router(panel_provider_runtime_router)
