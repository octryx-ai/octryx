from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....services.auth import get_current_user
from ....services.entity_version import list_entity_versions, rollback_entity_version

router = APIRouter(prefix="/api/v1/entities", tags=["entity-versions"])


@router.get("/{entity_type}/{entity_id}/versions")
async def get_entity_versions(
    entity_type: str,
    entity_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_entity_versions(db, entity_type=entity_type, entity_id=entity_id, current_user=current_user)


@router.post("/{entity_type}/{entity_id}/rollback/{version}")
async def rollback_entity(
    entity_type: str,
    entity_id: str,
    version: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await rollback_entity_version(
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        version=version,
        current_user=current_user,
    )
