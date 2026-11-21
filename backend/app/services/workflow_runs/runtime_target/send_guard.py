"""A chat message on a run's thread executes where the run executes, or is refused (never a silent switch).

A run with a runtime target owns its thread's runtime: a message sent to another device or folder, to a device
while the run executes on the Server or a terminal, or to the Server while it executes on a device, is refused with
``needs_configuration: runtime_target_mismatch``; the run card's ``change_runtime`` switches explicitly. Threads
without an active run, and runs started without a target, are unaffected.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...devices.dispatch_gate import normalized_folder
from .target import KIND_DEVICE, stored_target, target_label

REASON_MISMATCH = "runtime_target_mismatch"


async def send_refusal(db: AsyncSession, *, session_id: str | None, device_target: dict[str, Any] | None
                       ) -> dict[str, Any] | None:
    """The refusal detail for a message to ``device_target`` (``None``: the Server) on ``session_id``, or ``None``."""
    from ..records import active_run_for_session

    run = await active_run_for_session(db, session_id) if session_id else None
    target = stored_target(run)
    if target is None:
        return None
    if target["kind"] == KIND_DEVICE:
        matches = device_target is not None and (
            str(device_target.get("device_id") or ""), normalized_folder(device_target.get("folder"))
        ) == (target.get("device_id"), target.get("folder"))
    else:
        matches = device_target is None
    if matches:
        return None
    return {"state": "needs_configuration", "reason": REASON_MISMATCH, "code": REASON_MISMATCH,
            "message": f"This workflow run executes on {target_label(target)}. Send from there, or change where the "
                       "run executes in the run card."}


__all__ = ["REASON_MISMATCH", "send_refusal"]
