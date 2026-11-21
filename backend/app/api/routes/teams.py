from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import User
from ...schemas.core.team import TeamCreateRequest, TeamMemberAddRequest, TeamProjectGrantRequest, TeamResponse
from ...services.access_control import require_project_access
from ...services.auth import get_current_user
from ...services.team_notification import add_team_member, create_team, grant_team_project, list_teams

router = APIRouter(prefix="/api/v1/teams", tags=["teams"])


@router.get("", response_model=list[TeamResponse])
async def get_teams(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_teams(db, current_user)


@router.post("", response_model=TeamResponse)
async def post_team(
    body: TeamCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await create_team(
        db,
        current_user=current_user,
        name=body.name,
        description=body.description,
        avatar_url=body.avatar_url,
    )


@router.post("/{team_id}/members", response_model=TeamResponse)
async def post_team_member(
    team_id: str,
    body: TeamMemberAddRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await add_team_member(
        db,
        team_id=team_id,
        current_user=current_user,
        user_id=body.user_id,
        role=body.role,
    )


@router.post("/{team_id}/projects", response_model=TeamResponse)
async def post_team_project(
    team_id: str,
    body: TeamProjectGrantRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_project_access(db, current_user.id, body.project_id)
    return await grant_team_project(
        db,
        team_id=team_id,
        current_user=current_user,
        project_id=body.project_id,
        role=body.role,
    )
