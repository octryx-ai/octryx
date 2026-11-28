"""The gateway's last refusal of a session's model call, kept for the device turn that made it: a coding engine
reports a refused call only as a failed connection, so the turn shows the gateway's reason instead."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...agent_gateway.contract import (
    HEADER_GATEWAY_REASON,
    HEADER_GATEWAY_STATE,
    STATE_DENIED,
    STATE_NEEDS_CONFIGURATION,
)
from .refusals import REASON_COUNT_TOKENS_UNSUPPORTED

logger = logging.getLogger(__name__)

KEY = "gateway_refusal"
MAX_REASON = 80
LOCK_TIMEOUT_MS = 2000
NOTED_STATES = (STATE_DENIED, STATE_NEEDS_CONFIGURATION)
# What the engine recovers from by itself (an upstream error it retries, a token count it does without) never names
# the turn: only the gateway's own policy and configuration refusals do.
UNNOTED_REASON = REASON_COUNT_TOKENS_UNSUPPORTED
UNNOTED_PREFIX = "upstream_"
# A device code that says only that the engine's model call failed: the gateway's reason replaces it.
GENERIC_ENGINE_ERRORS = frozenset({"", "codex_error_httpConnectionFailed",
                                   "codex_error_responseStreamConnectionFailed"})


def _noted(state: str, reason: str) -> bool:
    return bool(reason) and state in NOTED_STATES and reason != UNNOTED_REASON and not reason.startswith(UNNOTED_PREFIX)


async def note_refusal(session_id: str, response: Any) -> None:
    headers = getattr(response, "headers", None)
    reason = str(headers.get(HEADER_GATEWAY_REASON) or "") if headers is not None else ""
    state = str(headers.get(HEADER_GATEWAY_STATE) or "") if headers is not None else ""
    if not session_id or int(getattr(response, "status_code", 200) or 200) < 400 or not _noted(state, reason):
        return
    from .... import db as db_core

    try:
        # Its own session: a failed note never touches what the request itself writes.
        async with db_core.async_session_factory() as db:
            await _write_note(db, session_id, reason, state)
    except Exception:  # noqa: BLE001 - the refusal itself was already answered; the note is information only
        logger.warning("gateway.refusal_note_failed", exc_info=True)


async def _write_note(db: AsyncSession, session_id: str, reason: str, state: str) -> None:
    from ....models import Session
    from ....time_utils import utc_now

    if db.get_bind().dialect.name == "postgresql":
        # The request's own open transaction may hold a row this note writes: the note gives up, never the request.
        # ``set_config(..., true)`` is ``SET LOCAL``: it ends with this note's transaction.
        await db.execute(select(func.set_config("lock_timeout", f"{LOCK_TIMEOUT_MS}ms", True)))
    session = await db.get(Session, session_id)
    if session is None:
        return
    metadata = dict(session.metadata_ or {})
    note = {"reason": reason[:MAX_REASON], "state": state[:40], "at": utc_now().isoformat(),
            "turn_id": str(metadata.get("device_turn_id") or "")}
    session.metadata_ = {**metadata, KEY: note}
    # A device turn's model calls come through the gateway's own session: the note goes to the job's chat too.
    await _note_on_job_chat(db, str(metadata.get("device_job_id") or ""), note)
    await db.commit()


async def _note_on_job_chat(db: AsyncSession, job_id: str, note: dict[str, str]) -> None:
    from ....models import DeviceJob, Session

    job = await db.get(DeviceJob, job_id) if job_id else None
    chat = await db.get(Session, job.session_id) if job is not None and job.session_id else None
    if chat is not None:
        chat.metadata_ = {**dict(chat.metadata_ or {}), KEY: note}


def clear_refusal(session: Any) -> None:
    metadata = dict(getattr(session, "metadata_", None) or {})
    if KEY in metadata:
        metadata.pop(KEY)
        session.metadata_ = metadata


def turn_refusal(session: Any, turn_id: str) -> str:
    note = dict(getattr(session, "metadata_", None) or {}).get(KEY)
    if not isinstance(note, dict) or (note.get("turn_id") and note.get("turn_id") != turn_id):
        return ""
    return str(note.get("reason") or "")


__all__ = ["GENERIC_ENGINE_ERRORS", "KEY", "clear_refusal", "note_refusal", "turn_refusal"]
