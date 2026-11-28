from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....schemas.core.auth import APIKeyCreateRequest, APIKeyCreateResponse, APIKeyResponse
from ....services.access_control import require_visible_workspace
from ....services.api_key import (
    create_api_key_for_user,
    list_api_keys_for_user,
    revoke_api_key_for_user,
    serialize_api_key,
)
from ....services.auth import get_current_user

router = APIRouter(prefix="/api/v1/api-keys", tags=["api-keys"])


@router.get("", response_model=list[APIKeyResponse])
async def list_api_keys(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_api_keys_for_user(db, current_user)


@router.post("", response_model=APIKeyCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    body: APIKeyCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_visible_workspace(db, current_user.id, body.project_id)
    entry, raw_key = await create_api_key_for_user(
        db,
        current_user=current_user,
        name=body.name,
        scopes=body.scopes,
        project_id=body.project_id,
        expires_at=body.expires_at,
    )
    payload = serialize_api_key(entry)
    # Return only the raw key ONCE during creation - never returned again
    # Frontend should save it immediately as it cannot be retrieved
    payload["api_key"] = raw_key
    return payload


@router.delete("/{key_id}", status_code=status.HTTP_200_OK)
async def delete_api_key(
    key_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    entry = await revoke_api_key_for_user(db, current_user=current_user, key_id=key_id)
    if entry.revoked_at is None:
        raise HTTPException(status_code=500, detail="Failed to revoke API key")
    return {"ok": True, "id": entry.id, "revoked_at": entry.revoked_at.isoformat()}
