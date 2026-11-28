"""Compliance audit records (``/records``, ``/kinds``) for platform admins and, limited to their own Workspaces,
Workspace admins and owners."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....models.security.compliance_audit import ALL_AUDIT_EVENT_TYPES
from ....services.auth import get_current_user
from ....services.compliance_audit.service import list_audit_records
from ....services.compliance_audit.view import (
    AuditScope,
    InvalidCursorError,
    WorkspaceAdminRequiredError,
    audit_scope,
    decode_cursor,
    encode_cursor,
    serialize_records,
    visible_workspaces,
)

router = APIRouter(prefix="/api/v1/admin/compliance-audit", tags=["compliance-audit"])

API_KEY_SCOPE = "admin"
MAX_LIMIT = 200
_LIMIT = re.compile(r"[0-9]{1,3}")


def _invalid(code: str) -> HTTPException:
    return HTTPException(status_code=422, detail={"code": code})


async def _scope(request: Request, db: AsyncSession, user: User, workspace_id: str | None) -> AuditScope:
    # The Workspace answer comes first and alike for every caller, then the key's scope, then the query's syntax:
    # a Workspace the caller may not see never answers differently from an unknown one.
    via_key = hasattr(request.state, "api_key_id")
    bound = getattr(request.state, "api_key_project_id", None) if via_key else None
    try:
        scope = await audit_scope(db, user.id, workspace_id or None, bound_workspace_id=bound)
    except WorkspaceAdminRequiredError:
        raise HTTPException(status_code=403, detail={"code": "workspace_admin_required"}) from None
    scopes = {str(item).strip().lower() for item in getattr(request.state, "api_key_scopes", None) or []}
    if via_key and API_KEY_SCOPE not in scopes:
        raise HTTPException(status_code=403, detail={"code": "api_key_scope_required", "scope": API_KEY_SCOPE})
    return scope


def _time(value: str | None, code: str) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone(UTC).replace(tzinfo=None) if parsed.tzinfo else parsed
    except (ValueError, OverflowError):
        raise _invalid(code) from None


def _limit(value: str | None) -> int:
    if value is None:
        return 50
    if not _LIMIT.fullmatch(value) or not 1 <= int(value) <= MAX_LIMIT:
        raise _invalid("invalid_limit")
    return int(value)


@router.get("/records")
async def get_records(
    request: Request,
    workspace_id: str | None = None,
    event_type: str | None = None,
    since: str | None = None,
    until: str | None = None,
    cursor: str | None = None,
    limit: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    scope = await _scope(request, db, user, workspace_id)
    if event_type and event_type not in ALL_AUDIT_EVENT_TYPES:
        raise _invalid("unknown_event_type")
    page_size = _limit(limit)
    try:
        before = decode_cursor(cursor) if cursor is not None else None
    except InvalidCursorError:
        raise _invalid("invalid_cursor") from None
    records = await list_audit_records(
        db, project_ids=scope.project_ids, exclude_project_ids=scope.exclude_project_ids, event_type=event_type,
        since=_time(since, "invalid_since"), until=_time(until, "invalid_until"), before=before,
        limit=page_size + 1,
    )
    page = records[:page_size]
    return {
        "records": await serialize_records(db, page),
        "next_cursor": encode_cursor(page[-1]) if len(records) > page_size else None,
    }


@router.get("/kinds")
async def get_kinds(
    request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict:
    scope = await _scope(request, db, user, None)
    return {
        "event_types": sorted(ALL_AUDIT_EVENT_TYPES),
        "workspaces": await visible_workspaces(db, scope),
        "platform_admin": scope.platform_admin,
    }
