"""Which Workspaces' threads a user may see in the chat sidebar, resolved once per bootstrap.

The bootstrap asks the same question for the project list, the group counts, every group's first page
and the archived count; each answer costs several queries (global admin check and project access with
its role lookups). Inside ``thread_visibility_memo()`` the first answer is reused for that user; outside
it every call resolves afresh, so a change of membership is never hidden across requests.
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import ParamSpec, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.admin.governance.admin_access_service import is_global_admin

from ...models import User
from ...services.project import get_user_project_ids

__all__ = ["thread_visibility_memo", "visible_thread_project_ids", "with_thread_visibility_memo"]

P = ParamSpec("P")
R = TypeVar("R")
_MEMO: ContextVar[dict[str, tuple[frozenset[str], bool]] | None] = ContextVar("chat_thread_visibility_memo", default=None)


@contextmanager
def thread_visibility_memo() -> Iterator[None]:
    token = _MEMO.set({})
    try:
        yield
    finally:
        _MEMO.reset(token)


def with_thread_visibility_memo(fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Run ``fn`` inside one ``thread_visibility_memo()`` (one answer per user for the whole call)."""

    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        with thread_visibility_memo():
            return await fn(*args, **kwargs)

    return wrapper


async def visible_thread_project_ids(db: AsyncSession, *, user: User) -> tuple[set[str], bool]:
    memo = _MEMO.get()
    if memo is not None and user.id in memo:
        project_ids, admin = memo[user.id]
        return set(project_ids), admin
    admin = await is_global_admin(db, user.id)
    project_ids = {str(project_id) for project_id in await get_user_project_ids(user.id, db)}
    if memo is not None:
        memo[user.id] = (frozenset(project_ids), admin)
    return project_ids, admin
