"""A runner or device turn's ``workflow_select`` of a phased workflow in a chat thread: the chat's own start card, the
one the composer shows (prepared with the workflow key, held by the execution gate); the person confirms the start."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import DeviceJob, Message, User


async def chat_start_card(db: AsyncSession, *, job: DeviceJob, user: User, workflow_key: str,
                          reference: str) -> dict[str, Any]:
    from ...agent.runtime_defaults import DEFAULT_AGENT_MODE_KEY
    from ...db import core as db_core
    from ..session.turn_handoff import held_by_gate
    from ..session.turn_refusals import TurnRefusal
    from ..session.turn_request import SESSION_SCOPE_EXISTING, TurnRequest
    from ..session.turn_start import prepare_turn

    # The card reads its Work item from the person's request, like the composer's: the thread's last user message.
    asked = (await db.execute(select(Message.content).where(
        Message.session_id == job.session_id, Message.role == "user").order_by(Message.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    prompt = " ".join(part for part in (str(asked or "").strip(), reference) if part) or f"Start {workflow_key}."
    prepared = await prepare_turn(TurnRequest(
        user_id=user.id, prompt=prompt, session_id=job.session_id, session_scope=SESSION_SCOPE_EXISTING,
        project_id=job.workspace_id or "", project_id_explicit=True, workflow_key=workflow_key,
        agent_type=DEFAULT_AGENT_MODE_KEY))  # the chat's mode, as the composer sends it (its writes need the card)
    if isinstance(prepared, TurnRefusal):
        return {"state": "refused", "reason": prepared.state.value}
    if not await held_by_gate(db, prepared, session_factory=db_core.async_session_factory):
        return {"state": "needs_clarification", "reason": "workflow_not_startable",
                "message": f"{workflow_key} does not start from this chat."}
    return {"state": "needs_confirmation", "reason": "start_card_in_chat",
            "message": "The start card waits in the chat: the person confirms the start there. End your turn."}


__all__ = ["chat_start_card"]
