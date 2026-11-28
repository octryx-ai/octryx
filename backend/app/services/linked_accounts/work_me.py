""""You in Jira" for a Workspace's "My work": an explicit choice, never matched by email or name."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User
from ...models.runtime.secure_work import WorkItem
from .contract import ATLASSIAN, JIRA_SERVER, LinkedAccountError
from .store import account_row, identifier_of, remove_account, save_account

SOURCE_TYPE = "jira"


async def _platform(db: AsyncSession, workspace_id: str) -> str:
    instances = (await db.execute(select(WorkItem.source_instance).where(
        WorkItem.project_id == workspace_id, WorkItem.source_type == SOURCE_TYPE).distinct().limit(20))).scalars()
    hosts = [str(value or "").lower() for value in instances]
    return JIRA_SERVER if hosts and not any("atlassian.net" in host for host in hosts) else ATLASSIAN


def _view(account_id: str | None, display_name: str | None) -> dict[str, Any]:
    return {"source_type": SOURCE_TYPE, "account_id": account_id or None, "display_name": display_name or None}


async def _display(db: AsyncSession, workspace_id: str, account_id: str) -> str | None:
    rows = (await db.execute(select(WorkItem.source_fields_json).where(
        WorkItem.project_id == workspace_id, WorkItem.assignee == account_id).limit(5))).scalars()
    for fields in rows:
        person = dict(dict(dict(fields or {}).get("people") or {}).get("assignee") or {})
        if person.get("display"):
            return str(person["display"])[:255]
    return None


async def read_me(db: AsyncSession, user: User, workspace_id: str) -> dict[str, Any]:
    row = await account_row(db, user.id, await _platform(db, workspace_id))
    return _view(identifier_of(row), row.display_name if row is not None else None)


async def choose_me(db: AsyncSession, user: User, workspace_id: str, account_id: str) -> dict[str, Any]:
    account_id = str(account_id or "").strip()
    known = (await db.execute(select(WorkItem.id).where(
        WorkItem.project_id == workspace_id, WorkItem.source_type == SOURCE_TYPE, WorkItem.assignee == account_id,
    ).limit(1))).first()
    if not account_id or known is None:
        raise LinkedAccountError("unknown_jira_account",
                                 "This account is not an assignee of this Workspace's Jira items.", 422)
    display = await _display(db, workspace_id, account_id)
    await save_account(db, user_id=user.id, platform_key=await _platform(db, workspace_id),
                       identifier=account_id, display_name=display, actor_id=user.id)
    return _view(account_id, display)


async def clear_me(db: AsyncSession, user: User, workspace_id: str) -> dict[str, Any]:
    await remove_account(db, user_id=user.id, platform_key=await _platform(db, workspace_id), actor_id=user.id)
    return _view(None, None)


__all__ = ["SOURCE_TYPE", "choose_me", "clear_me", "read_me"]
