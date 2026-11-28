"""Server runners: devices of one technical account that enroll with the join secret and serve every Workspace
allowing them; a pool turn keeps its thread's runner while it is free, else takes the least busy one."""

from __future__ import annotations

import hmac
import secrets
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Project, Session, User
from ...models.security.device import DEVICE_STATUS_ACTIVE, UserDevice

POOL_DEVICE_ID = "pool"
RUNNER_SERVICE_KIND = "runner"
RUNNER_ACCOUNT_TYPE = "runner_service"
RUNNER_USERNAME = "octryx-runner"
RUNNER_ROOT = "/workspace"
WORKSPACE_SWITCH = "server_runners"
SWITCH_FORBIDDEN = "forbidden"
REASON_POOL_EMPTY = "runner_pool_unavailable"
REASON_POOL_NOT_SET_UP = "runner_pool_not_set_up"
REASON_POOL_FORBIDDEN = "server_runners_forbidden"
REASON_ENROLL_DISABLED = "runner_enrollment_not_configured"
REASON_ENROLL_REFUSED = "runner_join_secret_invalid"
REASON_RUNTIME_MISMATCH = "runner_runtime_mismatch"
ASK_FIRST = "default"  # the chat's "Ask first", sent as no mode: Claude Code's default
_EMAIL_DOMAIN = "runner.octryx.invalid"


class RunnerEnrollError(Exception):
    def __init__(self, reason: str, status: int) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status = status


@dataclass(frozen=True)
class PoolChoice:
    device: UserDevice
    folder: str


async def runner_account(db: AsyncSession, *, create: bool = False) -> User | None:
    user = (await db.execute(select(User).where(User.username == RUNNER_USERNAME))).scalar_one_or_none()
    if user is not None and user.account_type != RUNNER_ACCOUNT_TYPE:
        raise RunnerEnrollError("runner_account_conflict", 409)
    if user is None and create:
        from ..auth import hash_password  # noqa: PLC0415

        user = User(id=str(uuid.uuid4()), username=RUNNER_USERNAME, email=f"{RUNNER_USERNAME}@{_EMAIL_DOMAIN}",
                    password_hash=hash_password(secrets.token_urlsafe(48)), auth_source=RUNNER_ACCOUNT_TYPE,
                    account_type=RUNNER_ACCOUNT_TYPE, display_name="Server runner", is_active=True)
        db.add(user)
        await db.flush()
    return user


def join_secret_matches(offered: str, configured: str) -> bool:
    if not configured:
        raise RunnerEnrollError(REASON_ENROLL_DISABLED, 503)
    return hmac.compare_digest(offered.encode(), configured.encode())


async def enroll_runner(db: AsyncSession, *, join_secret: str, configured_secret: str, client_id: str,
                        body: dict[str, Any], runtime: str = "", required_runtime: str = "") -> Any:
    from .credential import DEVICE_JOB_SCOPES  # noqa: PLC0415
    from .registry import register_device  # noqa: PLC0415

    if not join_secret or not join_secret_matches(join_secret, configured_secret):
        raise RunnerEnrollError(REASON_ENROLL_REFUSED, 403)
    if not client_id:
        raise RunnerEnrollError("runner_client_required", 422)
    # The installation names the container runtime its runners must run on (gVisor); no runner joins on another.
    if required_runtime and runtime != required_runtime:
        raise RunnerEnrollError(REASON_RUNTIME_MISMATCH, 409)
    account = await runner_account(db, create=True)
    assert account is not None
    fields = {**body, "service_kind": RUNNER_SERVICE_KIND, "folders": [RUNNER_ROOT],
              "profiles_available": ["governed"], "os": "linux"}
    registration = await register_device(db, owner_user_id=account.id, client_id=client_id,
                                         login_scopes=sorted(DEVICE_JOB_SCOPES), body=fields)
    registration.device.runtime = runtime[:40] or None
    return registration


def on_required_runtime(device: UserDevice) -> bool:
    # Checked at every pick as well: a runner enrolled before the installation required gVisor never takes a turn.
    from ...config import get_settings  # noqa: PLC0415

    return (device.runtime or "") == get_settings().runner_runtime


async def is_pool_runner(db: AsyncSession, device: UserDevice | None) -> bool:
    if device is None or device.service_kind != RUNNER_SERVICE_KIND:
        return False
    account = await runner_account(db)
    return account is not None and device.owner_user_id == account.id


async def pool_allowed(db: AsyncSession, workspace_id: str | None) -> bool:
    project = await db.get(Project, workspace_id) if workspace_id else None
    config = project.config if project is not None and isinstance(project.config, dict) else {}
    return project is not None and config.get(WORKSPACE_SWITCH) != SWITCH_FORBIDDEN


async def serves_someone_else(db: AsyncSession, device: UserDevice, *, owner_user_id: str,
                              workspace_id: str | None) -> bool:
    # All agents of a runner share one account and one disk: its active turns are one person's in one Workspace. Read
    # past the viewer filter, or another person's private turn would be missed.
    from .runner_tenant import runner_tenants  # noqa: PLC0415

    return any((owner, workspace) != (owner_user_id, workspace_id)
               for owner, workspace in await runner_tenants(db, device.id))


async def can_take(db: AsyncSession, device: UserDevice | None, *, owner_user_id: str,
                    workspace_id: str | None) -> bool:
    from .hub import device_hub  # noqa: PLC0415
    from .jobs import counted_job_count  # noqa: PLC0415

    if device is None or device.status != DEVICE_STATUS_ACTIVE or device.paused or not device_hub.reachable(device):
        return False
    if not on_required_runtime(device):
        return False
    if await serves_someone_else(db, device, owner_user_id=owner_user_id, workspace_id=workspace_id):
        return False
    return await counted_job_count(db, device.id) < int(device.max_parallel_jobs or 1)


async def resolve_runner(db: AsyncSession, *, workspace_id: str | None, owner_user_id: str,
                         previous: dict[str, Any] | None = None) -> PoolChoice | str:
    # The thread stays on its runner (its Codex thread lives there) while that runner can take the turn.
    from .jobs import counted_job_count  # noqa: PLC0415

    if not await pool_allowed(db, workspace_id):
        return REASON_POOL_FORBIDDEN
    if previous and previous.get("pool") and previous.get("device_id"):
        held = await db.get(UserDevice, str(previous["device_id"]))
        takes = await can_take(db, held, owner_user_id=owner_user_id, workspace_id=workspace_id)
        if await is_pool_runner(db, held) and takes:
            assert held is not None
            return PoolChoice(held, str(previous.get("folder") or new_folder()))
    runners = await _enrolled_runners(db)
    if not runners:
        return REASON_POOL_NOT_SET_UP
    free = [device for device in runners
            if await can_take(db, device, owner_user_id=owner_user_id, workspace_id=workspace_id)]
    if not free:
        return REASON_POOL_EMPTY
    loads = {device.id: await counted_job_count(db, device.id) for device in free}
    chosen = min(free, key=lambda device: (loads[device.id], device.id))
    return PoolChoice(chosen, new_folder())


async def _enrolled_runners(db: AsyncSession) -> list[UserDevice]:
    # Enrolled on the required runtime, online or not: with none, a turn has nothing to wait for.
    account = await runner_account(db)
    if account is None:
        return []
    runners = (await db.execute(select(UserDevice).where(
        UserDevice.owner_user_id == account.id, UserDevice.service_kind == RUNNER_SERVICE_KIND,
        UserDevice.status == DEVICE_STATUS_ACTIVE))).scalars().all()
    return [device for device in runners if on_required_runtime(device)]


async def runners_online(db: AsyncSession) -> int:
    from .hub import device_hub  # noqa: PLC0415

    runners = await _enrolled_runners(db)
    return sum(1 for device in runners
               if not device.paused and device_hub.reachable(device))


def new_folder() -> str:
    return f"{RUNNER_ROOT}/{uuid.uuid4().hex[:16]}"


async def person_chat_target(db: AsyncSession, target: dict[str, Any]) -> dict[str, Any]:
    # A person's chat without a mode chose "Ask first". Claude Code asks by default; Codex on a runner asks only when
    # told, so the runner gets the mode by name. Platform-driven turns keep none: their gates are the run's checks.
    if target.get("permission_mode"):
        return target
    device_id = str(target.get("device_id") or "")
    pool = device_id == POOL_DEVICE_ID or bool(target.get("pool"))
    device = None if pool or not device_id else await db.get(UserDevice, device_id)
    if pool or (device is not None and device.service_kind == RUNNER_SERVICE_KIND):
        return {**target, "permission_mode": ASK_FIRST}
    return target


def previous_pool_target(session: Session | None) -> dict[str, Any] | None:
    from .chat_turn import EXECUTION_TARGET_METADATA_KEY  # noqa: PLC0415

    target = dict(session.metadata_ or {}).get(EXECUTION_TARGET_METADATA_KEY) if session is not None else None
    return dict(target) if isinstance(target, dict) and target.get("pool") else None


__all__ = [
    "ASK_FIRST",
    "POOL_DEVICE_ID",
    "REASON_POOL_EMPTY",
    "REASON_POOL_FORBIDDEN",
    "REASON_POOL_NOT_SET_UP",
    "RUNNER_SERVICE_KIND",
    "PoolChoice",
    "RunnerEnrollError",
    "can_take",
    "enroll_runner",
    "is_pool_runner",
    "new_folder",
    "on_required_runtime",
    "person_chat_target",
    "pool_allowed",
    "previous_pool_target",
    "resolve_runner",
    "runner_account",
    "runners_online",
    "serves_someone_else",
]
