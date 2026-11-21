"""Admin panel routes for identity providers and command execution policies.

Included by ``chat_approvals.router``, so both mounts of that router serve these routes too.
"""

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.admin.admin_panel._governance import IdentityProviderUpsertRequest
from app.services.admin.panel.admin_panel_service import (
    create_exec_policy_payload,
    delete_exec_policy_payload,
    get_exec_policy_payload,
    list_exec_policy_payloads,
    update_exec_policy_payload,
    update_global_exec_policy_payload,
)
from app.services.oidc import (
    list_identity_providers as admin_list_identity_providers,
)
from app.services.oidc import (
    serialize_identity_provider,
)
from app.services.oidc import (
    upsert_identity_provider as admin_upsert_identity_provider,
)
from app.web._helpers._serialization_ext import _serialize_exec_policy_config
from app.web._helpers.api_guards import _require_admin_api, _require_admin_permission_api

router = APIRouter()


@router.get("/chat/api/panel/identity-providers")
async def admin_panel_list_identity_providers(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_permission_api(request, db, resource="identity_providers", action="read")
    providers = await admin_list_identity_providers(db)
    return JSONResponse([serialize_identity_provider(provider) for provider in providers])


@router.post("/chat/api/panel/identity-providers")
async def admin_panel_upsert_identity_provider(
    payload: IdentityProviderUpsertRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_permission_api(request, db, resource="identity_providers", action="write")
    return JSONResponse(
        await admin_upsert_identity_provider(
            db,
            payload=payload.model_dump(exclude_none=True),
            serialize_provider=serialize_identity_provider,
            actor_user_id=admin.id,
        )
    )


@router.put("/chat/api/panel/identity-providers/{provider_id}")
async def admin_panel_update_identity_provider(
    provider_id: str,
    payload: IdentityProviderUpsertRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_permission_api(request, db, resource="identity_providers", action="write")
    data = payload.model_dump(exclude_none=True)
    data["id"] = provider_id
    return JSONResponse(
        await admin_upsert_identity_provider(
            db,
            payload=data,
            serialize_provider=serialize_identity_provider,
            actor_user_id=admin.id,
        )
    )


@router.get("/chat/api/panel/exec-policy")
async def admin_panel_get_exec_policy(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(await get_exec_policy_payload(db))


@router.put("/chat/api/panel/exec-policy")
async def admin_panel_update_exec_policy(
    request: Request,
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    return JSONResponse(await update_global_exec_policy_payload(db, payload, actor_user_id=admin.id))


@router.get("/chat/api/panel/exec-policies")
async def admin_panel_list_exec_policies(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(await list_exec_policy_payloads(db, serialize_exec_policy_config=_serialize_exec_policy_config))


@router.post("/chat/api/panel/exec-policies")
async def admin_panel_create_exec_policy(
    request: Request,
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    return JSONResponse(
        await create_exec_policy_payload(
            db,
            payload=payload,
            serialize_exec_policy_config=_serialize_exec_policy_config,
            actor_user_id=admin.id,
        )
    )


@router.put("/chat/api/panel/exec-policies/{config_id}")
async def admin_panel_update_exec_policy_config(
    config_id: str,
    request: Request,
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    return JSONResponse(
        await update_exec_policy_payload(
            db,
            config_id=config_id,
            payload=payload,
            serialize_exec_policy_config=_serialize_exec_policy_config,
            actor_user_id=admin.id,
        )
    )


@router.delete("/chat/api/panel/exec-policies/{config_id}")
async def admin_panel_delete_exec_policy_config(
    config_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_api(request, db)
    return JSONResponse(await delete_exec_policy_payload(db, config_id=config_id, actor_user_id=admin.id))
