"""Device job values: statuses, decisions, limits, refusal reasons, the error, and how a job and its approvals
are stored and shown (``devices.jobs``)."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, DeviceJob, DeviceJobApproval
from ...time_utils import ensure_utc
from .contract import STATE_DENIED

STATUS_OFFERED = "offered"
STATUS_RUNNING = "running"
STATUS_IDLE = "idle"
STATUS_REJECTED = "rejected"
STATUS_FAILED = "failed"
STATUS_LOST = "device_lost"
STATUS_CLOSED = "closed"
# A chat turn no server runner was free for: no device yet, offered when a runner frees (``runner_queue``).
STATUS_WAITING = "waiting_runner"
ACTIVE_STATUSES = (STATUS_OFFERED, STATUS_RUNNING)
BUSY_STATUSES = (STATUS_WAITING, *ACTIVE_STATUSES)
OPEN_STATUSES = (STATUS_OFFERED, STATUS_RUNNING, STATUS_IDLE)

DECISION_ALLOW_ONCE = "allow_once"
DECISION_ALLOW_JOB_EDITS = "allow_job_edits"
DECISION_DENY = "deny"
DECISIONS = {DECISION_ALLOW_ONCE: "allowed", DECISION_ALLOW_JOB_EDITS: "allowed_job_edits", DECISION_DENY: "denied"}
EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})

# The chat chooses Claude Code's permission mode and effort per turn, as in the terminal. The
# platform's PreToolUse check runs in every mode (bypass included); the device checks these values again.
PERMISSION_MODES = frozenset({"default", "acceptEdits", "plan", "bypassPermissions"})
EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})

DEFAULT_APPROVAL_TIMEOUT_S = 300
DEFAULT_MAX_JOB_MINUTES = 60
# How long a running job survives its device being away before it becomes ``device_lost``. A platform redeploy
# disconnects every device: measured over a week, the gap from close to reconnect was a median 17 s but up to
# 122-145 s (API boot ~50-75 s plus client backoff), so 2 minutes lost running turns on ordinary redeploys. Five
# minutes is twice the worst observed gap and still half the 10-minute stalled-turn limit (``job_recovery``); a
# device that reconnects reports a turn its restart ended itself (``service_restarted``).
OFFLINE_GRACE = timedelta(minutes=5)
MAX_TEXT_CHARS = 16_000
MAX_TOOL_RESULT_CHARS = 4_000
MAX_PREVIEW_CHARS = 2_000
MAX_PROMPT_CHARS = 100_000

REASON_JOB_NOT_FOUND = "device_job_not_found"
REASON_JOB_BUSY = "device_job_busy"
REASON_NOT_OWNER = "device_approval_not_owner"
REASON_APPROVAL_NOT_FOUND = "device_approval_not_found"
REASON_APPROVAL_EXPIRED = "approval_expired"
REASON_APPROVAL_DECIDED = "approval_already_decided"
REASON_DECISION_INVALID = "approval_decision_invalid"
REASON_JOB_EDITS_NOT_ALLOWED = "approval_job_edits_not_allowed"
REASON_JOB_NOT_RUNNING = "device_job_not_running"
REASON_CANCELLED = "cancelled_by_owner"


class DeviceJobError(Exception):
    def __init__(self, reason: str, status: int = 400, state: str = STATE_DENIED) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status = status
        self.state = state


def _audit(db: AsyncSession, *, actor_id: str, action: str, job: DeviceJob, details: dict[str, Any]) -> None:
    db.add(AuditLog(user_id=actor_id, session_id=job.session_id, action=action, resource_type="device_job",
                    resource_id=job.id, project_id=job.workspace_id, details={"device_id": job.device_id, **details}))


def _clip(value: Any, limit: int) -> Any:
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + "…"
    return value


def bounded_body(body: dict[str, Any]) -> dict[str, Any]:
    limit = MAX_TOOL_RESULT_CHARS if body.get("kind") == "tool_result" else MAX_TEXT_CHARS
    clipped = {key: _clip(value, limit) for key, value in body.items()}
    if len(json.dumps(clipped, default=str)) > 4 * MAX_TEXT_CHARS:
        return {"kind": str(body.get("kind") or ""), "truncated": True}
    return clipped


def input_digest(preview: str) -> str:
    return "sha256:" + hashlib.sha256(preview.encode("utf-8")).hexdigest()[:16]


def _iso(value: Any) -> str | None:
    return ensure_utc(value).isoformat() if value is not None else None


def serialize_approval(approval: DeviceJobApproval) -> dict[str, Any]:
    return {
        "id": approval.id, "tool": approval.tool, "input_preview": approval.input_preview,
        "status": approval.status, "can_allow_job_edits": bool(approval.can_allow_job_edits),
        "expires_at": _iso(approval.expires_at), "decided_at": _iso(approval.decided_at),
    }


def serialize_job(job: DeviceJob, *, device_name: str = "") -> dict[str, Any]:
    return {
        "id": job.id, "device_id": job.device_id, "device_name": device_name, "folder": job.folder,
        "profile": job.profile, "model": job.model, "requested_model": job.turn_model or "",
        # The coding engine (``claude_code`` | ``codex``); null until the first offer fixes it.
        "engine": getattr(job, "engine", None),
        "status": job.status, "status_reason": job.status_reason,
        "turn_id": job.turn_id, "turn_count": job.turn_count, "stopping": job.stop_state is not None,
        "last_event_seq": job.last_event_seq, "cost_usd": float(job.cost_usd) if job.cost_usd is not None else None,
        "created_at": _iso(job.created_at), "finished_at": _iso(job.finished_at),
    }
