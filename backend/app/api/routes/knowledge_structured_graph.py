"""The Workspace's deterministic structured graph: builds, status, "Handbook vs. reality", profile.

Thin: authenticate, authorize the Workspace (an authoring role to request a build), delegate to
``services/knowledge/structured``. Every read resolves citations for the caller.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge.structured.build_states import TRIGGER_MANUAL
from app.services.knowledge.structured.profile_types import LAYERS, StructuredProfileError

from ...db import get_db
from ...models import User
from ...services.auth import get_current_user
from ...services.knowledge.access.authorization import (
    WORKSPACE_WRITE_FORBIDDEN_DETAIL,
    WorkspaceWriteForbiddenError,
    authorize_workspace,
)
from ...services.knowledge.ledger.errors import EvidenceLedgerError
from ...services.knowledge.structured.build import StructuredBuildRequestError, request_build
from ...services.knowledge.structured.config_report import MAX_LIMIT, handbook_vs_reality
from ...services.knowledge.structured.status import structured_status
from ...services.knowledge.structured.workspace_profile import (
    StructuredProfileConflictError,
    profile_settings,
    save_workspace_profile,
    validate_for_workspace,
)
from ._knowledge_evidence_http import evidence_http_error

PROFILE_CONFLICT_DETAIL = "structured profile: another save stored this revision first; reload and save again"

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/knowledge/graph/structured", tags=["workspace-knowledge"])


def _error(error: EvidenceLedgerError) -> HTTPException:
    return evidence_http_error(error)


class BuildRequest(BaseModel):
    # manual, configuration, operations; the build runs them in that order and links after all.
    layers: list[str] = Field(min_length=1, max_length=3)


@router.post("/builds", status_code=202)
async def request_structured_build(
    workspace_id: str,
    body: BuildRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        authorized = await authorize_workspace(
            db, current_user=current_user, workspace_id=workspace_id, require_author=True
        )
        build = await request_build(
            db, project_id=authorized.project_id, layers=body.layers, trigger=TRIGGER_MANUAL,
            requested_by=str(current_user.id),
        )
    except WorkspaceWriteForbiddenError:
        raise HTTPException(403, WORKSPACE_WRITE_FORBIDDEN_DETAIL) from None
    except StructuredBuildRequestError:
        raise HTTPException(422, "Unknown structured graph layer") from None
    except EvidenceLedgerError as error:
        raise _error(error) from None
    return {"workspace_id": authorized.project_id, "build": {"id": build.id, "state": build.state,
                                                             "layers": list(build.layers)}}


@router.get("")
async def get_structured_status(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        authorized = await authorize_workspace(db, current_user=current_user, workspace_id=workspace_id)
        return await structured_status(db, authorized=authorized)
    except EvidenceLedgerError as error:
        raise _error(error) from None


@router.get("/report")
async def get_handbook_vs_reality(
    workspace_id: str,
    parameter: str | None = Query(default=None, max_length=200),
    file: str | None = Query(default=None, max_length=200),
    section: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=MAX_LIMIT),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        authorized = await authorize_workspace(db, current_user=current_user, workspace_id=workspace_id)
        return await handbook_vs_reality(
            db, authorized=authorized, parameter=parameter, file=file, section=section, limit=limit
        )
    except EvidenceLedgerError as error:
        raise _error(error) from None


class ProfileBody(BaseModel):
    # A full profile document (the instance default's schema); ``null`` returns to the instance default.
    document: dict[str, Any] | None


@router.get("/profile")
async def get_structured_profile(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        authorized = await authorize_workspace(db, current_user=current_user, workspace_id=workspace_id)
        return await profile_settings(db, authorized.project_id, may_author=authorized.may_author)
    except EvidenceLedgerError as error:
        raise _error(error) from None


@router.post("/profile/validate")
async def validate_structured_profile(
    workspace_id: str,
    body: ProfileBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        authorized = await authorize_workspace(
            db, current_user=current_user, workspace_id=workspace_id, require_author=True
        )
        profile = await validate_for_workspace(db, authorized.project_id, body.document)
    except WorkspaceWriteForbiddenError:
        raise HTTPException(403, WORKSPACE_WRITE_FORBIDDEN_DETAIL) from None
    except StructuredProfileError as error:
        # The loader's message names the rule that failed, never document content.
        raise HTTPException(422, str(error)) from None
    except EvidenceLedgerError as error:
        raise _error(error) from None
    return {"valid": True, "profile_id": profile.profile_id}


@router.put("/profile")
async def put_structured_profile(
    workspace_id: str,
    body: ProfileBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Store the next profile revision (audited) and re-extract every layer under it."""
    try:
        authorized = await authorize_workspace(
            db, current_user=current_user, workspace_id=workspace_id, require_author=True
        )
        await save_workspace_profile(db, authorized.project_id, document=body.document,
                                     actor_id=str(current_user.id))
        build = await request_build(db, project_id=authorized.project_id, layers=list(LAYERS),
                                    trigger=TRIGGER_MANUAL, requested_by=str(current_user.id))
        settings = await profile_settings(db, authorized.project_id, may_author=True)
    except WorkspaceWriteForbiddenError:
        raise HTTPException(403, WORKSPACE_WRITE_FORBIDDEN_DETAIL) from None
    except StructuredProfileConflictError:
        raise HTTPException(409, PROFILE_CONFLICT_DETAIL) from None
    except StructuredProfileError as error:
        raise HTTPException(422, str(error)) from None
    except EvidenceLedgerError as error:
        raise _error(error) from None
    return {**settings, "build": {"id": build.id, "state": build.state, "layers": list(build.layers)}}
