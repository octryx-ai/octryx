"""Full session transcripts (behind a Workspace switch): the switch and the transcript view. Transport only.

- ``GET /api/v1/workspaces/{project_id}/agent-gateway/session-transcripts`` (members) →
  ``{project_id, session_transcripts: {enabled, retention_days}, source, can_edit}``; ``source`` is ``workspace``
  or ``default`` (off, 30 days).
- ``PUT`` the same path with ``{enabled?, retention_days?}`` (Workspace admin/owner or platform admin; 403
  otherwise) → the GET shape; audited (``admin.agent_gateway.session_transcripts_updated``). Invalid values: 422
  ``{"detail": {"errors": [{"code", "field"}]}}``.
- ``GET /api/v1/workspaces/{project_id}/session-transcripts?session_id=&workflow_run_id=&device_job_id=`` →
  ``{items: [{session_id, owner_user_id, claude_session_ids, workflow_run_id, device_job_id, first_at, last_at,
  bytes_stored, streams: [{stream, lines, first_line, last_line}]}]}``: admins and owners see every session, others
  their own.
- ``GET /api/v1/session-transcripts/{session_id}?stream=main&from_line=1&limit=200`` → one redacted page
  ``{session_id, project_id, owner_user_id, stream, streams, lines: [{line, entry}], next_from_line, redacted}``;
  Workspace admins/owners and the session's owner only, audited per page (``session_transcript.read``).

A non-member, or a reader who may not see the transcript, gets 404, exactly like a missing one.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import Project, User
from ...services.agent_gateway.transcript_policy import set_workspace_transcript_policy
from ...services.agent_gateway.transcript_policy_keys import TranscriptPolicyError, transcript_policy_from_config
from ...services.auth import get_current_user
from ...services.session_transcripts.access import (
    DEFAULT_PAGE_LINES,
    MAX_PAGE_LINES,
    TranscriptAccessError,
    list_transcripts,
    read_page,
    viewer_for,
)
from ...services.session_transcripts.store import STREAM_MAIN

router = APIRouter(tags=["session-transcripts"])
POLICY_PATH = "/api/v1/workspaces/{project_id}/agent-gateway/session-transcripts"


def _http(error: TranscriptAccessError) -> HTTPException:
    return HTTPException(status_code=error.status, detail={"reason": error.reason})


async def _workspace(db: AsyncSession, user: User, project_id: str, *, write: bool) -> tuple[Project, bool]:
    try:
        viewer = await viewer_for(db, user, project_id)
    except TranscriptAccessError as error:
        raise _http(error) from None
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail={"reason": "workspace_not_found"})
    if write and not viewer.workspace_admin:
        raise HTTPException(status_code=403, detail="Workspace admin or owner role required")
    return project, viewer.workspace_admin


def _payload(project: Project, can_edit: bool) -> dict[str, Any]:
    policy, source = transcript_policy_from_config(project.config)
    return {"project_id": project.id, "session_transcripts": policy.as_dict(), "source": source,
            "can_edit": can_edit}


@router.get(POLICY_PATH)
async def get_transcript_policy(
    project_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    project, can_edit = await _workspace(db, current_user, project_id, write=False)
    return _payload(project, can_edit)


@router.put(POLICY_PATH)
async def put_transcript_policy(
    project_id: str,
    body: dict[str, Any] = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    project, can_edit = await _workspace(db, current_user, project_id, write=True)
    current, _source = transcript_policy_from_config(project.config)
    try:  # a PUT may set one field; the other keeps its current value
        await set_workspace_transcript_policy(db, project=project, value={**current.as_dict(), **body},
                                              actor_id=current_user.id)
    except TranscriptPolicyError as error:
        raise HTTPException(status_code=422,
                            detail={"errors": [{"code": error.reason, "field": error.path}]}) from None
    await db.commit()
    await db.refresh(project)
    return _payload(project, can_edit)


@router.get("/api/v1/workspaces/{project_id}/session-transcripts")
async def get_workspace_transcripts(
    project_id: str,
    session_id: str = Query(default="", max_length=36),
    workflow_run_id: str = Query(default="", max_length=36),
    device_job_id: str = Query(default="", max_length=40),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        viewer = await viewer_for(db, current_user, project_id)
    except TranscriptAccessError as error:
        raise _http(error) from None
    items = await list_transcripts(db, viewer=viewer, project_id=project_id, session_id=session_id,
                                   workflow_run_id=workflow_run_id, device_job_id=device_job_id)
    return {"project_id": project_id, "items": items}


@router.get("/api/v1/session-transcripts/{session_id}")
async def get_session_transcript(
    session_id: str,
    stream: str = Query(default=STREAM_MAIN, max_length=80),
    from_line: int = Query(default=1, ge=1),
    limit: int = Query(default=DEFAULT_PAGE_LINES, ge=1, le=MAX_PAGE_LINES),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        return await read_page(db, user=current_user, session_id=session_id, stream=stream, from_line=from_line,
                               limit=limit)
    except TranscriptAccessError as error:
        raise _http(error) from None


__all__ = ["router"]
