"""Admin panel routes for a provider's local runtime and its models."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import LLMProvider
from app.schemas.admin.admin_provider_panel import (
    ProviderModelCreateRequest,
    ProviderModelPullRequest,
    ProviderModelUpdateRequest,
)
from app.services.admin.provider._admin_provider_models import add_model as admin_add_model
from app.services.admin.provider._admin_provider_models import update_model as admin_update_model
from app.services.local_bootstrap import (
    pull_provider_model,
    refresh_provider_health,
)
from app.services.local_runtime_orchestrator import (
    ensure_local_runtime_started,
    stop_local_runtime,
)
from app.time_utils import utc_now
from app.web._helpers.api_guards import _require_admin_api

from .panel_provider_auth import router as panel_provider_auth_router

router = APIRouter()


@router.post("/chat/api/panel/providers/{provider_id}/start-local-runtime")
async def panel_start_local_runtime(provider_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    provider = await db.get(LLMProvider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    driver = str(getattr(provider, "driver", "") or "").strip()
    if driver not in {"ollama", "llama_cpp"}:
        raise HTTPException(status_code=400, detail="Only local providers can be started this way")
    result = await ensure_local_runtime_started(
        driver=driver, endpoint_url=provider.endpoint_url or "", provider=provider
    )
    await refresh_provider_health(db, provider_id=provider_id)
    return JSONResponse(result)


@router.post("/chat/api/panel/providers/{provider_id}/stop-local-runtime")
async def panel_stop_local_runtime(provider_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    provider = await db.get(LLMProvider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    driver = str(getattr(provider, "driver", "") or "").strip()
    if driver not in {"ollama", "llama_cpp"}:
        raise HTTPException(status_code=400, detail="Only local providers can be stopped this way")
    result = await stop_local_runtime(driver=driver, provider=provider)
    if isinstance(provider.capabilities_json, dict):
        provider.capabilities_json = {
            **provider.capabilities_json,
            "available_models": [],
        }
    provider.health_status = "stopped"
    provider.last_health_error = ""
    provider.last_health_check_at = utc_now()
    await db.commit()
    return JSONResponse(result)


@router.post("/chat/api/panel/providers/{provider_id}/pull-model")
async def panel_pull_provider_model(
    provider_id: str,
    payload: ProviderModelPullRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(await pull_provider_model(db, provider_id=provider_id, model_id=payload.model_id))


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


router.include_router(panel_provider_auth_router)
