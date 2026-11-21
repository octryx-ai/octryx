"""Databases page: audited removal and the recent queries by agents.

* **Remove** is refused (409 ``database_in_use``) while query tools still use the database; then it writes
  an audit row (name, type, query tools, how many queries were recorded),
  deletes the connector with its query tools and query history, then releases the stored password
  or DSN when nothing else references it.
* **Recent queries**: the last runs of query tools, in words: tool, database, who or which run,
  rows (and whether the limit cut the answer), outcome.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import DatabaseConnector, DatabaseQueryTool, Project, User
from ...models.runtime.database_connector import DatabaseQueryToolRun
from ...time_utils import ensure_utc
from ..admin.governance.admin_config_audit_service import record_admin_config_audit
from ..secret.release import config_secret_refs, release_unreferenced_secrets

STATE_DATABASE_IN_USE = "database_in_use"


async def remove_database(db: AsyncSession, *, connector_id: str, actor_user_id: str | None) -> dict[str, Any]:
    connector = await db.get(DatabaseConnector, connector_id)
    if connector is None:
        raise HTTPException(status_code=404, detail="Database connector not found")
    tools = (
        await db.execute(select(DatabaseQueryTool.tool_name).where(DatabaseQueryTool.connector_id == connector_id))
    ).scalars().all()
    if tools:
        # Like a connector: a database that agents can still query through its tools is not removed.
        raise HTTPException(status_code=409, detail={
            "code": STATE_DATABASE_IN_USE,
            "message": "Agents still use it through its query tools. Delete them first, or pause the database.",
            "query_tools": list(tools),
        })
    run_count = int(
        (
            await db.execute(
                select(func.count()).select_from(DatabaseQueryToolRun)
                .where(DatabaseQueryToolRun.connector_id == connector_id)
            )
        ).scalar_one()
    )
    secret_ids = config_secret_refs(dict(connector.connection_config or {}))
    record_admin_config_audit(
        db,
        actor_user_id=actor_user_id,
        action="admin.database_connector.deleted",
        resource_type="database_connector",
        resource_id=connector_id,
        before={"name": connector.name, "db_type": connector.db_type, "is_active": bool(connector.is_active)},
        after={},
        details={"name": connector.name, "query_tools": list(tools), "recorded_queries": run_count},
    )
    await db.execute(delete(DatabaseQueryToolRun).where(DatabaseQueryToolRun.connector_id == connector_id))
    await db.execute(delete(DatabaseQueryTool).where(DatabaseQueryTool.connector_id == connector_id))
    await db.delete(connector)
    await db.flush()
    released = await release_unreferenced_secrets(db, secret_ids)
    await db.commit()
    return {"status": "deleted", "stored_entries": released.to_payload()}


async def recent_query_runs(db: AsyncSession, *, limit: int = 20) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(DatabaseQueryToolRun, DatabaseQueryTool.display_name, User.username, Project.name)
            .outerjoin(DatabaseQueryTool, DatabaseQueryTool.id == DatabaseQueryToolRun.query_tool_id)
            .outerjoin(User, User.id == DatabaseQueryToolRun.actor_user_id)
            .outerjoin(Project, Project.id == DatabaseQueryToolRun.project_id)
            .order_by(DatabaseQueryToolRun.started_at.desc())
            .limit(max(1, min(limit, 100)))
        )
    ).all()
    return [
        {
            "id": run.id,
            "tool": display or run.tool_name,
            "database": run.connector_name,
            "db_type": run.db_type,
            "status": run.status,
            "failure_category": run.failure_category or "",
            "rows": int(run.row_count or 0),
            "limit_reached": bool(run.max_rows and run.row_count >= run.max_rows),
            "who": username or "",
            "workspace": workspace or "",
            "session_id": run.session_id,
            "started_at": ensure_utc(run.started_at).isoformat() if run.started_at else None,
        }
        for run, display, username, workspace in rows
    ]


__all__ = ["STATE_DATABASE_IN_USE", "recent_query_runs", "remove_database"]
