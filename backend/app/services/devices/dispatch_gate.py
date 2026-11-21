"""The device dispatch gate: may this chat message run on that device?

Checked in order; the first failure is an explicit state with a fixed reason, shown in the chat. There is no
fallback to the Server.

1. ownership (hard invariant): the device belongs to the caller, the thread too — ``denied``;
2. the device is not revoked — ``denied: device_revoked``;
3. platform switch, Workspace opt-in, classification, Cedar ``run_on_device`` and the profile rules
   (``device_policy.device_run_decision``);
4. the device is online — ``needs_configuration: device_offline`` (no queue);
5. not paused — ``denied: device_paused``;
6. the folder is inside the device's reported allowlist — ``denied: folder_not_allowlisted``;
7. the profile is available on the device — ``needs_configuration: device_profile_unavailable``;
8. a free parallel slot — ``needs_configuration: device_busy``.
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import UserDevice
from ...models.security.device import DEFAULT_MAX_PARALLEL_JOBS, DEVICE_STATUS_ACTIVE
from .contract import (
    PROFILES,
    REASON_DEVICE_NOT_OWNER,
    REASON_DEVICE_REVOKED,
    STATE_DENIED,
    STATE_NEEDS_CONFIGURATION,
)
from .hub import device_hub
from .job_recovery import fail_stalled_turns
from .jobs import counted_job_count, mark_lost_jobs

REASON_DEVICE_OFFLINE = "device_offline"
REASON_DEVICE_PAUSED = "device_paused"
REASON_FOLDER_NOT_ALLOWLISTED = "folder_not_allowlisted"
REASON_PROFILE_UNAVAILABLE = "device_profile_unavailable"
REASON_DEVICE_BUSY = "device_busy"
REASON_TARGET_INVALID = "device_target_invalid"


@dataclass(frozen=True, slots=True)
class DispatchDecision:
    allowed: bool
    state: str = ""
    reason: str = ""
    policy_decision_id: str | None = None

    @classmethod
    def deny(cls, state: str, reason: str, policy_decision_id: str | None = None) -> DispatchDecision:
        return cls(False, state, reason, policy_decision_id)


def normalized_folder(value: Any) -> str:
    text = str(value or "") if isinstance(value, str) else ""
    if not text.startswith("/") or "\x00" in text or ".." in text.split("/") or len(text) > 500:
        return ""
    return posixpath.normpath(text)


def folder_allowlisted(folder: str, allowlist: list[str]) -> bool:
    for allowed in allowlist:
        root = posixpath.normpath(str(allowed))
        if folder == root or folder.startswith(root.rstrip("/") + "/"):
            return True
    return False


async def check_device_dispatch(
    db: AsyncSession, *, user_id: str, thread_owner_id: str, device_id: str, folder: str, profile: str,
    workspace_id: str | None, session_id: str | None = None,
) -> DispatchDecision:
    """The dispatch decision; every refusal is a decision record and every admission is counted."""
    from ..decisions.devices import record_device_dispatch

    decision = await _check_device_dispatch(
        db, user_id=user_id, thread_owner_id=thread_owner_id, device_id=device_id, folder=folder, profile=profile,
        workspace_id=workspace_id, session_id=session_id,
    )
    record_device_dispatch(decision, user_id=user_id, profile=profile, folder=normalized_folder(folder),
                           workspace_id=workspace_id, session_id=session_id)
    return decision


async def _check_device_dispatch(
    db: AsyncSession, *, user_id: str, thread_owner_id: str, device_id: str, folder: str, profile: str,
    workspace_id: str | None, session_id: str | None = None,
) -> DispatchDecision:
    device = await db.get(UserDevice, device_id) if device_id else None
    if device is None or device.owner_user_id != user_id or thread_owner_id != user_id:
        return DispatchDecision.deny(STATE_DENIED, REASON_DEVICE_NOT_OWNER)
    if device.status != DEVICE_STATUS_ACTIVE:
        return DispatchDecision.deny(STATE_DENIED, REASON_DEVICE_REVOKED)
    folder = normalized_folder(folder)
    if not folder or profile not in PROFILES:
        return DispatchDecision.deny(STATE_DENIED, REASON_TARGET_INVALID)
    from .device_policy import device_run_decision

    policy = await device_run_decision(db, user_id=user_id, device=device, workspace_id=workspace_id,
                                       profile=profile, session_id=session_id,
                                       folder_allowlisted=folder_allowlisted(folder, device.folders or []))
    if not policy.allowed:
        return policy
    if not device_hub.reachable(device):
        return DispatchDecision.deny(STATE_NEEDS_CONFIGURATION, REASON_DEVICE_OFFLINE, policy.policy_decision_id)
    if device.paused:
        return DispatchDecision.deny(STATE_DENIED, REASON_DEVICE_PAUSED, policy.policy_decision_id)
    if not folder_allowlisted(folder, list(device.folders or [])):
        return DispatchDecision.deny(STATE_DENIED, REASON_FOLDER_NOT_ALLOWLISTED, policy.policy_decision_id)
    if profile not in (device.profiles or []):
        return DispatchDecision.deny(STATE_NEEDS_CONFIGURATION, REASON_PROFILE_UNAVAILABLE, policy.policy_decision_id)
    await mark_lost_jobs(db, device_id=device.id)
    await fail_stalled_turns(db, device_id=device.id)
    if await _no_free_slot(db, device, session_id):
        return DispatchDecision.deny(STATE_NEEDS_CONFIGURATION, REASON_DEVICE_BUSY, policy.policy_decision_id)
    return DispatchDecision(True, policy_decision_id=policy.policy_decision_id)


async def _no_free_slot(db: AsyncSession, device: UserDevice, session_id: str | None) -> bool:
    """Every parallel slot is taken; a team's platform turn on its run's main thread needs none (``teamwork.slots``:
    the git work and the coordinator's answers never wait behind, or take the place of, an item)."""
    from ..workflow_runs.teamwork.slots import slot_free

    if await slot_free(db, session_id):
        return False
    return await counted_job_count(db, device.id) >= int(device.max_parallel_jobs or DEFAULT_MAX_PARALLEL_JOBS)


__all__ = ["DispatchDecision", "check_device_dispatch", "folder_allowlisted", "normalized_folder"]
