"""The device's side of a seat review, through the control plane: the review session, its request and its answer."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from ....models import DeviceJob, Session
from .seat import ANSWER_KEY, GATEWAY_REVIEW_JOB_KEY, PURPOSE_KEY, REQUEST_KEY, REVIEW_PURPOSE, is_review_thread


async def mark_review_session(db: AsyncSession, gateway_session: Session, job_id: str, user_id: str) -> bool:
    """At registration: the gateway session of a review turn's job is a review session (no tools, the request)."""
    if not job_id:
        return False
    job = await db.get(DeviceJob, job_id)
    if job is None or job.owner_user_id != user_id:
        return False
    if not is_review_thread(await db.get(Session, job.session_id)):
        return False
    gateway_session.metadata_ = {**dict(gateway_session.metadata_ or {}), GATEWAY_REVIEW_JOB_KEY: job.id,
                                 PURPOSE_KEY: REVIEW_PURPOSE}
    flag_modified(gateway_session, "metadata_")
    return True


def is_review_session(gateway_session: Session | None) -> bool:
    return gateway_session is not None and bool(dict(gateway_session.metadata_ or {}).get(GATEWAY_REVIEW_JOB_KEY))


async def _review_job(db: AsyncSession, gateway_session: Session, user_id: str) -> tuple[DeviceJob, Session] | None:
    job_id = str(dict(gateway_session.metadata_ or {}).get(GATEWAY_REVIEW_JOB_KEY) or "")
    job = await db.get(DeviceJob, job_id) if job_id else None
    if job is None or job.owner_user_id != user_id:
        return None
    thread = await db.get(Session, job.session_id)
    return (job, thread) if is_review_thread(thread) else None


async def review_request_for(db: AsyncSession, gateway_session: Session, user_id: str) -> dict[str, Any] | None:
    """The pending request of the session's review turn (``None`` when there is none for its current turn)."""
    found = await _review_job(db, gateway_session, user_id)
    if found is None:
        return None
    job, thread = found
    request = dict(thread.metadata_ or {}).get(REQUEST_KEY)
    if not isinstance(request, dict) or request.get("turn_id") != job.turn_id:
        return None
    return request


MAX_ANSWER_CHARS = 400_000


async def store_review_answer(db: AsyncSession, gateway_session: Session, user_id: str, body: Any) -> str | None:
    """Store the device's answer for the session's current review turn; a refusal reason, ``None`` when stored."""
    found = await _review_job(db, gateway_session, user_id)
    if found is None:
        return "review_request_not_found"
    job, thread = found
    if not isinstance(body, dict) or body.get("turn_id") != job.turn_id:
        return "review_turn_mismatch"
    text = body.get("text")
    if not isinstance(text, str) or len(text) > MAX_ANSWER_CHARS:
        return "review_answer_invalid"
    usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
    tokens = {key: int(usage[key]) for key in ("input_tokens", "output_tokens")
              if isinstance(usage.get(key), int) and not isinstance(usage.get(key), bool) and usage[key] >= 0}
    model = body.get("model")
    thread.metadata_ = {**dict(thread.metadata_ or {}), ANSWER_KEY: {
        "turn_id": job.turn_id, "text": text, "usage": tokens,
        "model": model[:200] if isinstance(model, str) and model.isprintable() else ""}}
    flag_modified(thread, "metadata_")
    return None
