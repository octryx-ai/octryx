"""``/api/v1`` session turn routes: send a message (one turn) and stop the running turn. A refusal answers with the
shared status and a closed ``code`` a client can branch on."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....schemas.operations.session import MessageCreate, MessageResponse, SessionResponse
from ....services.auth import get_current_user
from ....services.session.api import stop_session_turn_response
from ....services.session.message_dispatch import send_session_message
from ....services.session.turn_refusals import TurnRefusal

router = APIRouter()


def api_refusal_http_exception(refusal: TurnRefusal) -> HTTPException:
    return HTTPException(
        status_code=refusal.http_status, detail={"code": refusal.state.value, "detail": refusal.detail}
    )


@router.post("/{session_id}/messages", response_model=list[MessageResponse])
async def send_message(
    session_id: str,
    body: MessageCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await send_session_message(
        db,
        session_id=session_id,
        content=body.content,
        user_id=current_user.id,
        workflow_key=body.workflow_key,
        workflow_decisions=body.workflow_decisions,
        runtime_target_id=body.runtime_target_id,
        thinking_level=body.thinking_level,
        agent_id=body.agent_id,
        person_chat=True,
    )
    if isinstance(result, TurnRefusal):
        raise api_refusal_http_exception(result)
    return result


@router.post("/{session_id}/stop", response_model=SessionResponse)
async def stop_session_turn(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await stop_session_turn_response(db=db, session_id=session_id, user_id=current_user.id)
