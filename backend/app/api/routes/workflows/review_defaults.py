"""The installation's reviewer defaults: per coding engine the reviewer's ``{model, route}`` and the shallow-review
thresholds. Platform admins only."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import AuditLog, User
from ....services.admin.governance.admin_access_service import is_global_admin
from ....services.agent_gateway.review_keys import (
    DEFAULT_MODELS,
    INSTALLATION_KEY,
    SHALLOW_DEFAULTS,
    ReviewPolicyError,
    normalize_installation,
)
from ....services.auth import get_current_user

router = APIRouter(tags=["review-defaults"])


def _refusal(reason: str, status: int, path: str | None = None) -> JSONResponse:
    return JSONResponse({"state": "denied", "reason": reason, **({"path": path} if path else {})}, status_code=status)


@router.get("/api/v1/admin/review-defaults")
async def get_review_defaults(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not await is_global_admin(db, current_user.id):
        return _refusal("platform_admin_required", 403)
    from ....services.workflow_runs.review.choice import installation_defaults

    try:
        stored = await installation_defaults(db)
    except ReviewPolicyError as error:
        stored = {"invalid": error.reason}
    return {"defaults": stored, "platform": {"models": DEFAULT_MODELS, "shallow": SHALLOW_DEFAULTS}}


@router.put("/api/v1/admin/review-defaults")
async def put_review_defaults(body: dict[str, Any] = Body(...), current_user: User = Depends(get_current_user),
                              db: AsyncSession = Depends(get_db)):
    if not await is_global_admin(db, current_user.id):
        return _refusal("platform_admin_required", 403)
    from ....services.system_config.values import set_system_config_value

    try:
        value = normalize_installation(body or None)
    except ReviewPolicyError as error:
        return _refusal(error.reason, 400, error.path)
    await set_system_config_value(db, key=INSTALLATION_KEY, value=json.dumps(value) if value else None,
                                  description="The installation's reviewer defaults")
    db.add(AuditLog(user_id=current_user.id, action="admin.review_defaults_updated", resource_type="system_config",
                    resource_id=INSTALLATION_KEY, details={"defaults": value}))
    await db.commit()
    return {"defaults": value}
