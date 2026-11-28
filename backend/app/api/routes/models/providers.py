from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....schemas.operations.provider import ModelResponse, ProviderCreate, ProviderResponse
from ....services.access_control import require_existing_workspace
from ....services.auth import get_current_user
from ....services.auth.admin_principal import get_current_admin_user
from ....services.control_plane_service import build_provider_client_kwargs_async
from ....services.provider import create_provider_response, list_active_provider_models, list_provider_responses
from ....services.provider import sync_provider_models as sync_provider_models_service

router = APIRouter(prefix="/api/v1/providers", tags=["providers"])


@router.get("", response_model=list[ProviderResponse])
async def list_providers(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_provider_responses(db)


@router.post("", response_model=ProviderResponse)
async def create_provider(
    body: ProviderCreate,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    await require_existing_workspace(db, current_user.id, body.project_id)
    return await create_provider_response(db, body, current_user)


@router.get("/{provider_id}/models", response_model=list[ModelResponse])
async def list_provider_models(
    provider_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_active_provider_models(db, provider_id=provider_id)


@router.post("/{provider_id}/models/sync")
async def sync_provider_models(
    provider_id: str,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    return await sync_provider_models_service(
        db,
        provider_id=provider_id,
        build_provider_client_kwargs_async_func=build_provider_client_kwargs_async,
    )
