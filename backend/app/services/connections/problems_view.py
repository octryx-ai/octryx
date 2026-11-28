"""``problems_count`` and ``problems`` of the connection list and detail, from the problems aggregator."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User
from ..problems.scope import ProblemScope, platform_scope
from ..problems.service import visible_problems
from .rights import Viewer


async def problems_by_connection(db: AsyncSession, viewer: Viewer,
                                 ids: Iterable[str]) -> dict[str, list[dict[str, Any]]]:
    wanted = {str(item) for item in ids}
    found: dict[str, list[dict[str, Any]]] = {item: [] for item in wanted}
    user = await db.get(User, viewer.user_id)
    if not wanted or user is None:
        return found
    scope = platform_scope(user) if viewer.platform_admin else ProblemScope(frozenset(viewer.admin_workspaces))
    for problem in await visible_problems(db, user, scope):
        if problem.connection_id in wanted:
            found[problem.connection_id].append(problem.to_dict())
    return found


__all__ = ["problems_by_connection"]
