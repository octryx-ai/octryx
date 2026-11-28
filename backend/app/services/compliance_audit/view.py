"""What the admin compliance audit page reads: the caller's scope, the cursor and the rows as JSON."""

from __future__ import annotations

import base64
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Project, User
from ...models.security.compliance_audit import ComplianceAuditRecord
from ..access_control import _user_is_admin, workspace_not_found
from ..project.private_workspace import hidden_private_ids
from ..project.service import get_project_access_details
from .projection import project_details

ADMIN_ROLES = frozenset({"admin", "owner"})
MAX_CURSOR_LENGTH = 200


class WorkspaceAdminRequiredError(Exception):
    pass


class InvalidCursorError(Exception):
    pass


@dataclass(frozen=True)
class AuditScope:
    project_ids: list[str] | None
    exclude_project_ids: frozenset[str]
    platform_admin: bool


async def _administered_ids(db: AsyncSession, user_id: str) -> list[str]:
    access = await get_project_access_details(user_id, db)
    return sorted({str(item["id"]) for item in access if item.get("role") in ADMIN_ROLES})


async def audit_scope(
    db: AsyncSession, user_id: str, workspace_id: str | None, *, bound_workspace_id: str | None = None,
) -> AuditScope:
    if await _user_is_admin(db, user_id):
        hidden = frozenset(await hidden_private_ids(db, user_id))
        allowed = None if bound_workspace_id is None else [bound_workspace_id]
        if workspace_id:
            if (workspace_id in hidden or (allowed is not None and workspace_id not in allowed)
                    or await db.get(Project, workspace_id) is None):
                raise workspace_not_found()
            allowed = [workspace_id]
        return AuditScope(allowed, hidden, True)
    administered = await _administered_ids(db, user_id)
    if bound_workspace_id is not None:
        administered = [ws for ws in administered if ws == bound_workspace_id]
    if workspace_id:
        # Unknown, foreign and merely-a-member answer alike, so the page never confirms that a Workspace exists.
        if workspace_id not in administered:
            raise workspace_not_found()
        return AuditScope([workspace_id], frozenset(), False)
    if not administered:
        raise WorkspaceAdminRequiredError
    return AuditScope(administered, frozenset(), False)


async def visible_workspaces(db: AsyncSession, scope: AuditScope) -> list[dict[str, str]]:
    stmt = select(Project.id, Project.name).order_by(Project.name)
    if scope.project_ids is not None:
        stmt = stmt.where(Project.id.in_(scope.project_ids))
    rows = (await db.execute(stmt)).all()
    return [{"id": str(row.id), "name": row.name} for row in rows if str(row.id) not in scope.exclude_project_ids]


def encode_cursor(record: ComplianceAuditRecord) -> str:
    return base64.urlsafe_b64encode(f"{record.created_at.isoformat()}|{record.id}".encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    if not cursor or len(cursor) > MAX_CURSOR_LENGTH:
        raise InvalidCursorError
    try:
        decoded = base64.b64decode(cursor.encode("ascii"), altchars=b"-_", validate=True)
        if base64.urlsafe_b64encode(decoded).decode("ascii") != cursor:
            raise InvalidCursorError
        raw = decoded.decode("ascii")
        at_text, record_id = raw.split("|")
        at = datetime.fromisoformat(at_text)
        parsed_id = str(uuid.UUID(record_id))
    except (ValueError, UnicodeError) as error:
        raise InvalidCursorError from error
    # Only what encode_cursor emits: a naive UTC time (the column has no zone) and a canonical id.
    if at.tzinfo is not None or at.isoformat() != at_text or parsed_id != record_id:
        raise InvalidCursorError
    return at, record_id


async def _names(db: AsyncSession, model, ids: set[str], label) -> dict[str, str]:
    if not ids:
        return {}
    rows = (await db.execute(select(model).where(model.id.in_(ids)))).scalars().all()
    return {str(row.id): label(row) for row in rows}


async def serialize_records(db: AsyncSession, records: list[ComplianceAuditRecord]) -> list[dict]:
    workspaces = await _names(db, Project, {r.project_id for r in records if r.project_id}, lambda p: p.name)
    actors = await _names(db, User, {r.actor_user_id for r in records if r.actor_user_id},
                          lambda u: u.display_name or u.username)
    return [_row(r, workspaces, actors) for r in records]


def _row(r: ComplianceAuditRecord, workspaces: dict[str, str], actors: dict[str, str]) -> dict:
    shown, hidden = project_details(r)
    return {
        "id": r.id,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "event_type": r.event_type,
        "outcome": r.outcome,
        "workspace": {"id": r.project_id, "name": workspaces.get(r.project_id)} if r.project_id else None,
        "actor": {"id": r.actor_user_id, "display_name": actors.get(r.actor_user_id)} if r.actor_user_id else None,
        "actor_role": r.actor_role,
        "resource_type": r.resource_type,
        "resource_id": r.resource_id,
        "resource_name": r.resource_name,
        "details": shown,
        "hidden_field_count": hidden,
        "classification_level": r.classification_level,
        "request_id": r.request_id,
        "session_id": r.session_id,
    }
