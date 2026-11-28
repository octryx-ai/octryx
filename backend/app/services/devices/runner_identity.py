"""A server runner's calls act for the person whose active pool turn it runs, in that turn's Workspace only;
the runner account itself is a member of nothing."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User
from ...models.security.device import DEVICE_STATUS_ACTIVE, UserDevice
from ..data_access import as_viewer
from .runner_pool import RUNNER_ACCOUNT_TYPE, RUNNER_SERVICE_KIND, pool_allowed
from .runner_tenant import runner_turn_jobs


def is_runner_account(user: User | None) -> bool:
    return user is not None and getattr(user, "account_type", None) == RUNNER_ACCOUNT_TYPE


async def runner_turn_owner(db: AsyncSession, runner: User, *, grant_id: str, workspace_id: str,
                            session_key: str = "") -> User | None:
    if not is_runner_account(runner) or not workspace_id or not grant_id:
        return None
    device = (await db.execute(select(UserDevice).where(
        UserDevice.grant_id == grant_id, UserDevice.owner_user_id == runner.id,
        UserDevice.service_kind == RUNNER_SERVICE_KIND, UserDevice.status == DEVICE_STATUS_ACTIVE,
    ))).scalar_one_or_none()
    if device is None:
        return None
    # The turns are read past the viewer filter (a private Workspace's turn is invisible to the runner account);
    # the Workspace's pool switch is then read as the turn's owner.
    jobs = await runner_turn_jobs(db, device.id, workspace_id)
    named = [owner for owner, key in jobs if session_key and key == session_key]
    # Before the session reports its key, the turn is known only by its Workspace: unambiguous for one person alone.
    owners = set(named or [owner for owner, _key in jobs])
    if len(owners) != 1:
        return None
    owner = await db.get(User, owners.pop())
    if owner is None or not bool(getattr(owner, "is_active", True)):
        return None
    with as_viewer(owner.id):
        return owner if await pool_allowed(db, workspace_id) else None
