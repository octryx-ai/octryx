from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....services.access_control import require_visible_workspace
from ....services.auth import get_current_user
from ....services.feature_flag import evaluate_feature_flag

router = APIRouter(prefix="/api/v1/feature-flags", tags=["feature-flags"])


@router.get("/{key}")
async def get_feature_flag(
    key: str,
    project_id: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """A flag evaluated for the caller, in a Workspace the caller sees: an unknown Workspace and one the caller is no
    member of are the same 404, so the flag's Workspace allowlist is never probed through foreign ids."""
    project_id = (project_id or "").strip() or None
    await require_visible_workspace(db, current_user.id, project_id)
    return await evaluate_feature_flag(db, key=key, current_user=current_user, project_id=project_id)
