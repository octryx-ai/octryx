"""Device job decisions (O2): dispatch refusals and the owner's approvals of a device job.

A refused dispatch (not the owner, revoked, offline, paused, folder not allow-listed, profile unavailable, busy, or
the device policy) is a ``device_job`` decision; an admitted dispatch is counted. Device approvals are decided by
the job owner only; each request, decision and expiry is a record.
"""

from __future__ import annotations

from typing import Any

from .recorder import (
    GATE_DEVICE_JOB,
    OUTCOME_APPROVED,
    OUTCOME_DENIED,
    OUTCOME_EXPIRED,
    OUTCOME_NEEDS_APPROVAL,
    OUTCOME_NEEDS_CONFIGURATION,
    OUTCOME_REJECTED,
    count_allowed,
    record_gate_decision,
)

DISPATCH_ACTION = "device_dispatch"
APPROVAL_ACTION = "device_approval"
_APPROVAL_OUTCOMES = {
    "allowed": OUTCOME_APPROVED,
    "allowed_job_edits": OUTCOME_APPROVED,
    "denied": OUTCOME_REJECTED,
    "expired": OUTCOME_EXPIRED,
}


def record_device_dispatch(decision: Any, *, user_id: str, profile: str, folder: str, workspace_id: str | None,
                           session_id: str | None) -> None:
    if decision.allowed:
        count_allowed(gate=GATE_DEVICE_JOB, action=DISPATCH_ACTION, workspace_id=workspace_id)
        return
    record_gate_decision(
        gate=GATE_DEVICE_JOB,
        outcome=OUTCOME_NEEDS_CONFIGURATION if decision.state == "needs_configuration" else OUTCOME_DENIED,
        action=DISPATCH_ACTION,
        resource=f"Run on device ({profile}) in {folder or 'an unknown folder'}",
        principal=user_id,
        workspace_id=workspace_id,
        session_id=session_id,
        rule=f"device policy: {decision.reason}",
        reason=decision.reason,
    )


def record_device_approval(job: Any, approval: Any, *, status: str, actor_id: str | None = None) -> None:
    """``status``: ``pending`` (requested) or the decided status of the device approval row."""
    outcome = OUTCOME_NEEDS_APPROVAL if status == "pending" else _APPROVAL_OUTCOMES.get(status)
    if outcome is None:
        return
    record_gate_decision(
        gate=GATE_DEVICE_JOB,
        outcome=outcome,
        action=APPROVAL_ACTION,
        resource=f"Device job: {approval.tool} in {job.folder}",
        principal=actor_id or job.owner_user_id,
        workspace_id=job.workspace_id,
        session_id=job.session_id,
        rule="the job owner decides" if outcome != OUTCOME_EXPIRED else "owner approval timed out",
        actor_id=actor_id,
    )
