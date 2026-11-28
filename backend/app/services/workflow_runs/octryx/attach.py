"""Bind an octryx-claude session to a workflow run: attach to one, or start one the user confirmed."""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Session, User, WorkflowRun
from ....models.runtime.secure_work import WorkItem
from ..records import WorkflowRunError, active_run_for_session, bind_session, lock_run
from ..states import ACTIVE_STATUSES

ROLE_OCTRYX = "octryx"
RUNTIME_OCTRYX = "octryx_claude"


async def work_item_in_workspace(db: AsyncSession, reference: str, workspace_id: str) -> WorkItem | None:
    reference = str(reference or "").strip()[:220]
    if not reference:
        return None
    return (await db.execute(select(WorkItem).where(
        WorkItem.project_id == workspace_id, or_(WorkItem.id == reference, WorkItem.source_key == reference),
    ).limit(1))).scalars().first()


async def active_run_of_item(db: AsyncSession, item: WorkItem) -> WorkflowRun | None:
    return (await db.execute(select(WorkflowRun).where(
        WorkflowRun.work_item_id == item.id, WorkflowRun.status.in_(tuple(ACTIVE_STATUSES)),
        WorkflowRun.parent_run_id.is_(None),
    ).order_by(WorkflowRun.created_at.desc()).limit(1))).scalars().first()


def item_role(key: str) -> str:
    # WorkflowRunSession.role holds 20 characters; a longer key keeps a readable start plus a digest of the whole key.
    import hashlib

    from ....models import WorkflowRunSession

    role = f"{ROLE_OCTRYX}:{key}"
    limit = WorkflowRunSession.role.type.length or len(role)
    if len(role) <= limit:
        return role
    digest = hashlib.sha256(key.encode()).hexdigest()[:8]
    return f"{ROLE_OCTRYX}:{key[:limit - len(ROLE_OCTRYX) - 10]}~{digest}"


async def job_item(db: AsyncSession, job_id: str, run: WorkflowRun | None, user: User) -> dict[str, Any] | None:
    from ....models import DeviceJob
    from ..teamwork import item_marker

    job = await db.get(DeviceJob, job_id) if job_id else None
    if job is None or run is None or job.owner_user_id != user.id:
        return None
    marker = item_marker(await db.get(Session, job.session_id))
    if marker is not None and marker.get("run_id") == run.id:
        return marker
    from ..teamwork.device_work_state import GIT_KEY

    sequential = dict(dict(dict(run.context or {}).get(GIT_KEY) or {}).get("sequential_job") or {})
    if sequential.get("job_id") == job.id:
        from ..teamwork import work_of

        return {"run_id": run.id, "node_id": work_of(run).get("node_id"), "key": sequential["key"],
                "sequential": True}
    return None


async def _is_coordinator_wake(run: WorkflowRun, job_id: str) -> bool:
    from ..teamwork import work_of

    wake = dict(dict(run.context or {}).get("coordinator_wake") or {})
    work = work_of(run)
    return bool(work) and wake.get("job_id") == job_id and run.current_node_id == work.get("node_id")


async def take_over(db: AsyncSession, *, gateway_session: Session, user: User, workspace_id: str,
                    run: WorkflowRun | None) -> WorkflowRun:
    # A person's terminal attaching explicitly: a run on the server runners moves to the terminal (WP-C4a).
    from ..runtime_target.terminal_takeover import take_over_for_terminal

    run = await attach(db, gateway_session=gateway_session, user=user, workspace_id=workspace_id, run=run)
    await take_over_for_terminal(db, run, gateway_session, actor_id=user.id)
    return run


async def attach(db: AsyncSession, *, gateway_session: Session, user: User, workspace_id: str,
                 run: WorkflowRun | None, job_id: str = "") -> WorkflowRun:
    from ..access import run_access

    if run is None or run.project_id != workspace_id or run.status not in ACTIVE_STATUSES:
        raise WorkflowRunError("unknown_run", "No active workflow run with this id in this Workspace.", 404)
    if await run_access(db, run, user) != "write":
        raise WorkflowRunError("run_read_only", "Only the requester, the Work item owner or an admin works on "
                                                "this run.", 403)
    current = await active_run_for_session(db, gateway_session.id)
    if current is not None and current.id == run.id:
        return run
    from ...agent_gateway.repository_root import MESSAGES, bound_repository_refusal

    if (refused := await bound_repository_refusal(db, run, gateway_session)) is not None:
        raise WorkflowRunError(refused.reason, MESSAGES[refused.reason], 409)
    run = await lock_run(db, run)
    if job_id and await _is_coordinator_wake(run, job_id):
        from ..teamwork.device_work_state import COORDINATOR_METADATA_KEY

        # The board wake of the coordinator on the main thread: its turn answers, it is no phase pass.
        gateway_session.metadata_ = {**dict(gateway_session.metadata_ or {}),
                                     COORDINATOR_METADATA_KEY: {"run_id": run.id, "job_id": job_id}}
    item = await job_item(db, job_id, run, user)
    role = item_role(str(item["key"])) if item is not None and not item.get("sequential") else ROLE_OCTRYX
    if item is not None:
        from ..teamwork import ITEM_METADATA_KEY

        gateway_session.metadata_ = {**dict(gateway_session.metadata_ or {}), ITEM_METADATA_KEY: item}
    await bind_session(db, run, gateway_session, actor_id=user.id, role=role, runtime=RUNTIME_OCTRYX)
    from .attribution import stamp

    await stamp(db, run, gateway_session, item=str(item["key"]) if item is not None else "")
    if item is not None and not item.get("sequential"):
        await _remember_agent(db, run, str(item["key"]), gateway_session)
    return run


async def _remember_agent(db: AsyncSession, run: WorkflowRun, key: str, gateway_session: Session) -> None:
    from ...agent_gateway.contract import SESSION_KEY_METADATA
    from ...agent_gateway.presence import session_key_hash
    from ..teamwork import WORK_KEY, work_of

    work = work_of(run)
    items = dict(work.get("items") or {})
    session_key = str(dict(gateway_session.metadata_ or {}).get(SESSION_KEY_METADATA) or "")
    if key not in items or not session_key:
        return
    items[key] = {**dict(items[key]), "agent_hash": session_key_hash(session_key)}
    run.context = {**dict(run.context or {}), WORK_KEY: {**work, "items": items}}


async def session_runtime_target(db: AsyncSession, *, gateway_session: Session, grant_id: str | None,
                                 requested: Any) -> Any:
    from app.services.devices.job_state import ACTIVE_STATUSES as JOB_ACTIVE

    from ....models.security.oauth_provider import OAuthGrant
    from ..runtime_target.target import KIND_DEVICE, KIND_TERMINAL

    kind = requested.get("kind") if isinstance(requested, dict) else requested
    if requested and (isinstance(requested, dict) and len(requested) > 1 or kind != KIND_DEVICE):
        return requested
    grant = await db.get(OAuthGrant, grant_id) if grant_id else None
    device_id = getattr(grant, "device_id", None)
    if not device_id:
        return requested or {"kind": KIND_TERMINAL}
    from ....models import DeviceJob

    job = (await db.execute(select(DeviceJob).where(
        DeviceJob.device_id == device_id, DeviceJob.owner_user_id == gateway_session.user_id,
        DeviceJob.workspace_id == gateway_session.project_id, DeviceJob.status.in_(JOB_ACTIVE),
    ).order_by(DeviceJob.updated_at.desc()).limit(1))).scalars().first()
    if job is None:
        return {"kind": KIND_DEVICE}  # refused by validation: no job names the folder
    return {"kind": KIND_DEVICE, "device_id": device_id, "folder": job.folder, "profile": job.profile,
            "model": job.turn_model or ""}


async def start_confirmed_run(db: AsyncSession, *, gateway_session: Session, user: User, workspace_id: str,
                              workflow_key: str, item: WorkItem, repository: str | None,
                              runtime_target: Any = None) -> WorkflowRun:
    from ..records import new_chat_session, start_run

    thread = await new_chat_session(db, user, workspace_id)
    run = await start_run(db, user=user, workflow_key=workflow_key, project_id=workspace_id, work_item_id=item.id,
                          repository=repository, session=thread, runtime_target=runtime_target)
    if run.status in ACTIVE_STATUSES:
        await bind_session(db, run, gateway_session, actor_id=user.id, role=ROLE_OCTRYX, runtime=RUNTIME_OCTRYX)
    return run


async def bind_device_session(db: AsyncSession, *, gateway_session: Session, user: User, workspace_id: str,
                              run_id: str, job_id: str = "") -> WorkflowRun | None:
    run = await db.get(WorkflowRun, run_id) if run_id else None
    try:
        if not job_id:  # a launcher started for the run, no device job's: the person's terminal
            return await take_over(db, gateway_session=gateway_session, user=user, workspace_id=workspace_id, run=run)
        return await attach(db, gateway_session=gateway_session, user=user, workspace_id=workspace_id, run=run,
                            job_id=job_id)
    except WorkflowRunError:
        return None


def device_bound(run: WorkflowRun, bindings: list[Any]) -> bool:
    return any(item.runtime == RUNTIME_OCTRYX and item.active for item in bindings)


__all__ = ["ROLE_OCTRYX", "RUNTIME_OCTRYX", "active_run_of_item", "attach", "bind_device_session",
           "device_bound", "item_role", "job_item", "session_runtime_target", "start_confirmed_run", "take_over",
           "work_item_in_workspace"]
