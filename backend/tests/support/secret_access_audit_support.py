from __future__ import annotations

import json
import uuid

from sqlalchemy import select

from app.models import Project, SecretAccessAuditLog, StoredSecret, User
from app.services.project.private_workspace import ensure_private_workspace
from app.services.secret import set_secret_value
from tests.devices.device_support import user_named

VALUE = "sk-synthetic-audit-value-QXZW-kmpr"


async def owner_and_workspace(db) -> tuple[User, Project]:
    owner = await user_named(db, f"audit-owner-{uuid.uuid4().hex[:8]}")
    return owner, await ensure_private_workspace(db, owner)


async def stored(db, *, tool_name: str, field_name: str, project_id: str | None, value: str = VALUE) -> StoredSecret:
    return await set_secret_value(db, tool_name=tool_name, field_name=field_name, project_id=project_id, value=value)


async def reads_of(db, *, secret_id: str | None = None, entity_id: str | None = None) -> list[SecretAccessAuditLog]:
    statement = select(SecretAccessAuditLog).order_by(SecretAccessAuditLog.created_at)
    if secret_id is not None:
        statement = statement.where(SecretAccessAuditLog.secret_id == secret_id)
    if entity_id is not None:
        statement = statement.where(SecretAccessAuditLog.entity_id == entity_id)
    return list((await db.execute(statement)).scalars())


def assert_holds_no_value(row: SecretAccessAuditLog, value: str = VALUE) -> None:
    for column in SecretAccessAuditLog.__table__.columns:
        text = json.dumps(getattr(row, column.key), default=str)
        for start in range(len(value) - 5):
            assert value[start:start + 6] not in text, column.key


async def assert_read_once(db, *, secret_id: str, purpose: str, workspace_id: str | None,
                           user: User | None = None) -> SecretAccessAuditLog:
    [row] = await reads_of(db, secret_id=secret_id)
    assert (row.action, row.outcome, row.purpose, row.project_id) == ("read", "success", purpose, workspace_id)
    if user is not None:
        assert (row.principal, row.actor_user_id) == (f"user:{user.id}", user.id)
    assert_holds_no_value(row)
    return row
