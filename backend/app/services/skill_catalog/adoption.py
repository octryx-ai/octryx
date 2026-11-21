"""Shared pieces of the skill catalog writers: top-level categories by label and the publish approval action.

A free ``category`` label becomes a top-level category with a stable key.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import SkillCategory, SkillVersion
from ...time_utils import utc_now


def category_key(label: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "-", str(label or "").strip().lower()).strip("-")
    return key[:80] or "uncategorized"


async def ensure_top_category(db: AsyncSession, label: str) -> SkillCategory:
    key = category_key(label)
    existing = (await db.execute(select(SkillCategory).where(SkillCategory.key == key))).scalar_one_or_none()
    if existing is not None:
        return existing
    now = utc_now()
    category = SkillCategory(key=key, label=str(label or "Uncategorized").strip()[:120] or "Uncategorized",
                             description="", sort_order=0, created_at=now, updated_at=now)
    db.add(category)
    await db.flush()
    return category


def approval_action(row: SkillVersion) -> str:
    return f"skill.publish:{row.id}:{row.digest}"


__all__ = [
    "approval_action",
    "category_key",
    "ensure_top_category",
]
