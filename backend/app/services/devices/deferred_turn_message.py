"""A run continuation's prompt reaches the chat only when its agent turn really starts."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Message, Session

PENDING_KEY = "pending_turn_message"


def hold(thread: Session, *, job_id: str, turn_id: str, prompt: str, idempotency_key: str | None,
         author_user_id: str | None = None) -> None:
    metadata = dict(thread.metadata_ or {})
    metadata[PENDING_KEY] = {"job_id": job_id, "turn_id": turn_id, "prompt": prompt,
                             "idempotency_key": idempotency_key, "author_user_id": author_user_id}
    thread.metadata_ = metadata


async def _pending(db: AsyncSession, job: Any) -> tuple[Session | None, dict[str, Any]]:
    thread = await db.get(Session, job.session_id)
    held = dict(dict(getattr(thread, "metadata_", None) or {}).get(PENDING_KEY) or {})
    if thread is None or held.get("job_id") != job.id or held.get("turn_id") != job.turn_id:
        return None, {}
    return thread, held


def _clear(thread: Session) -> None:
    metadata = dict(thread.metadata_ or {})
    metadata.pop(PENDING_KEY, None)
    thread.metadata_ = metadata


async def release(db: AsyncSession, job: Any) -> bool:
    thread, held = await _pending(db, job)
    if thread is None:
        return False
    db.add(Message(session_id=thread.id, role="user", content=str(held.get("prompt") or ""),
                   idempotency_key=held.get("idempotency_key"), author_user_id=held.get("author_user_id")))
    _clear(thread)
    return True


async def drop(db: AsyncSession, job: Any) -> bool:
    thread, _held = await _pending(db, job)
    if thread is None:
        return False
    _clear(thread)
    return True


__all__ = ["PENDING_KEY", "drop", "hold", "release"]
