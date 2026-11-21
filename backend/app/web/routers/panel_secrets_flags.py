"""Admin panel routes for stored secrets and feature flags."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.admin.admin_panel._governance import (
    FeatureFlagUpsertRequest,
    SecretRevokeRequest,
    SecretRotateRequest,
    StoredSecretMetadataUpdateRequest,
)
from app.services.admin.panel.admin_secret_service import (
    list_secret_rotation_logs_for_admin as admin_list_secret_rotation_logs,
)
from app.services.admin.panel.admin_secret_service import (
    list_stored_secrets_for_admin as admin_list_stored_secrets,
)
from app.services.admin.panel.admin_secret_service import (
    revoke_stored_secret_for_admin as admin_revoke_stored_secret,
)
from app.services.admin.panel.admin_secret_service import (
    rotate_stored_secret_for_admin as admin_rotate_stored_secret,
)
from app.services.admin.panel.admin_secret_service import (
    update_stored_secret_for_admin as admin_update_stored_secret,
)
from app.services.feature_flag import (
    delete_feature_flag,
    list_feature_flags,
    upsert_feature_flag,
)
from app.web._helpers.api_guards import _require_admin_api

from .panel_task_management import router as panel_task_management_router

router = APIRouter()


@router.get("/chat/api/panel/stored-secrets")
async def panel_list_stored_secrets(
    request: Request,
    expiring_within_days: int | None = None,
    limit: int = 200,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(
        await admin_list_stored_secrets(
            db,
            expiring_within_days=expiring_within_days,
            limit=int(limit),
        )
    )


@router.get("/chat/api/panel/secret-rotation-log")
async def panel_list_secret_rotation_log(
    request: Request,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(await admin_list_secret_rotation_logs(db, limit=int(limit)))


@router.patch("/chat/api/panel/stored-secrets/{secret_id}")
async def panel_update_stored_secret(
    secret_id: str,
    payload: StoredSecretMetadataUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    return JSONResponse(
        await admin_update_stored_secret(
            db,
            secret_id=secret_id,
            payload=payload.model_dump(exclude_unset=True),
            actor_user_id=admin.id,
        )
    )


@router.post("/chat/api/panel/stored-secrets/{secret_id}/rotate")
async def panel_rotate_stored_secret(
    secret_id: str,
    payload: SecretRotateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _require_admin_api(request, db)
    return JSONResponse(
        await admin_rotate_stored_secret(
            db,
            secret_id=secret_id,
            rotated_by=user.id,
            payload=payload.model_dump(exclude_unset=True),
            actor_user_id=user.id,
        )
    )


@router.post("/chat/api/panel/stored-secrets/{secret_id}/revoke")
async def panel_revoke_stored_secret(
    secret_id: str,
    payload: SecretRevokeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _require_admin_api(request, db)
    return JSONResponse(
        await admin_revoke_stored_secret(
            db,
            secret_id=secret_id,
            revoked_by=user.id,
            payload=payload.model_dump(exclude_unset=True),
            actor_user_id=user.id,
        )
    )


@router.get("/chat/api/panel/feature-flags")
async def panel_list_feature_flags(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await list_feature_flags(db))


@router.post("/chat/api/panel/feature-flags")
async def panel_upsert_feature_flag(
    payload: FeatureFlagUpsertRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    return JSONResponse(await upsert_feature_flag(db, payload=payload.model_dump(), actor_user_id=admin.id))


@router.delete("/chat/api/panel/feature-flags/{key}")
async def panel_delete_feature_flag(key: str, request: Request, db: AsyncSession = Depends(get_db)):
    admin = await _require_admin_api(request, db)
    try:
        return JSONResponse(await delete_feature_flag(db, key=key, actor_user_id=admin.id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


router.include_router(panel_task_management_router)
