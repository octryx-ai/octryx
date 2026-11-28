"""A chat message that runs on one of the sender's devices."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Message, Session
from ...time_utils import utc_now
from ..project import get_user_project_ids
from ..session.session_title import apply_prompt_title
from .contract import REASON_DEVICE_NOT_OWNER, STATE_DENIED, STATE_NEEDS_CONFIGURATION
from .device_models import REASON_MODEL_NOT_ALLOWED, admitted_device_model, check_device_model
from .dispatch_gate import check_device_dispatch, normalized_folder
from .job_state import EFFORTS, PERMISSION_MODES, DeviceJobError
from .jobs import start_turn
from .runner_pool import POOL_DEVICE_ID, REASON_POOL_EMPTY, REASON_POOL_NOT_SET_UP, PoolChoice
from .turn_engine import require_engine

REASON_TARGET_CONFLICT = "device_target_conflict"
REASON_PROJECT_REQUIRED = "device_target_workspace_required"
REASON_PROJECT_NOT_FOUND = "project_not_found"
REASON_SESSION_NOT_FOUND = "session_not_found"
REASON_BYPASS_DISABLED = "bypass_disabled_in_workspace"


async def _mode_for_role(db: AsyncSession, *, user_id: str, workspace_id: str | None,
                         permission_mode: str) -> tuple[str, str]:
    from ...models import Project  # noqa: PLC0415
    from ..agent_gateway.role_modes import (  # noqa: PLC0415
        CEILING_BYPASS,
        CEILING_READ_ONLY,
        REASON_BYPASS_OWNER_ONLY,
        session_ceiling,
        workspace_ceiling,
    )

    ceiling = await session_ceiling(db, user_id=user_id, workspace_id=workspace_id)
    if ceiling == CEILING_READ_ONLY:
        return "plan", ""
    if permission_mode == "bypassPermissions" and ceiling != CEILING_BYPASS:
        project = await db.get(Project, workspace_id) if workspace_id else None
        return permission_mode, (REASON_BYPASS_DISABLED if workspace_ceiling(project) != CEILING_BYPASS
                                 else REASON_BYPASS_OWNER_ONLY)
    return permission_mode, ""
EXECUTION_TARGET_METADATA_KEY = "execution_target"


@dataclass(frozen=True, slots=True)
class DeviceTurnRefusal:
    state: str
    reason: str
    status: int
    policy_decision_id: str | None = None

    def detail(self) -> dict[str, Any]:
        detail: dict[str, Any] = {"state": self.state, "reason": self.reason, "code": self.reason,
                                  "message": REFUSAL_MESSAGES.get(self.reason, f"{self.state}: {self.reason}")}
        if self.policy_decision_id:
            detail["policy_decision_id"] = self.policy_decision_id
        return detail


@dataclass(frozen=True, slots=True)
class DeviceTurnStarted:
    session: Session
    job_id: str


_STATUS = {STATE_DENIED: 403, STATE_NEEDS_CONFIGURATION: 409}
# What the chat says for each refusal (``detail.message``); the code stays in ``detail.reason``.
REFUSAL_MESSAGES = {
    REASON_TARGET_CONFLICT: "A device runs the message as it is: clear the workflow and Server model selection.",
    REASON_PROJECT_REQUIRED: "Choose a Workspace for this chat first.",
    REASON_PROJECT_NOT_FOUND: "This Workspace does not exist or you are not a member of it.",
    REASON_SESSION_NOT_FOUND: "This chat no longer exists.",
    REASON_DEVICE_NOT_OWNER: "Only your own devices can run your own chats.",
    "device_revoked": "This device is revoked.",
    "device_offline": "The device is offline. Start it, or run this message on the Server.",
    "device_paused": "The device is paused. Resume it in My settings → Devices or on the device.",
    "folder_not_allowlisted": "This folder is not allowed on the device.",
    "device_profile_unavailable": "This profile is not available on the device.",
    "device_busy": "The device already runs as many chats as it allows.",
    REASON_POOL_EMPTY: "No server runner is free right now. Try again in a moment.",
    REASON_POOL_NOT_SET_UP: "No server runner is set up. An administrator starts one, or run the chat on a device.",
    "server_runners_forbidden": "Server runners are off for this Workspace.",
    "device_target_invalid": "Choose a folder from the device's allowed folders.",
    "device_job_busy": "This chat is still running on the device. Wait for it or stop it.",
    "device_engine_missing": "The device has not reported the engine this chat runs on: install it there (or update "
                             "octryx-claude), or run the chat elsewhere.",
    "device_runs_disabled": "Device runs are off for this Workspace. A Workspace admin can turn them on in "
                            "Agents → Policy.",
    "device_runs_platform_disabled": "Device runs are switched off on this platform.",
    "device_runs_classification": "This Workspace's data classification does not allow device runs.",
    "device_profile_not_allowed": "This Workspace does not allow that profile on devices.",
    "seat_requires_governed": "The Workspace requires the governed profile here.",
    "cedar_policy_denied": "A Workspace policy blocks this device run.",
    REASON_MODEL_NOT_ALLOWED: "This model is not available for that profile in this Workspace. Pick another model.",
    "bypass_disabled_in_workspace": "This Workspace does not allow bypass mode. Pick another permission mode.",
    "bypass_requires_workspace_owner": "Only the Workspace's owners may use bypass mode. Pick another permission mode.",
}


async def _shared_writer(db: AsyncSession, session: Session, user_id: str) -> bool:
    from fastapi import HTTPException

    from ..session.collaboration import require_session_access

    try:
        await require_session_access(db, session_id=session.id, user_id=user_id, require_write=True)
    except HTTPException:
        return False
    return True


async def _existing_thread(db: AsyncSession, *, user_id: str, session_id: str, project_id: str,
                           pool: bool = False) -> Session | str | DeviceTurnRefusal:
    if session_id:
        session = await db.get(Session, session_id)
        if session is None:
            return DeviceTurnRefusal(STATE_DENIED, REASON_SESSION_NOT_FOUND, 404)
        if session.user_id != user_id and not (pool and await _shared_writer(db, session, user_id)):
            # A person's device runs only its owner's thread; the runners also run a shared thread's writer, as the
            # sender's own turn.
            return DeviceTurnRefusal(STATE_DENIED, REASON_DEVICE_NOT_OWNER, 403)
        return session
    if not project_id:
        return DeviceTurnRefusal(STATE_NEEDS_CONFIGURATION, REASON_PROJECT_REQUIRED, 409)
    if project_id not in set(await get_user_project_ids(user_id, db)):
        return DeviceTurnRefusal(STATE_DENIED, REASON_PROJECT_NOT_FOUND, 404)
    return project_id


async def new_thread(db: AsyncSession, *, user_id: str, project_id: str, prompt: str) -> Session:
    from ..session.workspace import ensure_session_workspace_root

    session = Session(id=str(uuid.uuid4()), user_id=user_id, project_id=project_id, status="active",
                      origin="device_chat", metadata_={})
    apply_prompt_title(session.metadata_, prompt)
    db.add(session)
    await db.flush()
    await ensure_session_workspace_root(db, session)
    return session


def device_thread_target(session: Session | None) -> dict[str, Any] | None:
    target = dict(session.metadata_ or {}).get(EXECUTION_TARGET_METADATA_KEY) if session is not None else None
    if not isinstance(target, dict) or target.get("kind") != "device" or not target.get("device_id"):
        return None
    return dict(target)


async def admitted_target(
    db: AsyncSession, *, user_id: str, existing: Session | str, workspace_id: str, device_id: str, folder: str,
    profile: str, model: str,
) -> tuple[Any, str] | DeviceTurnRefusal:
    decision = await check_device_dispatch(
        db, user_id=user_id, thread_owner_id=existing.user_id if isinstance(existing, Session) else user_id,
        device_id=device_id, folder=folder, profile=profile, workspace_id=workspace_id,
        session_id=existing.id if isinstance(existing, Session) else None,
        shared_writer=isinstance(existing, Session) and existing.user_id != user_id)  # checked by _existing_thread
    if not decision.allowed:
        return DeviceTurnRefusal(decision.state, decision.reason, _STATUS.get(decision.state, 409),
                                 decision.policy_decision_id)
    model, refused = await admitted_device_model(db, user_id=user_id, workspace_id=workspace_id, profile=profile,
                                                 device_id=device_id, model=model, check=check_device_model)
    if refused:
        return DeviceTurnRefusal(refused[0], refused[1], _STATUS.get(refused[0], 409), decision.policy_decision_id)
    return decision, model


async def store_prompt(db: AsyncSession, thread: Session, job: Any, prompt: str, *, rerun_message: Message | None,
                        message_on_accept: bool, idempotency_key: str | None, author_user_id: str) -> str:
    if rerun_message is not None:
        from ..chat_rerun import rewind_chat_history  # noqa: PLC0415

        rewound = await rewind_chat_history(db, session=thread, target_message=rerun_message, prompt=prompt)
        # New words are the rerunner's; an unchanged prompt stays with the person who wrote it.
        if rewound.text_changed:
            rewound.target_message.author_user_id = author_user_id
        prompt = rewound.prompt
    elif message_on_accept:
        from .deferred_turn_message import hold  # noqa: PLC0415

        hold(thread, job_id=job.id, turn_id=str(job.turn_id), prompt=prompt, idempotency_key=idempotency_key,
             author_user_id=author_user_id)
    else:
        db.add(Message(session_id=thread.id, role="user", content=prompt, idempotency_key=idempotency_key,
                       author_user_id=author_user_id))
    return prompt


def record_target(thread: Session, *, device_id: str, folder: str, profile: str, model: str,
                   permission_mode: str, effort: str, prompt: str, pool: bool = False) -> None:
    metadata = dict(thread.metadata_ or {})
    metadata[EXECUTION_TARGET_METADATA_KEY] = {"kind": "device", "device_id": device_id, "folder": folder,
                                               "profile": profile, "model": model,
                                               "permission_mode": permission_mode if permission_mode in PERMISSION_MODES
                                               else "",
                                               "effort": effort if effort in EFFORTS else "",
                                               **({"pool": True} if pool else {})}
    apply_prompt_title(metadata, prompt)
    thread.metadata_ = metadata
    thread.last_activity_at = utc_now()


async def pool_default_model(db: AsyncSession, *, user_id: str, workspace_id: str, device_id: str) -> str:
    # A runner has no model of its own to fall back on: the Workspace's first governed model.
    from .device_models import device_model_options

    options = list((await device_model_options(db, user_id=user_id, workspace_id=workspace_id, profile="governed",
                                               device_id=device_id)).ids())
    return options[0] if options else ""


async def _engine_checked_turn(db: AsyncSession, device: Any, **turn: Any) -> Any:
    async with db.begin_nested():  # a refused engine leaves no job behind
        job = await start_turn(db, device=device, **turn)
        await require_engine(db, device, job)
    return job


async def start_device_turn(
    db: AsyncSession, *, user_id: str, prompt: str, target: dict[str, Any], session_id: str = "",
    project_id: str = "", server_selections: dict[str, str] | None = None, idempotency_key: str | None = None,
    rerun_message: Message | None = None, fresh_session: bool = False, resume_session_id: str = "",
    message_on_accept: bool = False, wait_for_runner: bool = False,
) -> DeviceTurnStarted | DeviceTurnRefusal:
    if any(str(value or "").strip() for value in (server_selections or {}).values()):
        return DeviceTurnRefusal(STATE_NEEDS_CONFIGURATION, REASON_TARGET_CONFLICT, 409)
    device_id, profile = str(target.get("device_id") or ""), str(target.get("profile") or "")
    folder = normalized_folder(target.get("folder"))
    pool = device_id == POOL_DEVICE_ID or bool(target.get("pool"))
    existing = await _existing_thread(db, user_id=user_id, session_id=session_id, project_id=project_id, pool=pool)
    if isinstance(existing, DeviceTurnRefusal):
        return existing
    workspace_id = existing.project_id if isinstance(existing, Session) else existing
    model = str(target.get("model") or "")
    permission_mode, effort = str(target.get("permission_mode") or ""), str(target.get("effort") or "")
    permission_mode, refused = await _mode_for_role(db, user_id=user_id, workspace_id=workspace_id,
                                                    permission_mode=permission_mode)
    if refused:
        return DeviceTurnRefusal(STATE_DENIED, refused, 409)  # the role decides the mode
    if pool:
        from .runner_queue import pool_turn_runner  # noqa: PLC0415
        choice = await pool_turn_runner(db, user_id=user_id, existing=existing, prompt=prompt, model=model,
                                        permission_mode=permission_mode, effort=effort, wait=wait_for_runner,
                                        rerun_message=rerun_message, idempotency_key=idempotency_key)
        if not isinstance(choice, PoolChoice):
            return choice  # refused, or waiting for a runner
        device_id, folder, profile = choice.device.id, choice.folder, profile or "governed"
        model = model or await pool_default_model(db, user_id=user_id, workspace_id=workspace_id, device_id=device_id)
    admitted = await admitted_target(db, user_id=user_id, existing=existing, workspace_id=workspace_id,
                                      device_id=device_id, folder=folder, profile=profile, model=model)
    if isinstance(admitted, DeviceTurnRefusal):
        return admitted
    decision, model = admitted
    thread = existing if isinstance(existing, Session) else await new_thread(
        db, user_id=user_id, project_id=workspace_id, prompt=prompt)
    from ...models import UserDevice

    device = await db.get(UserDevice, device_id)
    try:
        job = await _engine_checked_turn(db, device, owner_user_id=user_id, session_id=thread.id,
                                         workspace_id=thread.project_id, folder=folder, profile=profile, prompt=prompt,
                                         policy_decision_id=decision.policy_decision_id, model=model,
                                         permission_mode=permission_mode, effort=effort, fresh_session=fresh_session,
                                         resume_session_id=resume_session_id)
    except DeviceJobError as error:
        return DeviceTurnRefusal(error.state, error.reason, error.status)
    prompt = await store_prompt(db, thread, job, prompt, rerun_message=rerun_message,
                                 message_on_accept=message_on_accept, idempotency_key=idempotency_key,
                                 author_user_id=user_id)
    record_target(thread, device_id=device.id, folder=folder, profile=profile, model=model,
                   permission_mode=permission_mode, effort=effort, prompt=prompt, pool=pool)
    await db.flush()
    return DeviceTurnStarted(session=thread, job_id=job.id)


__all__ = ["DeviceTurnRefusal", "DeviceTurnStarted", "EXECUTION_TARGET_METADATA_KEY", "device_thread_target",
           "start_device_turn"]
