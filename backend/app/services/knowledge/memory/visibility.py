"""Who sees and who controls a memory item.

- A **personal** item (scope ``user``) is visible to its owner only. For anyone else it does not
  exist: loading it answers ``not_found``, exactly like an unknown id.
- A **workspace** item is visible to every member of its Workspace. Changing it needs the authoring
  role (admin/owner); a member without it gets ``author_required``.
- Memory is per Workspace. A Workspace binding reads Knowledge, never memory: every query
  here is pinned to the one authorized Workspace.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_memory import KnowledgeMemoryItem, MemoryScope, MemoryState
from ..access.authorization import AuthorizedWorkspace
from .errors import MemoryRefusedError

RECALLABLE_STATES = (MemoryState.OBSERVED.value, MemoryState.CONFIRMED.value)
_MAX_ID_CHARS = 36


def visible_to(workspace_project_id: str, user_id: str):
    """SQL predicate: items of this Workspace that this user may see."""
    item = KnowledgeMemoryItem
    return and_(
        item.project_id == workspace_project_id,
        or_(
            item.scope == MemoryScope.WORKSPACE.value,
            and_(item.scope == MemoryScope.USER.value, item.owner_user_id == user_id),
        ),
    )


def recallable(now: datetime):
    """SQL predicate: items a recall may return (active, unexpired, not erased)."""
    item = KnowledgeMemoryItem
    return and_(
        item.state.in_(RECALLABLE_STATES),
        item.text.is_not(None),
        or_(item.expires_at.is_(None), item.expires_at > now),
    )


def is_expired(row: KnowledgeMemoryItem, now: datetime) -> bool:
    return row.expires_at is not None and row.expires_at <= now


def may_change(row: KnowledgeMemoryItem, authorized: AuthorizedWorkspace, user_id: str,
               confirm_roles: tuple[str, ...] = ("owner", "admin")) -> bool:
    if row.scope == MemoryScope.USER.value:
        return row.owner_user_id == user_id
    if row.state == MemoryState.PROPOSED.value:
        # A session's proposed lesson: whoever the Workspace gave the confirmation right.
        return authorized.on_behalf_of is None and authorized.role in confirm_roles
    return authorized.may_author


async def load_for_change(
    db: AsyncSession, *, authorized: AuthorizedWorkspace, user_id: str, memory_id: object
) -> KnowledgeMemoryItem:
    """The visible item this user may change, or a fixed refusal."""
    if type(memory_id) is not str or not memory_id or len(memory_id) > _MAX_ID_CHARS:
        raise MemoryRefusedError("not_found")
    row = (
        await db.execute(
            select(KnowledgeMemoryItem).where(
                KnowledgeMemoryItem.id == memory_id, visible_to(authorized.project_id, user_id)
            )
        )
    ).scalar_one_or_none()
    if row is None or row.state == MemoryState.FORGOTTEN.value:
        raise MemoryRefusedError("not_found")
    from .settings import confirm_roles  # noqa: PLC0415

    if not may_change(row, authorized, user_id, await confirm_roles(db, authorized.project_id)):
        raise MemoryRefusedError("author_required")
    return row


__all__ = ["RECALLABLE_STATES", "is_expired", "load_for_change", "may_change", "recallable", "visible_to"]
