"""Session episodes of one Workspace: platform sessions return what they learned."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import Session, User
from ....services.auth import get_current_user
from ....services.knowledge.access.authorization import (
    WORKSPACE_WRITE_FORBIDDEN_DETAIL,
    AuthorizedWorkspace,
    authorize_workspace,
)
from ....services.knowledge.episodes.policy import (
    episodes_accepted,
    platform_turn_capture_stored,
    public_origin,
    set_episode_policy,
)
from ....services.knowledge.episodes.writer import MAX_EPISODE_CHARS, EpisodeProvenance, record_episode_summary
from ....services.knowledge.ledger.errors import EvidenceLedgerError
from ._knowledge_evidence_http import evidence_http_error

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/knowledge/episodes", tags=["workspace-knowledge"])

PLATFORM_CLIENT = "platform"
SESSION_NOT_FOUND_DETAIL = "Session not found."
SETTINGS_REQUIRED_DETAIL = "Set accept_session_episodes, capture_platform_turns, or both."
STATUS_BY_STATE = {
    "denied": 403,
    "not_found": 404,
    "needs_configuration": 409,
    "invalid_request": 422,
    "limit_exceeded": 413,
    "unavailable": 503,
}


class EpisodeRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=36)
    summary: str = Field(min_length=1, max_length=MAX_EPISODE_CHARS)
    title: str | None = Field(default=None, max_length=300)
    products: list[str] | None = None
    version: str | None = Field(default=None, max_length=40)


class EpisodeSettingsRequest(BaseModel):
    # Each switch is optional, so a client can change one without restating the other; at least one is required.
    accept_session_episodes: bool | None = None
    capture_platform_turns: bool | None = None


async def _authorized(db: AsyncSession, user: User, workspace_id: str) -> AuthorizedWorkspace:
    try:
        return await authorize_workspace(db, current_user=user, workspace_id=workspace_id)
    except EvidenceLedgerError as error:
        raise evidence_http_error(error) from None


async def _settings(db: AsyncSession, authorized: AuthorizedWorkspace) -> dict:
    return {
        "workspace_id": authorized.project_id,
        "may_author": authorized.may_author,
        "accept_session_episodes": await episodes_accepted(db, authorized.project_id),
        # Automatic capture runs only when this and accept_session_episodes are both on.
        "capture_platform_turns": await platform_turn_capture_stored(db, authorized.project_id),
        "public_origin_configured": public_origin() is not None,
    }


@router.post("")
async def record_workspace_episode(
    workspace_id: str,
    body: EpisodeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    authorized = await _authorized(db, current_user, workspace_id)
    session = await db.get(Session, body.session_id)
    if session is None or session.user_id != current_user.id or session.project_id != authorized.project_id:
        raise HTTPException(status_code=404, detail=SESSION_NOT_FOUND_DETAIL)
    result = await record_episode_summary(
        db,
        authorized=authorized,
        provenance=EpisodeProvenance(
            session_id=str(session.id),
            client=PLATFORM_CLIENT,
            recorded_by=str(current_user.id),
            session_date=session.started_at.date().isoformat() if session.started_at else "",
        ),
        summary=body.summary,
        title=body.title,
        products=body.products,
        version=body.version,
    )
    state = str(result.get("state"))
    if state not in {"recorded", "duplicate"}:
        raise HTTPException(status_code=STATUS_BY_STATE.get(state, 502), detail=str(result.get("error")))
    await db.commit()
    return result


@router.get("/settings")
async def get_workspace_episode_settings(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await _settings(db, await _authorized(db, current_user, workspace_id))


@router.put("/settings")
async def set_workspace_episode_settings(
    workspace_id: str,
    body: EpisodeSettingsRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    authorized = await _authorized(db, current_user, workspace_id)
    if not authorized.may_author:
        raise HTTPException(status_code=403, detail=WORKSPACE_WRITE_FORBIDDEN_DETAIL)
    if body.accept_session_episodes is None and body.capture_platform_turns is None:
        raise HTTPException(status_code=422, detail=SETTINGS_REQUIRED_DETAIL)
    await set_episode_policy(
        db,
        authorized.project_id,
        accepted=body.accept_session_episodes,
        capture_platform_turns=body.capture_platform_turns,
        actor_id=str(current_user.id),
    )
    await db.commit()
    return await _settings(db, authorized)
