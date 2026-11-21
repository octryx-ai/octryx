from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...schemas.operations.coordinator import (
    CoordinatorControlAction,
    CoordinatorControlResponse,
    CoordinatorStateContract,
)
from ..coordinator_contract import load_coordinator_state_contract
from ..coordinator_control import apply_coordinator_control
from .collaboration import require_session_access


async def get_session_coordinator_state_response(
    db: AsyncSession,
    *,
    session_id: str,
    user_id: str,
) -> CoordinatorStateContract:
    await require_session_access(db, session_id=session_id, user_id=user_id)
    payload = await load_coordinator_state_contract(db, session_id=session_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return payload


async def apply_session_coordinator_control_response(
    db: AsyncSession,
    *,
    session_id: str,
    user_id: str,
    action: CoordinatorControlAction,
) -> CoordinatorControlResponse:
    payload = await apply_coordinator_control(
        db,
        session_id=session_id,
        user_id=user_id,
        action=action,
    )
    return CoordinatorControlResponse(action=action, contract=payload)
