"""A run continuation's prompt reaches the chat only when its agent turn really starts.

The launcher runs a run's pending CI pipeline and hands-on test before the agent of the turn (``device_session``):
green ends the job with ``pipeline_done`` / ``hands_on_done`` and no agent runs; only then, or when there was nothing
to run first, does it accept the turn (``job_accepted``). Storing the continuation's prompt as the thread's user
message when the turn is offered would leave "the CI pipeline ran … and they are red … Fix exactly that" in the
chat after every green pipeline. So the message waits on the thread (:data:`PENDING_KEY`) and is stored at
``job_accepted`` (:func:`release`); a rejected turn, any reason, drops it (:func:`drop`).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Message, Session

PENDING_KEY = "pending_turn_message"


def hold(thread: Session, *, job_id: str, turn_id: str, prompt: str, idempotency_key: str | None) -> None:
    """Keep the turn's prompt on the thread until the device accepts the turn."""
    metadata = dict(thread.metadata_ or {})
    metadata[PENDING_KEY] = {"job_id": job_id, "turn_id": turn_id, "prompt": prompt,
                             "idempotency_key": idempotency_key}
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
    """At ``job_accepted``: the held prompt becomes the thread's user message; ``False`` when none was held."""
    thread, held = await _pending(db, job)
    if thread is None:
        return False
    db.add(Message(session_id=thread.id, role="user", content=str(held.get("prompt") or ""),
                   idempotency_key=held.get("idempotency_key")))
    _clear(thread)
    return True


async def drop(db: AsyncSession, job: Any) -> bool:
    """At ``job_rejected``: no agent turn ran, so the prompt never reaches the chat."""
    thread, _held = await _pending(db, job)
    if thread is None:
        return False
    _clear(thread)
    return True


__all__ = ["PENDING_KEY", "drop", "hold", "release"]
