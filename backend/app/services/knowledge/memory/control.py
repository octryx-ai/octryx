"""User control over memory: list, confirm, correct, forget. Forget is real: the text of the item and of every version
it superseded is erased."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_memory import KnowledgeMemoryItem, MemoryAuthorClass, MemoryClass, MemoryState
from ....time_utils import utc_now
from ..access.authorization import AuthorizedWorkspace
from .errors import MemoryRefusedError
from .feedback_capture import erase_forgotten_feedback_texts
from .presentation import control_entry
from .recall import usernames
from .text_guard import content_hash, normalize_memory_text
from .visibility import RECALLABLE_STATES, is_expired, load_for_change, may_change, visible_to

MAX_LISTED = 200
MAX_SUPERSESSION_DEPTH = 50
# Proposed lessons are listed (to be confirmed or rejected) but never recalled (``visibility.RECALLABLE_STATES``).
_CURRENT_STATES = (*RECALLABLE_STATES, MemoryState.CONTRADICTED.value, MemoryState.PROPOSED.value)
AUDIT_LESSON_CONFIRMED = "knowledge_memory.lesson_confirmed"
AUDIT_LESSON_REJECTED = "knowledge_memory.lesson_rejected"
_CORRECTABLE_STATES = frozenset(_CURRENT_STATES)


async def list_memory(
    db: AsyncSession, *, authorized: AuthorizedWorkspace, user_id: str, include_history: bool = False
) -> list[dict]:
    item = KnowledgeMemoryItem
    # Answer feedback has its own learning surface (``feedback_query``); this list is the memories.
    statement = select(item).where(
        visible_to(authorized.project_id, user_id), item.item_class != MemoryClass.ANSWER_FEEDBACK.value
    )
    if not include_history:
        statement = statement.where(item.state.in_(_CURRENT_STATES))
    rows = list((await db.execute(statement.order_by(item.created_at.desc(), item.id).limit(MAX_LISTED))).scalars())
    now = utc_now()
    if not include_history:
        rows = [row for row in rows if not is_expired(row, now)]
    names = await usernames(db, {row.author_user_id for row in rows if row.author_user_id})
    from .settings import confirm_roles  # noqa: PLC0415

    roles = await confirm_roles(db, authorized.project_id)
    return [
        control_entry(
            row,
            now=now,
            may_change=may_change(row, authorized, user_id, roles),
            recorded_by=names.get(row.author_user_id or ""),
        )
        for row in rows
    ]


def _mark(row: KnowledgeMemoryItem, state: MemoryState, user_id: str) -> None:
    row.state = state.value
    row.state_changed_by = user_id
    row.state_changed_at = utc_now()


async def confirm_memory(
    db: AsyncSession, *, authorized: AuthorizedWorkspace, user_id: str, memory_id: object
) -> KnowledgeMemoryItem:
    row = await load_for_change(db, authorized=authorized, user_id=user_id, memory_id=memory_id)
    if row.state == MemoryState.CONFIRMED.value and not is_expired(row, utc_now()):
        return row
    if row.state not in (MemoryState.OBSERVED.value, MemoryState.PROPOSED.value) or is_expired(row, utc_now()):
        raise MemoryRefusedError("not_active")
    if row.state == MemoryState.PROPOSED.value:
        _audit_lesson(db, row, user_id, AUDIT_LESSON_CONFIRMED)
    _mark(row, MemoryState.CONFIRMED, user_id)
    await db.flush()
    return row


def _audit_lesson(db: AsyncSession, row: KnowledgeMemoryItem, user_id: str, action: str) -> None:
    from ....models import AuditLog  # noqa: PLC0415

    db.add(AuditLog(user_id=user_id, action=action, resource_type="knowledge_memory_item", resource_id=row.id,
                    project_id=row.project_id,
                    details={"project_id": row.project_id, "item_class": row.item_class,
                             "session_id": row.session_id}))


async def reject_memory(db: AsyncSession, *, authorized: AuthorizedWorkspace, user_id: str, memory_id: object) -> None:
    row = await load_for_change(db, authorized=authorized, user_id=user_id, memory_id=memory_id)
    if row.state != MemoryState.PROPOSED.value:
        raise MemoryRefusedError("not_active")
    _audit_lesson(db, row, user_id, AUDIT_LESSON_REJECTED)
    await db.delete(row)
    await db.flush()


async def correct_memory(
    db: AsyncSession, *, authorized: AuthorizedWorkspace, user_id: str, memory_id: object, text: object
) -> KnowledgeMemoryItem:
    row = await load_for_change(db, authorized=authorized, user_id=user_id, memory_id=memory_id)
    if row.state not in _CORRECTABLE_STATES:
        raise MemoryRefusedError("not_active")
    if row.item_class == MemoryClass.ANSWER_FEEDBACK.value:
        # Feedback is changed by its author re-rating the answer, never rewritten by someone else.
        raise MemoryRefusedError("invalid_request")
    body = normalize_memory_text(text)
    corrected = KnowledgeMemoryItem(
        project_id=row.project_id,
        scope=row.scope,
        owner_user_id=row.owner_user_id,
        product=row.product,
        item_class=row.item_class,
        author_class=MemoryAuthorClass.HUMAN_STATED.value,
        # The person corrected it with their own words: nothing is left to review.
        state=MemoryState.CONFIRMED.value,
        text=body,
        content_hash=content_hash(body),
        author_user_id=user_id,
        created_at=utc_now(),
        supersedes_id=row.id,
        expires_at=row.expires_at,
    )
    db.add(corrected)
    _mark(row, MemoryState.SUPERSEDED, user_id)
    await db.flush()
    return corrected


async def forget_memory(db: AsyncSession, *, authorized: AuthorizedWorkspace, user_id: str, memory_id: object) -> int:
    row = await load_for_change(db, authorized=authorized, user_id=user_id, memory_id=memory_id)
    erased = 0
    erased_ids: list[str] = []
    seen: set[str] = set()
    current: KnowledgeMemoryItem | None = row
    while current is not None and current.id not in seen and len(seen) < MAX_SUPERSESSION_DEPTH:
        seen.add(current.id)
        if current.state != MemoryState.FORGOTTEN.value or current.text is not None:
            current.text = None
            current.content_hash = None
            _mark(current, MemoryState.FORGOTTEN, user_id)
            erased += 1
            erased_ids.append(current.id)
        older_id = current.supersedes_id
        current = await db.get(KnowledgeMemoryItem, older_id) if older_id else None
        # A chain never leaves its Workspace or its owner; a foreign link is not followed.
        if current is not None and (current.project_id != row.project_id or current.owner_user_id != row.owner_user_id):
            current = None
    await erase_forgotten_feedback_texts(db, erased_ids)
    await db.flush()
    return erased


__all__ = ["confirm_memory", "correct_memory", "forget_memory", "list_memory", "reject_memory"]
