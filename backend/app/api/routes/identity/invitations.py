from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....schemas.core.invitation import InvitationAcceptRequest, InvitationCreateRequest, InvitationResponse
from ....services.access_control import require_visible_workspace
from ....services.auth import get_current_user
from ....services.invitation import accept_invitation, create_invitation

router = APIRouter(prefix="/api/v1/invitations", tags=["invitations"])


@router.post("", response_model=InvitationResponse)
async def post_invitation(
    body: InvitationCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_visible_workspace(db, current_user.id, body.project_id)
    return await create_invitation(
        db,
        current_user=current_user,
        request=request,
        email=body.email,
        team_id=body.team_id,
        project_id=body.project_id,
        role=body.role,
        expires_in_hours=body.expires_in_hours,
    )


@router.post("/{token}/accept")
async def post_invitation_accept(
    token: str,
    body: InvitationAcceptRequest,
    db: AsyncSession = Depends(get_db),
):
    return await accept_invitation(
        db,
        token=token,
        username=body.username,
        password=body.password,
        display_name=body.display_name,
    )
