"""Actual-principal handoff preview and hash-bound actions; acceptance precedes child start."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import User
from ...services.auth import get_current_user
from ...services.workflow_runs.handoff import service
from ...services.workflow_runs.handoff.contract import validate_action

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/workflow-handoffs", tags=["workflow-handoffs"])


async def _rights(**kwargs):
    from ...services.workflow_runs.handoff.permissions import rights_evaluator

    return await rights_evaluator(**kwargs)


async def _allocate(**kwargs):
    from ...services.workflow_runs.handoff.allocation import allocate_child

    return await allocate_child(**kwargs)


async def _start_child(db: AsyncSession, binding: dict) -> dict:
    from ...services.workflow_runs.handoff.lifecycle import start_accepted_child

    return await start_accepted_child(db, binding)


@router.get("/{handoff_id}")
async def preview_handoff(handoff_id: str, current_user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    return {"handoff": await service.preview_handoff(db, handoff_id, current_user, rights_evaluator=_rights)}


@router.post("/{handoff_id}/actions")
async def act_on_handoff(handoff_id: str, body: dict[str, Any] = Body(...),
                         current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    action = validate_action(body)
    # The ordinary preview guard makes unknown/out-of-scope offers equally unavailable.
    preview = await service.preview_handoff(db, handoff_id, current_user, rights_evaluator=_rights)
    if action["action"] == "decline":
        row = await service.decline_handoff(db, handoff_id, current_user, action)
        result = {"id": row.id, "state": row.state, "personal_response": "declined"}
        await db.commit()
        return {"handoff": result, "continuation": None}
    binding = await service.accept_handoff(db, handoff_id, current_user, action,
                                          rights_evaluator=_rights, allocator=_allocate)
    # Acceptance and receiver-owned allocations survive a later engine/readiness refusal.
    await db.commit()
    try:
        continuation = await _start_child(db, binding)
        if not isinstance(continuation, dict) or continuation.get("state") not in {"started", "held"}:
            raise ValueError("The continuation did not report its start state.")
        if (continuation.get("child_run_id") != binding["child_run_id"]
                or continuation.get("receiver_session_id") != binding["receiver_session_id"]):
            raise ValueError("The continuation did not bind the accepted child.")
        await db.commit()
    except Exception as error:
        logger.warning("Accepted handoff child initialization held (%s)", type(error).__name__,
                       extra={"handoff_id": handoff_id, "child_run_id": binding["child_run_id"]})
        # Only the post-acceptance transaction rolls back. No auto-retry or acceptance reversal.
        await db.rollback()
        continuation = {"state": "held", "child_run_id": binding["child_run_id"],
                        "receiver_session_id": binding["receiver_session_id"],
                        "reason": "Acceptance was recorded; child initialization needs attention."}
    safe_continuation = {key: continuation[key] for key in ("state", "child_run_id", "receiver_session_id")}
    if continuation["state"] == "held":
        safe_continuation["reason"] = "Acceptance was recorded; child initialization needs attention."
    return {"handoff": {"id": handoff_id, "state": "accepted", "payload_hash": preview["payload_hash"]},
            # Started means the engine initialized its cursor; it does not claim remote work completed.
            "continuation": safe_continuation}
