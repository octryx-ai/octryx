"""The Workspaces an Engineering Knowledge scope names, resolved for the caller before anything is read or written."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..access_control import require_existing_workspace

# A scope of these types names a Workspace in ``scope_id``.
WORKSPACE_SCOPE_TYPES = frozenset({"workspace", "project"})


def _text(value: Any) -> str | None:
    return str(value or "").strip() or None


async def require_scope_workspaces(db: AsyncSession, user_id: str, *, scope_type: Any, scope_id: Any,
                                   workspace_id: Any = None) -> None:
    await require_existing_workspace(db, user_id, _text(workspace_id))
    if str(scope_type or "").strip().lower() in WORKSPACE_SCOPE_TYPES:
        await require_existing_workspace(db, user_id, _text(scope_id))


__all__ = ["WORKSPACE_SCOPE_TYPES", "require_scope_workspaces"]
