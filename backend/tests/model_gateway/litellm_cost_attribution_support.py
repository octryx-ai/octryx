"""Shared helpers for the test_litellm_cost_attribution_* modules."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from app.agent.core.execution_support import record_usage_event
from app.agent.core.turn.turn_state import persist_runtime_assistant_response
from app.models import Session, UsageEvent, User
from tests.loop_runtime_turn_support import build_runtime_turn_kwargs

# --- the runtime path, end to end ---------------------------------------------


def _runtime_turn_kwargs(
    db,
    *,
    session_id: str,
    user_id: str,
    runtime: dict[str, Any],
    response: dict[str, Any],
) -> dict[str, Any]:
    """Real turn body, real usage recorder, real trace persistence, real database.

    Only the provider dispatch is faked, and the response it returns is one the
    real gateway adapter produced. Everything that decides or records what the
    turn cost — the turn body, ``record_usage_event``, the attribution, and the
    trace writer that persists ``TurnTrace`` and the canonical trace run — is the
    production code path, so what the assertions read is a stored row rather than
    an argument a stub happened to be handed.
    """

    async def _dispatch_loop_runtime_response(**_kwargs: Any):
        return response, runtime, [], None

    kwargs = build_runtime_turn_kwargs()
    kwargs.update(
        db=db,
        session_id=session_id,
        user_id=user_id,
        current_runtimes=[runtime],
        record_usage_event=record_usage_event,
        dispatch_loop_runtime_response=_dispatch_loop_runtime_response,
        persist_runtime_assistant_response=persist_runtime_assistant_response,
    )
    return kwargs


async def _session_for(db) -> tuple[User, Session]:
    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=admin_user.id, status="active")
    db.add(session)
    await db.commit()
    return admin_user, session


async def _usage_events(db, session_id: str) -> list[UsageEvent]:
    return list((await db.execute(select(UsageEvent).where(UsageEvent.session_id == session_id))).scalars().all())
