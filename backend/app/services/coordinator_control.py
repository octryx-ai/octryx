from __future__ import annotations

import logging

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Session
from ..schemas.operations.coordinator import CoordinatorControlAction, CoordinatorStateContract
from .coordinator_contract import load_coordinator_state_contract
from .session.collaboration import require_session_access
from .session.run_state import (
    get_session_run_completion_reason,
)
from .session.stream import session_stream_manager
from .session.turn_stop import stop_session_turn

logger = logging.getLogger(__name__)

_STOP_UNSUPPORTED_DETAIL = "Coordinator stop is only supported for direct parent-session runs in phase 1."


async def apply_coordinator_control(
    db: AsyncSession,
    *,
    session_id: str,
    user_id: str,
    action: CoordinatorControlAction,
) -> CoordinatorStateContract:
    await require_session_access(db, session_id=session_id, user_id=user_id, require_write=True)
    contract = await load_coordinator_state_contract(db, session_id=session_id)
    if contract is None:
        raise HTTPException(status_code=404, detail="Session not found")

    root_session, _ = await require_session_access(
        db,
        session_id=contract.root_session_id,
        user_id=user_id,
        require_write=True,
    )
    if str(root_session.status or "").strip().lower() == "archived":
        raise HTTPException(status_code=409, detail="Archived threads must be restored before coordinator control")

    if action == "stop":
        return await _stop_coordinator_contract(db, contract=contract, root_session=root_session)
    raise HTTPException(status_code=400, detail="Unsupported coordinator control action")


async def _stop_coordinator_contract(
    db: AsyncSession,
    *,
    contract: CoordinatorStateContract,
    root_session: Session,
) -> CoordinatorStateContract:
    if not contract.can_stop:
        raise HTTPException(status_code=409, detail="Coordinator session cannot stop in its current state")
    if contract.coordinator_mode not in {"direct", "deterministic_workflow"}:
        raise HTTPException(status_code=409, detail=_STOP_UNSUPPORTED_DETAIL)

    await stop_session_turn(db, root_session)

    refreshed = await load_coordinator_state_contract(db, session_id=root_session.id)
    if refreshed is None:
        raise HTTPException(status_code=404, detail="Session not found")
    await _publish_coordinator_run_state(
        root_session.id,
        contract=refreshed,
        run_status=refreshed.run_status,
        run_completion_reason=get_session_run_completion_reason(root_session) or refreshed.run_completion_reason or "",
    )
    return refreshed


async def _publish_coordinator_run_state(
    session_id: str,
    *,
    contract: CoordinatorStateContract,
    run_status: str,
    run_completion_reason: str,
) -> None:
    await session_stream_manager.publish(
        session_id,
        "run_state",
        {
            "runStatus": str(run_status or "").strip().lower(),
            "runCompletionReason": str(run_completion_reason or "").strip().lower(),
            "notificationScope": "coordinator",
            "rootSessionId": contract.root_session_id,
            "coordinatorMode": contract.coordinator_mode,
        },
    )


__all__ = ["apply_coordinator_control"]
