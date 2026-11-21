"""Jira intake fixtures through the intake's own store and runner (``jira_sync_config``, ``jira_sync``).

The setup API (``/workspaces/{project_id}/intake``) stores a draft through the same store; these helpers let a test
save any filters and options and run the sync with injected ``issues``. Each call commits, like a request would.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.models import User
from app.services.named_connections.contract import DEFAULT_CONNECTION_NAME
from app.services.secure_work.jira.jira_sync import run_jira_work_item_sync
from app.services.secure_work.jira.jira_sync_config import create_jira_sync_config, update_jira_sync_config


async def intake_user(db, username: str = "admin") -> User:
    return (await db.execute(select(User).where(User.username == username))).scalar_one()


async def create_jira_intake(db, payload: dict[str, Any], *, user: User | None = None) -> dict[str, Any]:
    """Save a Jira intake (``connection_id`` defaults to the Workspace's default connection)."""
    created = await create_jira_sync_config(db, current_user=user or await intake_user(db),
                                            payload={"connection_id": DEFAULT_CONNECTION_NAME, **payload})
    await db.commit()
    return created


async def update_jira_intake(db, config_id: str, payload: dict[str, Any], *, user: User | None = None
                             ) -> dict[str, Any]:
    updated = await update_jira_sync_config(db, config_id=config_id, current_user=user or await intake_user(db),
                                            payload=payload)
    await db.commit()
    return updated


async def run_jira_intake(db, config_id: str, payload: dict[str, Any] | None = None, *, dry_run: bool = False,
                          user: User | None = None) -> dict[str, Any]:
    """One sync (or dry run) of the intake with the given runner payload (e.g. injected ``issues``)."""
    result = await run_jira_work_item_sync(db, config_id=config_id, current_user=user or await intake_user(db),
                                           payload=payload or {}, dry_run=dry_run)
    await db.commit()
    return result


__all__ = ["create_jira_intake", "intake_user", "run_jira_intake", "update_jira_intake"]
