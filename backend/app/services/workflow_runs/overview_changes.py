"""Who changed a listed workflow last, and when: the Workflows list's "Last changed" and "By" columns.

A flow keeps every change as a new version (a draft or a saved layout), so the latest version says when the workflow
last changed and its author who changed it. Display only.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User
from ...time_utils import utc_isoformat


def latest_version(versions: Iterable[Any]) -> Any | None:
    return max(versions, key=lambda item: item.version, default=None)


def last_change(versions: Iterable[Any], *, names: dict[str, str]) -> dict[str, Any]:
    latest = latest_version(versions)
    if latest is None:
        return {"updated_at": None, "updated_by": None}
    return {"updated_at": utc_isoformat(latest.created_at), "updated_by": names.get(latest.created_by or "")}


async def author_names(db: AsyncSession, owners: Iterable[Any]) -> dict[str, str]:
    """Display names of the latest versions' authors (the username when no display name is set)."""
    ids = {version.created_by for owner in owners if (version := latest_version(owner.versions)) and version.created_by}
    if not ids:
        return {}
    rows = await db.execute(select(User.id, User.display_name, User.username).where(User.id.in_(ids)))
    return {user_id: display_name or username for user_id, display_name, username in rows.all()}


__all__ = ["author_names", "last_change", "latest_version"]
