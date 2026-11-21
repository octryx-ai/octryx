"""Skill usage counts: platform admins only.

- ``GET /usage?days=`` — uses and refusals per catalog skill by surface and invocation, plus unmanaged names
  (project skills of octryx-claude sessions, by name only). ``days`` 1–365, default 30.
- ``GET /skills/{id}/usage?days=`` — the same counts for one skill.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import User
from ...services.skill_catalog.usage import usage_summary
from ...time_utils import utc_now
from .skill_catalog_deps import CATALOG_PREFIX, require_platform_admin

router = APIRouter(prefix=CATALOG_PREFIX, tags=["skill-catalog"])


def _since(days: int) -> datetime:
    return utc_now() - timedelta(days=days)


@router.get("/usage")
async def catalog_usage(days: int = Query(30, ge=1, le=365), db: AsyncSession = Depends(get_db),
                        _admin: User = Depends(require_platform_admin)):
    return {"days": days, **await usage_summary(db, since=_since(days))}


@router.get("/skills/{skill_id}/usage")
async def skill_usage(skill_id: str, days: int = Query(30, ge=1, le=365), db: AsyncSession = Depends(get_db),
                      _admin: User = Depends(require_platform_admin)):
    summary = await usage_summary(db, since=_since(days), skill_id=skill_id)
    entry = summary["skills"][0] if summary["skills"] else {"skill_id": skill_id, "uses": 0, "refusals": 0,
                                                            "by_surface": {}, "last_used_at": None}
    return {"days": days, **entry}
