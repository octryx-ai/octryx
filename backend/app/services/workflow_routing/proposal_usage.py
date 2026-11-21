"""The workflow proposal call's ``UsageEvent``, written by the run that owns the session.

The proposal resolves while the chat turn is prepared, before a new session row exists, so the
resolver cannot write a ``UsageEvent`` (its ``session_id`` and ``user_id`` are required). The
proposal record carries the answered call's bounded usage instead (``dispatch``: provider,
driver, model, tokens, ``usage_id``), and run preparation, which has the session and the user,
writes exactly one event per answered call through :func:`record_workflow_proposal_usage`.

- The event records its owner in ``usage_events.dispatch_owner`` (``workflow_proposal``). Its
  ``request_id`` stays ``workflow_proposal:<usage_id>``, which makes the write idempotent: a
  resumed or repeated preparation of the same turn finds the row and writes nothing.
- A call that never answered (no runtime, all runtimes failed, timeout) has no ``usage_id``
  and writes nothing: there is no usage to account.
- The cost is attributed like every other usage event (``compute_usage_event_cost_attribution``
  with the serving driver).
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import select

from .proposal_model import DISPATCH_OWNER
from .proposal_states import WORKFLOW_PROPOSAL_KEY, WORKFLOW_PROPOSAL_VERSION
from .workflow_selection import ROUTING_RESOLUTION_KEY

USAGE_EVENT_ID_KEY = "usage_event_id"
_USAGE_ID = re.compile(r"^[0-9a-f]{32}$")


def workflow_proposal_request_id(usage_id: str) -> str:
    return f"{DISPATCH_OWNER}:{usage_id}"


def _pending_dispatch(session_metadata: dict[str, Any]) -> tuple[dict, dict, dict] | None:
    resolution = session_metadata.get(ROUTING_RESOLUTION_KEY)
    record = resolution.get(WORKFLOW_PROPOSAL_KEY) if isinstance(resolution, dict) else None
    if not isinstance(record, dict) or record.get("version") != WORKFLOW_PROPOSAL_VERSION:
        return None
    dispatch = record.get("dispatch")
    if not isinstance(dispatch, dict) or dispatch.get(USAGE_EVENT_ID_KEY):
        return None
    if dispatch.get("dispatch_owner") != DISPATCH_OWNER or not int(dispatch.get("calls") or 0):
        return None
    if not _USAGE_ID.fullmatch(str(dispatch.get("usage_id") or "")):
        return None
    return resolution, record, dispatch


async def record_workflow_proposal_usage(
    db: Any,
    *,
    session_metadata: dict[str, Any],
    session_id: str | None,
    user_id: str | None,
) -> str | None:
    """Write the proposal call's ``UsageEvent`` once; return its id, or ``None`` when none is due.

    Marks the record (copy-on-write, so the caller's metadata assignment persists it) with the
    event id. The caller persists ``session_metadata`` as it does for the rest of preparation.
    """
    pending = _pending_dispatch(session_metadata) if db is not None and session_id and user_id else None
    if pending is None:
        return None
    from ...models import UsageEvent
    from ..budget import compute_usage_event_cost_attribution

    resolution, record, dispatch = pending
    request_id = workflow_proposal_request_id(str(dispatch["usage_id"]))
    existing = (
        await db.execute(select(UsageEvent.id).where(UsageEvent.request_id == request_id).limit(1))
    ).scalar_one_or_none()
    event_id = existing
    if existing is None:
        provider = str(dispatch.get("provider") or DISPATCH_OWNER)[:100]
        model = str((dispatch.get("models") or ["unknown"])[0] or "unknown")[:100]
        tokens_in = int(dispatch.get("input_tokens") or 0)
        tokens_out = int(dispatch.get("output_tokens") or 0)
        attribution = await compute_usage_event_cost_attribution(
            db,
            provider=provider,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            driver=str(dispatch.get("driver") or "") or None,
        )
        event_id = str(uuid.uuid4())
        db.add(
            UsageEvent(
                id=event_id,
                session_id=session_id,
                user_id=user_id,
                provider=provider,
                model=model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost=attribution.cost,
                cost_source=attribution.cost_source or None,
                cost_status=attribution.status,
                request_id=request_id,
                dispatch_owner=DISPATCH_OWNER,
            )
        )
    session_metadata[ROUTING_RESOLUTION_KEY] = {
        **resolution,
        WORKFLOW_PROPOSAL_KEY: {**record, "dispatch": {**dispatch, USAGE_EVENT_ID_KEY: event_id}},
    }
    return event_id


__all__ = ["USAGE_EVENT_ID_KEY", "record_workflow_proposal_usage", "workflow_proposal_request_id"]
