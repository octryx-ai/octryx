"""Whose turns a server runner holds, read past the viewer filter: the runner's account is a member of nothing, and its
turns may lie in a person's private Workspace. Narrow reads keyed to one device, never returned to a client."""

from __future__ import annotations

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import DeviceJob
from ...time_utils import utc_now
from .job_state import ACTIVE_STATUSES, OPEN_STATUSES, STATUS_CLOSED, STATUS_IDLE

REASON_SWITCHED = "runner_switched"


async def runner_tenants(db: AsyncSession, device_id: str, *, open_jobs: bool = False,
                         workspace_id: str | None = None) -> set[tuple[str, str | None]]:
    # (owner, Workspace) of the device's active (or open) jobs; the one-tenant-per-runner admission keeps it to one.
    table = DeviceJob.__table__
    statuses = OPEN_STATUSES if open_jobs else ACTIVE_STATUSES
    query = select(table.c.owner_user_id, table.c.workspace_id).where(
        table.c.device_id == device_id, table.c.status.in_(statuses))
    if workspace_id is not None:
        query = query.where(table.c.workspace_id == workspace_id)
    connection = await db.connection()
    return {(str(owner), str(workspace) if workspace else None) for owner, workspace in
            (await connection.execute(query)).all()}


async def runner_turn_jobs(db: AsyncSession, device_id: str, workspace_id: str) -> list[tuple[str, str | None]]:
    # (owner, launcher session key) of the device's active jobs in one Workspace.
    table = DeviceJob.__table__
    connection = await db.connection()
    rows = await connection.execute(select(table.c.owner_user_id, table.c.claude_session_id).where(
        table.c.device_id == device_id, table.c.workspace_id == workspace_id, table.c.status.in_(ACTIVE_STATUSES)))
    return [(str(owner), key) for owner, key in rows.all()]


async def runner_channel_viewer(db: AsyncSession, device_id: str) -> str | None:
    # The one person whose open turns the runner's channel delivers; None when it holds none (or, never, several).
    owners = {owner for owner, _workspace in await runner_tenants(db, device_id, open_jobs=True)}
    return owners.pop() if len(owners) == 1 else None


async def close_other_tenants(db: AsyncSession, device_id: str, *, owner_user_id: str,
                              workspace_id: str | None) -> None:
    # The launcher empties the runner when it switches person or Workspace, so the others' idle jobs end there; left
    # open, two owners would leave the channel reading as nobody. Their next turn resumes from the session snapshot.
    table = DeviceJob.__table__
    connection = await db.connection()
    await connection.execute(update(table).where(
        table.c.device_id == device_id, table.c.status == STATUS_IDLE,
        or_(table.c.owner_user_id != owner_user_id, table.c.workspace_id.is_distinct_from(workspace_id)),
    ).values(status=STATUS_CLOSED, status_reason=REASON_SWITCHED, finished_at=utc_now()))


__all__ = ["close_other_tenants", "runner_channel_viewer", "runner_tenants", "runner_turn_jobs"]
