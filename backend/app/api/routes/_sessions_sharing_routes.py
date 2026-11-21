"""The live stream of a session and its sharing: collaborators, handovers and access grants.

Included into the ``/api/v1/sessions`` router by ``sessions.py``; this router has no prefix of its own.
"""

from fastapi import APIRouter, Depends, HTTPException, WebSocket
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import User
from ...schemas.operations.session import (
    SessionAccessGrant,
    SessionAccessGrantResponse,
    SessionCollaboratorCreate,
    SessionCollaboratorResponse,
    SessionHandoverCreate,
    SessionHandoverRespond,
    SessionHandoverResponse,
    SessionStreamTokenResponse,
)
from ...services.auth import get_current_user
from ...services.session.api import create_stream_token_response
from ...services.session.collaboration import (
    add_session_collaborator,
    create_session_handover,
    get_session_access_role,
    list_session_collaborators,
    respond_to_session_handover,
)
from ...services.session.stream import serve_session_stream_websocket
from ...services.session_access_service import grant_session_access, require_grant_authority, revoke_session_access

router = APIRouter()


@router.websocket("/{session_id}/ws")
async def session_stream_ws(
    session_id: str,
    websocket: WebSocket,
    db: AsyncSession = Depends(get_db),
):
    await serve_session_stream_websocket(db=db, session_id=session_id, websocket=websocket)


@router.get("/{session_id}/stream-token", response_model=SessionStreamTokenResponse)
async def get_session_stream_token(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await create_stream_token_response(db=db, session_id=session_id, user_id=current_user.id)


@router.get("/{session_id}/collaborators", response_model=list[SessionCollaboratorResponse])
async def get_session_collaborators(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_session_collaborators(db, session_id=session_id, current_user=current_user)


@router.post("/{session_id}/collaborators", response_model=SessionCollaboratorResponse)
async def post_session_collaborator(
    session_id: str,
    body: SessionCollaboratorCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await add_session_collaborator(
        db,
        session_id=session_id,
        current_user=current_user,
        target_user_id=body.user_id,
        role=body.role,
    )


@router.post("/{session_id}/handovers", response_model=SessionHandoverResponse)
async def post_session_handover(
    session_id: str,
    body: SessionHandoverCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await create_session_handover(
        db,
        session_id=session_id,
        current_user=current_user,
        to_user_id=body.to_user_id,
        reason=body.reason,
        context_summary=body.context_summary,
    )


@router.post("/handovers/{handover_id}/respond", response_model=SessionHandoverResponse)
async def post_session_handover_response(
    handover_id: str,
    body: SessionHandoverRespond,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await respond_to_session_handover(
        db,
        handover_id=handover_id,
        current_user=current_user,
        action=body.action,
    )


@router.get("/{session_id}/access", response_model=SessionAccessGrantResponse)
async def get_session_access(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the requesting user's access role for a session."""
    role = await get_session_access_role(db, session_id=session_id, user_id=current_user.id)
    if role is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionAccessGrantResponse(session_id=session_id, access_scope=role)


@router.post("/{session_id}/access", response_model=SessionAccessGrantResponse)
async def post_session_access(
    session_id: str,
    body: SessionAccessGrant,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Grant a user explicit read access to a session (overrides project mode)."""
    await require_grant_authority(db, session_id=session_id, user_id=current_user.id)
    scope = str(body.access_scope or "read").strip().lower()
    if scope not in {"read", "read_write", "admin"}:
        raise HTTPException(status_code=400, detail="Invalid access scope")
    grant = await grant_session_access(
        db,
        session_id=session_id,
        target_user_id=body.user_id,
        scope=scope,
        granted_by=current_user.id,
        expires_at=body.expires_at,
        metadata=body.metadata,
    )
    return SessionAccessGrantResponse(
        session_id=session_id,
        user_id=grant.user_id,
        access_scope=grant.access_scope,
        granted_by=grant.granted_by,
        expires_at=grant.expires_at.isoformat() if grant.expires_at else None,
    )


@router.delete("/{session_id}/access/{target_user_id}", status_code=204)
async def delete_session_access(
    session_id: str,
    target_user_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke a user's explicit access to a session."""
    await require_grant_authority(db, session_id=session_id, user_id=current_user.id)
    await revoke_session_access(db, session_id=session_id, target_user_id=target_user_id)
