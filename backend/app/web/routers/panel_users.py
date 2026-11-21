"""Auto-extracted router module: panel_users."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.admin.admin_panel._users import (
    IdentityGroupCreateRequest,
    IdentityGroupUpdateRequest,
    RoleCreateRequest,
    RoleUpdateRequest,
    UserApiKeyCreateRequest,
    UserCreateRequest,
    UserPasswordResetRequest,
    UserUpdateRequest,
)
from app.services.admin.governance._admin_user_queries import (
    list_user_oidc_identities as admin_list_user_oidc_identities,
)
from app.services.admin.governance._admin_user_queries import list_users as admin_list_users
from app.services.admin.governance.admin_access_service import (
    list_effective_access_diagnostics as admin_list_effective_access_diagnostics,
)
from app.services.admin.governance.admin_identity_group_service import (
    create_group as admin_create_identity_group,
)
from app.services.admin.governance.admin_identity_group_service import (
    delete_group as admin_delete_identity_group,
)
from app.services.admin.governance.admin_identity_group_service import (
    list_groups as admin_list_identity_groups,
)
from app.services.admin.governance.admin_identity_group_service import (
    update_group as admin_update_identity_group,
)
from app.services.admin.governance.admin_role_service import (
    create_role as admin_create_role,
)
from app.services.admin.governance.admin_role_service import (
    delete_role as admin_delete_role,
)
from app.services.admin.governance.admin_role_service import (
    list_permission_catalog as admin_list_role_permission_catalog,
)
from app.services.admin.governance.admin_role_service import (
    list_roles as admin_list_roles,
)
from app.services.admin.governance.admin_role_service import (
    update_role as admin_update_role,
)
from app.services.admin.governance.admin_user_api_key_service import (
    create_user_api_key as admin_create_user_api_key,
)
from app.services.admin.governance.admin_user_api_key_service import (
    list_user_api_keys as admin_list_user_api_keys,
)
from app.services.admin.governance.admin_user_api_key_service import (
    revoke_user_api_key as admin_revoke_user_api_key,
)
from app.services.admin.governance.admin_user_service import (
    create_user as admin_create_user,
)
from app.services.admin.governance.admin_user_service import (
    deactivate_user as admin_deactivate_user,
)
from app.services.admin.governance.admin_user_service import (
    reset_user_password as admin_reset_user_password,
)
from app.services.admin.governance.admin_user_service import (
    update_user as admin_update_user,
)
from app.web._helpers.api_guards import _require_admin_permission_api

from ...services.access_control import require_visible_workspace

router = APIRouter()


@router.get("/chat/api/panel/users")
async def panel_list_users(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_permission_api(request, db, resource="users", action="read")
    return JSONResponse(await admin_list_users(db))


@router.get("/chat/api/panel/roles")
async def panel_list_roles(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_permission_api(request, db, resource="roles", action="read")
    return JSONResponse(await admin_list_roles(db))


@router.get("/chat/api/panel/role-permission-catalog")
async def panel_list_role_permission_catalog(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_permission_api(request, db, resource="roles", action="read")
    return JSONResponse(await admin_list_role_permission_catalog())


@router.get("/chat/api/panel/effective-access")
async def panel_list_effective_access(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_permission_api(request, db, resource="audit", action="read")
    return JSONResponse(await admin_list_effective_access_diagnostics(db))


@router.get("/chat/api/panel/identity-groups")
async def panel_list_identity_groups(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_permission_api(request, db, resource="users", action="read")
    return JSONResponse(await admin_list_identity_groups(db))


@router.post("/chat/api/panel/identity-groups")
async def panel_create_identity_group(
    payload: IdentityGroupCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_permission_api(request, db, resource="users", action="write")
    return JSONResponse(await admin_create_identity_group(db, payload=payload.model_dump()))


@router.put("/chat/api/panel/identity-groups/{group_id}")
async def panel_update_identity_group(
    group_id: str,
    payload: IdentityGroupUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_permission_api(request, db, resource="users", action="write")
    return JSONResponse(
        await admin_update_identity_group(db, group_id=group_id, payload=payload.model_dump(exclude_none=True))
    )


@router.delete("/chat/api/panel/identity-groups/{group_id}")
async def panel_delete_identity_group(group_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_permission_api(request, db, resource="users", action="write")
    return JSONResponse(await admin_delete_identity_group(db, group_id=group_id))


@router.post("/chat/api/panel/roles")
async def panel_create_role(
    payload: RoleCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_permission_api(request, db, resource="roles", action="write")
    return JSONResponse(await admin_create_role(db, payload=payload.model_dump(), admin_id=admin.id))


@router.put("/chat/api/panel/roles/{role_id}")
async def panel_update_role(
    role_id: str,
    payload: RoleUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_permission_api(request, db, resource="roles", action="write")
    return JSONResponse(
        await admin_update_role(
            db,
            role_id=role_id,
            payload=payload.model_dump(exclude_none=True),
            admin_id=admin.id,
        )
    )


@router.delete("/chat/api/panel/roles/{role_id}")
async def panel_delete_role(role_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    admin = await _require_admin_permission_api(request, db, resource="roles", action="write")
    return JSONResponse(await admin_delete_role(db, role_id=role_id, admin_id=admin.id))


@router.post("/chat/api/panel/users")
async def panel_create_user(
    payload: UserCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_permission_api(request, db, resource="users", action="write")
    return JSONResponse(await admin_create_user(db, payload=payload.model_dump(), admin_id=admin.id))


@router.put("/chat/api/panel/users/{user_id}")
async def panel_update_user(
    user_id: str,
    payload: UserUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_permission_api(request, db, resource="users", action="write")
    return JSONResponse(
        await admin_update_user(
            db,
            admin_id=admin.id,
            user_id=user_id,
            payload=payload.model_dump(exclude_none=True),
        )
    )


@router.post("/chat/api/panel/users/{user_id}/reset-password")
async def panel_reset_user_password(
    user_id: str,
    payload: UserPasswordResetRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin_permission_api(request, db, resource="users", action="write")
    return JSONResponse(
        await admin_reset_user_password(
            db,
            admin_id=admin.id,
            user_id=user_id,
            password=payload.password,
        )
    )


@router.get("/chat/api/panel/users/{user_id}/api-keys")
async def panel_list_user_api_keys(user_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_permission_api(request, db, resource="api_keys", action="read")
    return JSONResponse(await admin_list_user_api_keys(db, user_id=user_id))


@router.get("/chat/api/panel/users/{user_id}/oidc-identities")
async def panel_list_user_oidc_identities(user_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_permission_api(request, db, resource="users", action="read")
    return JSONResponse(await admin_list_user_oidc_identities(db, user_id=user_id))


@router.post("/chat/api/panel/users/{user_id}/api-keys")
async def panel_create_user_api_key(
    user_id: str,
    payload: UserApiKeyCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    actor = await _require_admin_permission_api(request, db, resource="api_keys", action="write")
    await require_visible_workspace(db, str(actor.id), payload.project_id)
    # A key minted for someone else would act as them, private Workspace included. Only the
    # person mints their own keys; admins can still list and revoke others' keys.
    from ...models import User as _User  # noqa: PLC0415

    target = await db.get(_User, user_id)
    technical = target is not None and str(getattr(target, "account_type", "") or "") == "technical"
    if str(actor.id) != str(user_id) and not technical:  # a service account gets its keys from an admin
        return JSONResponse({"detail": "API keys can only be created by the person they belong to.",
                             "reason": "api_key_for_other_user"}, status_code=403)
    return JSONResponse(await admin_create_user_api_key(db, user_id=user_id, payload=payload.model_dump()))


@router.delete("/chat/api/panel/users/{user_id}/api-keys/{key_id}")
async def panel_revoke_user_api_key(
    user_id: str,
    key_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_permission_api(request, db, resource="api_keys", action="write")
    return JSONResponse(await admin_revoke_user_api_key(db, user_id=user_id, key_id=key_id))


@router.delete("/chat/api/panel/users/{user_id}")
async def panel_deactivate_user(user_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    admin = await _require_admin_permission_api(request, db, resource="users", action="write")
    return JSONResponse(await admin_deactivate_user(db, admin_id=admin.id, user_id=user_id))
