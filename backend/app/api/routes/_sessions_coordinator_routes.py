from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import User
from ...schemas.operations.coordinator import (
    CoordinatorControlRequest,
    CoordinatorControlResponse,
    CoordinatorStateContract,
)
from ...services.auth import get_current_user
from ...services.session.coordinator import (
    apply_session_coordinator_control_response,
    get_session_coordinator_state_response,
)

router = APIRouter()


@router.get("/{session_id}/coordinator-status", response_model=CoordinatorStateContract)
async def get_session_coordinator_status(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await get_session_coordinator_state_response(
        db,
        session_id=session_id,
        user_id=current_user.id,
    )


@router.post("/{session_id}/coordinator-control", response_model=CoordinatorControlResponse)
async def post_session_coordinator_control(
    session_id: str,
    body: CoordinatorControlRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await apply_session_coordinator_control_response(
        db,
        session_id=session_id,
        user_id=current_user.id,
        action=body.action,
    )
