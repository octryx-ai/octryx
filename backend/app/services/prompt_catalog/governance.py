"""Four-eyes publication of high-risk prompt keys (system prompts, guards, evidence rules).

Same pattern as the Model Policy registry
(``services/model_policy/governance.py``): submitting a high-risk version
creates a ``pending`` platform ``Approval`` whose action binds the version id **and**
its digest, decided through the existing approvals API. Publish accepts only that
approval, ``approved``, through the platform's single four-eyes decision
(``services/governance/four_eyes``): someone else approves it unless the platform
approval rule lets the requester approve their own version (audited).

The approval belongs to the scope's Workspace (a Workspace override's Workspace, an
agent definition's Workspace) or to no Workspace for a global key. The approver must be
a global admin, or an ``admin``/``owner`` of that Workspace for a Workspace-scoped one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Approval
from ...models.runtime.prompt_template import (
    PROMPT_SCOPE_WORKFLOW,
    PROMPT_SCOPE_WORKSPACE,
    PromptTemplate,
    PromptTemplateVersion,
)
from ..access_control import get_project_role_for_user
from ..admin.governance.admin_access_service import is_global_admin
from ..governance.four_eyes import FOUR_EYES_PASSING_STATUSES, decide_four_eyes, record_self_approval_audit

APPROVER_PROJECT_ROLES = frozenset({"admin", "owner"})


def publish_approval_action(version: PromptTemplateVersion) -> str:
    return f"prompt_template.publish:{version.id}:{version.digest}"


@dataclass(frozen=True, slots=True)
class PromptApprovalGate:
    status: str
    approval_id: str | None
    requested_by: str | None = None
    approved_by: str | None = None
    dev_self_approval: bool = False
    approval_mode: str | None = None

    @property
    def passed(self) -> bool:
        return self.status in FOUR_EYES_PASSING_STATUSES

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status,
            "approval_id": self.approval_id,
            "requested_by": self.requested_by,
            "approved_by": self.approved_by,
        }
        if self.dev_self_approval:
            payload["dev_self_approval"] = True
        if self.approval_mode:
            payload["approval_mode"] = self.approval_mode
        return payload


async def approval_workspace_id(db: AsyncSession, template: PromptTemplate) -> str | None:
    if template.scope_type == PROMPT_SCOPE_WORKSPACE:
        return template.scope_id
    return None


async def create_review_approval(
    db: AsyncSession, *, template: PromptTemplate, version: PromptTemplateVersion, requested_by: str
) -> Approval:
    approval = Approval(
        requested_by=requested_by,
        workspace_id=await approval_workspace_id(db, template),
        action=publish_approval_action(version),
        status="pending",
        reason=f"Publish prompt {template.key} v{version.version} ({template.scope_key})",
    )
    db.add(approval)
    await db.flush()
    return approval


async def check_publish_approval(
    db: AsyncSession, *, template: PromptTemplate, version: PromptTemplateVersion, approval_id: str | None
) -> PromptApprovalGate:
    if not approval_id:
        return PromptApprovalGate("required", None)
    approval = await db.get(Approval, approval_id)
    if approval is None:
        return PromptApprovalGate("missing", approval_id)
    workspace_id = await approval_workspace_id(db, template)
    if approval.action != publish_approval_action(version) or approval.workspace_id != workspace_id:
        return PromptApprovalGate("mismatched", approval.id)
    if approval.status != "approved":
        return PromptApprovalGate(str(approval.status or "pending"), approval.id, approval.requested_by)
    decision = await decide_four_eyes(db, approval.requested_by, approval.approved_by)
    if decision.approved:
        if not await _may_approve(db, str(approval.approved_by), workspace_id, template):
            return PromptApprovalGate(
                "approver_not_authorized", approval.id, approval.requested_by, approval.approved_by
            )
        # Same transaction as the publish that relies on it (no-op unless self-approved).
        record_self_approval_audit(
            db, decision, resource_type="prompt_template_version", resource_id=version.id, approval_id=approval.id
        )
    return PromptApprovalGate(
        decision.status,
        approval.id,
        approval.requested_by,
        approval.approved_by,
        decision.dev_exception,
        decision.approval_mode if decision.approved else None,
    )


async def _may_approve(db: AsyncSession, user_id: str, workspace_id: str | None,
                       template: PromptTemplate | None = None) -> bool:
    if await is_global_admin(db, user_id):
        return True
    if template is not None and template.scope_type == PROMPT_SCOPE_WORKFLOW:
        from .scope_rights import may_write

        return await may_write(db, user_id, template.scope_type, template.scope_id)  # the workflow's owner
    if workspace_id is None:
        return False
    return await get_project_role_for_user(db, user_id, workspace_id) in APPROVER_PROJECT_ROLES


__all__ = [
    "PromptApprovalGate",
    "approval_workspace_id",
    "check_publish_approval",
    "create_review_approval",
    "publish_approval_action",
]
