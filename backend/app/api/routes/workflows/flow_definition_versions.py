"""Publishing, review, unpublishing and running of flow definition versions and capabilities. A run without a Workspace
is 409 ``needs_configuration`` before anything is written."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....services.auth import get_current_user
from ....services.flow_definitions import publish_flow_definition_version
from ....services.flow_publish_review import request_review
from ....services.notification_delivery import require_admin_user

router = APIRouter()


@router.post("/versions/{version_id}/publish")
async def post_publish_flow_definition_version(
    version_id: str,
    payload: dict | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_admin_user(db, current_user)
    body = payload if isinstance(payload, dict) else {}
    result = await publish_flow_definition_version(
        db,
        version_id=version_id,
        current_user=current_user,
        publish_metadata=body.get("publish_metadata") if isinstance(body.get("publish_metadata"), dict) else body,
    )
    await db.commit()
    return result


@router.post("/versions/{version_id}/request-review")
async def post_request_flow_version_review(
    version_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """D2b2: the author asks a second admin to publish their phased workflow version (four-eyes)."""
    await require_admin_user(db, current_user)
    result = await request_review(db, version_id=version_id, current_user=current_user)
    await db.commit()
    return result


