"""The owner's chat approval as the change confirmation of a device job.

A governed Claude Code session is read-only until a change workflow is confirmed (``agent_gateway/capability``).
For a job the owner started from the chat on their **own** device, the Workspace setting
``device_runs.chat_approvals_confirm_changes`` (default on) makes the owner's approval in that chat the
confirmation instead:

- only for a launcher session authenticated with a **device grant** (the device service's own credential, bound
  to one registered device of the same user) that runs an active job of that device, owner and Workspace whose
  folder contains the hook's ``cwd``;
- only where the capability rule would deny with ``capability_read_only``; destructive commands, the Workspace's
  tool rules, Cedar and self-protection still deny first, and pushing or opening a pull request still needs a
  deliver workflow;
- a file change must stay inside the job's folder;
- the answer is ``ask``, so Claude Code asks through the device's permission prompt, which is the chat approval
  card (Allow once / Allow edits for this job / Deny). A file change under an earlier "Allow edits for this job"
  of the same job is allowed.

Every write approved this way is audited (``device.job.change_confirmed``: job, tool, approver = the owner). With
the setting off the capability rule's denial stands (a confirmed change workflow, through the workflow tools the
device grant may call).
"""

from __future__ import annotations

import json
import posixpath
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, DeviceJob, DeviceJobApproval, Session
from ...models.security.oauth_provider import OAuthGrant
from ..agent_gateway.capability import DELIVER_COMMAND_PREFIXES, FILE_MUTATION_TOOLS
from ..agent_gateway.command_match import command_segments, segment_matches
from ..agent_gateway.tool_check import DECISION_DENY, ToolDecision, candidate_paths
from .job_state import ACTIVE_STATUSES, DECISION_ALLOW_JOB_EDITS, MAX_PREVIEW_CHARS, input_digest

SETTING_KEY = "chat_approvals_confirm_changes"
DECISION_ASK = "ask"
STATE_NEEDS_APPROVAL = "needs_approval"
REASON_ASKED = "device_chat_confirmation"
REASON_OUTSIDE_FOLDER = "outside_device_job_folder"
REASON_DELIVER = "capability_deliver_required"
CAPABILITY_READ_ONLY_REASON = "capability_read_only"
AUDIT_REQUESTED = "device.job.change_confirmation_requested"
AUDIT_CONFIRMED = "device.job.change_confirmed"
WRITE_TOOLS = FILE_MUTATION_TOOLS | {"Bash"}
_ASK_MESSAGE = ("This would change files or state. On your own device, your approval in the Octryx chat "
                "confirms the change.")


def tool_preview(tool: str, tool_input: dict[str, Any]) -> str:
    """The same preview the device sends with its approval request (``device_sdk.input_preview``)."""
    if tool == "Bash" and isinstance(tool_input.get("command"), str):
        text = tool_input["command"]
    elif isinstance(tool_input.get("file_path"), str):
        text = tool_input["file_path"]
    else:
        text = json.dumps(tool_input, ensure_ascii=False, default=str)
    return text[:MAX_PREVIEW_CHARS]


def _within(path: str, root: str) -> bool:
    normalized, base = posixpath.normpath(path), posixpath.normpath(root)
    return normalized == base or normalized.startswith(base.rstrip("/") + "/")


def _delivers(command: str) -> bool:
    return any(segment_matches(segment, prefix) for segment in command_segments(command) or []
               for prefix in DELIVER_COMMAND_PREFIXES)


async def device_job_for_hook(db: AsyncSession, *, session: Session, grant_id: str | None,
                              hook_input: dict[str, Any]) -> DeviceJob | None:
    """The owner's active device job behind this launcher session, or ``None`` (not a device-grant session)."""
    grant = await db.get(OAuthGrant, grant_id) if grant_id else None
    if grant is None or not grant.device_id or grant.revoked_at is not None or grant.user_id != session.user_id:
        return None
    cwd = str(hook_input.get("cwd") or "")
    if not cwd.startswith("/"):
        return None
    jobs = (await db.execute(select(DeviceJob).where(
        DeviceJob.device_id == grant.device_id, DeviceJob.owner_user_id == session.user_id,
        DeviceJob.workspace_id == session.project_id, DeviceJob.status.in_(ACTIVE_STATUSES),
    ).order_by(DeviceJob.created_at.desc()))).scalars().all()
    candidates = [job for job in jobs if _within(cwd, job.folder)]
    claude_session = str(hook_input.get("session_id") or "")
    for job in candidates:
        if claude_session and job.claude_session_id == claude_session:
            return job
    return candidates[0] if len(candidates) == 1 else None


def _audit(db: AsyncSession, job: DeviceJob, action: str, details: dict[str, Any]) -> None:
    db.add(AuditLog(user_id=job.owner_user_id, session_id=job.session_id, action=action, resource_type="device_job",
                    resource_id=job.id, details={"device_id": job.device_id, **details}))


async def _job_edits_approval(db: AsyncSession, job: DeviceJob) -> DeviceJobApproval | None:
    return (await db.execute(select(DeviceJobApproval).where(
        DeviceJobApproval.job_id == job.id, DeviceJobApproval.status == "allowed_job_edits",
    ).order_by(DeviceJobApproval.decided_at.desc()).limit(1))).scalar_one_or_none()


async def chat_confirmed_change(db: AsyncSession, *, session: Session, grant_id: str | None,
                                hook_input: dict[str, Any], denial: ToolDecision) -> dict[str, Any] | None:
    """The answer replacing a ``capability_read_only`` denial on the owner's own device, else ``None``. Flushes."""
    if denial.reason != CAPABILITY_READ_ONLY_REASON:
        return None
    tool = str(hook_input.get("tool_name") or "")
    tool_input = hook_input.get("tool_input") if isinstance(hook_input.get("tool_input"), dict) else {}
    if tool not in WRITE_TOOLS:
        return None
    job = await device_job_for_hook(db, session=session, grant_id=grant_id, hook_input=hook_input)
    if job is None:
        return None
    from .workspace_policy import workspace_device_setting

    if await workspace_device_setting(db, job.workspace_id, SETTING_KEY) is not True:
        return None
    if tool in FILE_MUTATION_TOOLS:
        raw = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
        paths = candidate_paths(raw, str(hook_input.get("cwd") or ""))[-1:] if raw else []
        if not paths or not _within(paths[0], job.folder) or posixpath.normpath(paths[0]) == posixpath.normpath(
                job.folder):
            return ToolDecision(DECISION_DENY, "denied", REASON_OUTSIDE_FOLDER, REASON_OUTSIDE_FOLDER.replace("_", "-"),
                                f"Changes on a device job stay inside its folder {job.folder}.").to_payload()
        edits = await _job_edits_approval(db, job)
        if edits is not None:
            _audit(db, job, AUDIT_CONFIRMED, {"tool": tool, "approver_user_id": job.owner_user_id,
                                              "via": DECISION_ALLOW_JOB_EDITS, "approval_id": edits.id,
                                              "input_digest": input_digest(tool_preview(tool, tool_input))})
            await db.flush()
            return {"decision": "allow", "state": "allowed", "reason": REASON_ASKED, "rule_id": None, "message": ""}
    elif _delivers(str(tool_input.get("command") or "")):
        return ToolDecision(DECISION_DENY, "denied", REASON_DELIVER, REASON_DELIVER.replace("_", "-"),
                            "Pushing or opening a pull request needs a confirmed deliver workflow.").to_payload()
    _audit(db, job, AUDIT_REQUESTED, {"tool": tool, "input_digest": input_digest(tool_preview(tool, tool_input))})
    await db.flush()
    return {"decision": DECISION_ASK, "state": STATE_NEEDS_APPROVAL, "reason": REASON_ASKED, "rule_id": None,
            "message": _ASK_MESSAGE}


async def audit_confirmed_write(db: AsyncSession, job: DeviceJob, approval: DeviceJobApproval, decision: str) -> None:
    """An allowing decision on an approval this rule asked for becomes ``device.job.change_confirmed``. Flushes."""
    if approval.tool not in WRITE_TOOLS or approval.status not in ("allowed", "allowed_job_edits"):
        return
    asked = (await db.execute(select(AuditLog.details).where(
        AuditLog.resource_type == "device_job", AuditLog.resource_id == job.id, AuditLog.action == AUDIT_REQUESTED,
    ).order_by(AuditLog.created_at.desc()).limit(50))).scalars().all()
    if not any(isinstance(details, dict) and details.get("tool") == approval.tool
               and details.get("input_digest") == approval.input_digest for details in asked):
        return
    _audit(db, job, AUDIT_CONFIRMED, {"tool": approval.tool, "approver_user_id": approval.decided_by,
                                      "via": decision, "approval_id": approval.id,
                                      "input_digest": approval.input_digest})
    await db.flush()


__all__ = ["AUDIT_CONFIRMED", "AUDIT_REQUESTED", "SETTING_KEY", "audit_confirmed_write", "chat_confirmed_change",
           "device_job_for_hook", "tool_preview"]
