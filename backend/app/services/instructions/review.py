"""Review and publish of an instruction version: conflict check, four-eyes approval, publish."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AgentDefinition, Approval, User
from ...models.runtime.instruction import (
    INSTRUCTION_SCOPE_AGENT,
    INSTRUCTION_SCOPE_WORKSPACE,
    Instruction,
    InstructionVersion,
)
from ...time_utils import utc_now
from ..access_control import get_project_role_for_user
from ..admin.governance.admin_access_service import is_global_admin
from ..governance.four_eyes import (
    FOUR_EYES_PASSING_STATUSES,
    SelfApprovalRefusedError,
    decide_four_eyes,
    record_self_approval_audit,
    self_approve_review,
)
from .conflicts import check_conflicts
from .lifecycle_core import InstructionRefusal, _audit, _facts, load_version

APPROVER_PROJECT_ROLES = frozenset({"admin", "owner"})


async def approval_workspace_id(db: AsyncSession, instruction: Instruction) -> str | None:
    if instruction.scope_type == INSTRUCTION_SCOPE_WORKSPACE:
        return instruction.scope_id
    if instruction.scope_type == INSTRUCTION_SCOPE_AGENT:
        agent = await db.get(AgentDefinition, instruction.scope_id)
        return str(agent.project_id) if agent is not None and agent.project_id else None
    return None


def publish_approval_action(version: InstructionVersion) -> str:
    return f"instruction.publish:{version.id}:{version.digest}"


async def check_version(db: AsyncSession, *, version_id: str) -> list[dict[str, Any]]:
    instruction, version = await load_version(db, version_id)
    return await check_conflicts(db, instruction, version.body)


async def submit_for_review(
    db: AsyncSession, *, version_id: str, user: User, accept_findings: bool = False,
) -> InstructionVersion:
    instruction, version = await load_version(db, version_id)
    if version.state != "draft":
        raise InstructionRefusal("instruction_version_not_draft", state=version.state)
    findings = await check_conflicts(db, instruction, version.body)
    if findings and not accept_findings:
        raise InstructionRefusal("instruction_conflicts", findings=findings)
    approval = Approval(
        requested_by=user.id, workspace_id=await approval_workspace_id(db, instruction),
        action=publish_approval_action(version), status="pending",
        reason=f"Publish instruction {instruction.key} v{version.version}",
    )
    db.add(approval)
    await db.flush()
    version.state = "in_review"
    version.findings_json = findings
    version.findings_accepted = 1 if findings else 0
    version.approval_id = approval.id
    await db.flush()
    _audit(db, user_id=user.id, action="instruction.submit", instruction=instruction,
           details={**_facts(version), "findings": [item["code"] for item in findings]})
    return version


async def _may_approve(db: AsyncSession, user_id: str, workspace_id: str | None) -> bool:
    if await is_global_admin(db, user_id):
        return True
    if workspace_id is None:
        return False
    return await get_project_role_for_user(db, user_id, workspace_id) in APPROVER_PROJECT_ROLES


async def publish(
    db: AsyncSession, *, version_id: str, user: User, self_approve: bool = False,
) -> tuple[InstructionVersion, dict[str, Any]]:
    instruction, version = await load_version(db, version_id)
    if version.state != "in_review":
        raise InstructionRefusal("instruction_review_required", state=version.state)
    # The policy may have changed since submit: a finding the submitter did not accept blocks the publish.
    accepted = {(item.get("code"), tuple(item.get("names") or ())) for item in version.findings_json or []}
    new = [item for item in await check_conflicts(db, instruction, version.body)
           if (item.get("code"), tuple(item.get("names") or ())) not in accepted]
    if new:
        raise InstructionRefusal("instruction_conflicts", findings=new)
    approval_id = version.approval_id
    if self_approve:
        try:
            approval_id = await self_approve_review(db, approval_id, actor_id=user.id)
        except SelfApprovalRefusedError as error:
            raise InstructionRefusal(error.code) from None
    approval = await db.get(Approval, approval_id) if approval_id else None
    if approval is None or approval.action != publish_approval_action(version):
        raise InstructionRefusal("governance_approval_required", approval_gate={"status": "missing"})
    if approval.status != "approved":
        raise InstructionRefusal("governance_approval_required", approval_gate={"status": str(approval.status)})
    decision = await decide_four_eyes(db, approval.requested_by, approval.approved_by)
    workspace_id = await approval_workspace_id(db, instruction)
    if decision.status not in FOUR_EYES_PASSING_STATUSES:
        raise InstructionRefusal("governance_approval_required", approval_gate={"status": decision.status})
    if not await _may_approve(db, str(approval.approved_by), workspace_id):
        raise InstructionRefusal("governance_approval_required", approval_gate={"status": "approver_not_authorized"})
    record_self_approval_audit(db, decision, resource_type="instruction_version", resource_id=version.id,
                               approval_id=approval.id, project_id=workspace_id)
    now = utc_now()
    for other in (
        await db.execute(
            select(InstructionVersion).where(
                InstructionVersion.instruction_id == instruction.id, InstructionVersion.state == "published"
            )
        )
    ).scalars():
        other.state, other.retired_at = "retired", now
    version.state, version.published_by, version.published_at = "published", user.id, now
    instruction.updated_at = now
    await db.flush()
    gate = {"status": decision.status, "approval_id": approval.id, "approval_mode": decision.approval_mode}
    _audit(db, user_id=user.id, action="instruction.publish", instruction=instruction, details=_facts(version))
    return version, gate
