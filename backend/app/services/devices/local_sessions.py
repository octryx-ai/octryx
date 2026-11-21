"""Claude Code sessions outside octryx: what the device reports, who sees them, and "take over" (P6b/P6c).

Claude Code sessions not started by octryx-claude are available in the person's own Workspace, and from the phone the
person chooses per session between
**take over** (here) and **live** (a channel, later).

- **Report** (:func:`apply_report`, channel message ``local_sessions``): the device's connected profiles and their
  recent sessions. Every field is bounded and checked; the report replaces the device's previous list. Titles and
  answers are redacted on the device before they leave it.
- **List** (:func:`list_for_owner`): only the owner's own devices, active ones; nobody else, admins included.
- **Take over** (:func:`take_over`): the owner's message becomes a device job turn in the owner's **private
  Workspace**, profile ``local:<name>``, in the session's folder, resuming exactly that Claude Code session. Only a
  session the owner's own, active, online, unpaused device reported can be taken over; the device checks the
  session and its folder again before it runs anything. No Workspace policy applies (the private Workspace is the
  owner's own); the profile's own subscription pays.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import LocalClaudeSession, Message, Session, User, UserDevice
from ...models.security.device import DEVICE_STATUS_ACTIVE
from ...time_utils import utc_now
from ..project.private_workspace import ensure_private_workspace
from ..session.session_title import apply_prompt_title
from .hub import device_hub
from .local_session_report import MAX_SESSIONS, normalize_report

MESSAGE_TYPE = "local_sessions"
LOCAL_PROFILE_PREFIX = "local:"
MAX_PROMPT = 100_000

REASON_NOT_FOUND = "local_session_not_found"
REASON_DEVICE_OFFLINE = "device_offline"
REASON_DEVICE_PAUSED = "device_paused"
REASON_DEVICE_REVOKED = "device_revoked"
REASON_PROMPT_INVALID = "prompt_invalid"
REASON_TAKEOVER_NOT_ALLOWED = "takeover_not_allowed_on_device"
REASON_PLATFORM_DISABLED = "device_runs_platform_disabled"
# A fork (phase B): a copy of a running session, continued from the phone; the original is untouched.
FORK_PREFIX = "fork:"  # on a job's first ``resume_claude_session_id``: the device resumes with ``fork_session``
FORK_PERMISSION_MODE = "default"  # every write step of a fork asks first (the original may be working again)


def local_profile(name: str) -> str:
    return f"{LOCAL_PROFILE_PREFIX}{name}"


async def apply_report(db: AsyncSession, device: UserDevice, body: Any) -> int:
    """Replace the device's reported sessions with this report. Returns how many it holds now. Flushes."""
    if device is None or device.status != DEVICE_STATUS_ACTIVE:
        return 0
    _profiles, sessions = normalize_report(body)
    existing = {(row.profile, row.claude_session_id): row for row in (await db.execute(
        select(LocalClaudeSession).where(LocalClaudeSession.device_id == device.id))).scalars()}
    now = utc_now()
    keep = set()
    for item in sessions:
        key = (item["profile"], item["claude_session_id"])
        keep.add(key)
        row = existing.get(key)
        if row is None:
            row = LocalClaudeSession(device_id=device.id, owner_user_id=device.owner_user_id, **item)
            db.add(row)
        else:
            for name in ("cwd", "title", "last_text", "updated_at", "takeover_allowed"):
                setattr(row, name, item[name])
        row.reported_at = now
    gone = [row.id for key, row in existing.items() if key not in keep]
    if gone:
        await db.execute(delete(LocalClaudeSession).where(LocalClaudeSession.id.in_(gone)))
    await db.flush()
    return len(keep)


def _iso(value: Any) -> str | None:
    return value.isoformat() + "Z" if value is not None else None


async def list_for_owner(db: AsyncSession, *, user_id: str) -> list[dict[str, Any]]:
    rows = (await db.execute(
        select(LocalClaudeSession, UserDevice)
        .join(UserDevice, UserDevice.id == LocalClaudeSession.device_id)
        .where(LocalClaudeSession.owner_user_id == str(user_id), UserDevice.owner_user_id == str(user_id),
               UserDevice.status == DEVICE_STATUS_ACTIVE)
        .order_by(LocalClaudeSession.updated_at.desc().nullslast())
        .limit(MAX_SESSIONS * 2)
    )).all()
    # The phone continues a fork in its own thread (phase B): which threads are forks of which session.
    forks: dict[str, list[str]] = {}
    threads = (await db.execute(select(Session).where(
        Session.user_id == str(user_id), Session.origin == "device_chat").order_by(
        Session.started_at.desc()).limit(200))).scalars().all()
    for thread in threads:
        fork = dict((thread.metadata_ or {}).get("fork_of") or {})
        if fork.get("local_session_id"):
            forks.setdefault(str(fork["local_session_id"]), []).append(thread.id)
    return [
        {
            "id": row.id, "profile": row.profile, "title": row.title, "folder": row.cwd,
            "folder_name": row.cwd.rstrip("/").rsplit("/", 1)[-1] or row.cwd, "last_text": row.last_text,
            "updated_at": _iso(row.updated_at), "thread_id": row.thread_session_id,
            "takeover_allowed": bool(row.takeover_allowed), "fork_thread_ids": forks.get(row.id, [])[:20],
            "device": {"id": device.id, "name": device.name, "online": device_hub.reachable(device)},
        }
        for row, device in rows
    ]


class LocalSessionError(Exception):
    def __init__(self, reason: str, status: int) -> None:
        super().__init__(reason)
        self.reason, self.status = reason, status


async def owned_local_session(db: AsyncSession, *, local_id: str, user_id: str) -> LocalClaudeSession:
    row = await db.get(LocalClaudeSession, str(local_id or "")[:40]) if local_id else None
    if row is None or row.owner_user_id != str(user_id):
        raise LocalSessionError(REASON_NOT_FOUND, 404)
    return row


async def _thread(db: AsyncSession, row: LocalClaudeSession, user: User, private_id: str, prompt: str) -> Session:
    thread = await db.get(Session, row.thread_session_id) if row.thread_session_id else None
    if thread is not None and thread.user_id == str(user.id) and thread.project_id == private_id:
        return thread
    from ..session.workspace import ensure_session_workspace_root  # noqa: PLC0415

    thread = Session(id=str(uuid.uuid4()), user_id=str(user.id), project_id=private_id, status="active",
                     origin="device_chat", metadata_={"local_session_id": row.id})
    apply_prompt_title(thread.metadata_, row.title or prompt)
    db.add(thread)
    await db.flush()
    await ensure_session_workspace_root(db, thread)
    row.thread_session_id = thread.id
    return thread


def _fork_thread_of(thread: Session | None, row: LocalClaudeSession, user: User, private_id: str) -> bool:
    fork = dict((thread.metadata_ or {}).get("fork_of") or {}) if thread is not None else {}
    return (thread is not None and thread.user_id == str(user.id) and thread.project_id == private_id
            and fork.get("local_session_id") == row.id)


async def _new_fork_thread(db: AsyncSession, row: LocalClaudeSession, user: User, private_id: str,
                           label: str) -> Session:
    from ..session.workspace import ensure_session_workspace_root  # noqa: PLC0415

    name = (label or row.title or "a session").strip()[:80]
    thread = Session(id=str(uuid.uuid4()), user_id=str(user.id), project_id=private_id, status="active",
                     origin="device_chat", metadata_={"local_session_id": row.id,
                                                      "fork_of": {"local_session_id": row.id, "name": name}})
    thread.metadata_ = {**thread.metadata_, "title": f"Fork of {name}"[:120]}
    db.add(thread)
    await db.flush()
    await ensure_session_workspace_root(db, thread)
    return thread


async def _takeover_device(db: AsyncSession, row: LocalClaudeSession, user: User) -> UserDevice:
    """The session's device, when the owner may take the session over on it right now."""
    if not row.takeover_allowed:  # the Mac's own opt-in per profile (``--allow-takeover``)
        raise LocalSessionError(REASON_TAKEOVER_NOT_ALLOWED, 409)
    device = await db.get(UserDevice, row.device_id)
    if device is None or device.owner_user_id != str(user.id) or device.status != DEVICE_STATUS_ACTIVE:
        raise LocalSessionError(REASON_DEVICE_REVOKED, 403)
    if not device_hub.reachable(device):
        raise LocalSessionError(REASON_DEVICE_OFFLINE, 409)
    if device.paused:
        raise LocalSessionError(REASON_DEVICE_PAUSED, 403)
    return device


async def _record_takeover_dispatch(db: AsyncSession, row: LocalClaudeSession, user: User,
                                    private_id: str) -> None:
    from ..decisions.devices import record_device_dispatch  # noqa: PLC0415
    from .dispatch_gate import DispatchDecision  # noqa: PLC0415
    from .platform_switch import device_runs_platform_enabled  # noqa: PLC0415

    # The platform's kill switch stops take-overs too, and every take-over is a recorded decision.
    if not await device_runs_platform_enabled(db):
        decision = DispatchDecision.deny("denied", REASON_PLATFORM_DISABLED)
        record_device_dispatch(decision, user_id=str(user.id), profile=local_profile(row.profile), folder=row.cwd,
                               workspace_id=private_id, session_id=row.thread_session_id)
        raise LocalSessionError(REASON_PLATFORM_DISABLED, 403)
    record_device_dispatch(DispatchDecision(True), user_id=str(user.id), profile=local_profile(row.profile),
                           folder=row.cwd, workspace_id=private_id, session_id=row.thread_session_id)


async def _takeover_thread(db: AsyncSession, row: LocalClaudeSession, user: User, private_id: str, prompt: str, *,
                           fork: bool, fork_label: str, thread_id: str) -> tuple[Session, bool]:
    """The thread the turn runs in and whether it is a fork's."""
    if thread_id:
        thread = await db.get(Session, str(thread_id)[:36])
        if not _fork_thread_of(thread, row, user, private_id):
            raise LocalSessionError(REASON_NOT_FOUND, 404)
        return thread, True
    if fork:
        return await _new_fork_thread(db, row, user, private_id, fork_label), True
    return await _thread(db, row, user, private_id, prompt), False


async def take_over(db: AsyncSession, *, user: User, local_id: str, prompt: str, fork: bool = False,
                    fork_label: str = "", thread_id: str = "") -> dict[str, str]:
    """The owner's message as the next turn of that Claude Code session, on its device. Flushes.

    ``fork``: a new thread continues a *copy* of the session (the device resumes it with ``fork_session``), so the
    running original keeps its own transcript; ``thread_id``: the next turn of such a fork. Every fork turn runs in
    :data:`FORK_PERMISSION_MODE`: the original may be working in the same folder again, so each write asks first."""
    from .job_state import DeviceJobError
    from .jobs import start_turn  # noqa: PLC0415

    prompt = prompt.strip() if isinstance(prompt, str) else ""
    if not prompt or len(prompt) > MAX_PROMPT:
        raise LocalSessionError(REASON_PROMPT_INVALID, 400)
    row = await owned_local_session(db, local_id=local_id, user_id=str(user.id))
    device = await _takeover_device(db, row, user)
    private = await ensure_private_workspace(db, user)
    await _record_takeover_dispatch(db, row, user, private.id)
    thread, forked = await _takeover_thread(db, row, user, private.id, prompt, fork=fork, fork_label=fork_label,
                                            thread_id=thread_id)
    try:
        job = await start_turn(db, owner_user_id=str(user.id), device=device, session_id=thread.id,
                               workspace_id=private.id, folder=row.cwd, profile=local_profile(row.profile),
                               prompt=prompt, permission_mode=FORK_PERMISSION_MODE if forked else "")
    except DeviceJobError as error:
        raise LocalSessionError(error.reason, error.status) from None
    if not job.claude_session_id and not job.resume_claude_session_id:
        # The first turn continues exactly that session, or (a fork) a copy of it.
        job.resume_claude_session_id = (FORK_PREFIX if forked else "") + row.claude_session_id
    db.add(Message(session_id=thread.id, role="user", content=prompt))
    metadata = dict(thread.metadata_ or {})
    metadata["execution_target"] = {"kind": "device", "device_id": device.id, "folder": row.cwd,
                                    "profile": local_profile(row.profile), "model": ""}
    thread.metadata_ = metadata
    thread.last_activity_at = utc_now()
    await db.flush()
    return {"thread_id": thread.id, "job_id": job.id, "workspace_id": private.id, "local_id": row.id,
            "title": str((thread.metadata_ or {}).get("title") or "") or (f"Fork of {fork_label}" if forked else "")}


__all__ = [
    "LOCAL_PROFILE_PREFIX",
    "MESSAGE_TYPE",
    "LocalSessionError",
    "apply_report",
    "list_for_owner",
    "local_profile",
    "owned_local_session",
    "take_over",
]
