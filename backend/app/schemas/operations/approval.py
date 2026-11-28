from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class WorkflowStartOutcome(BaseModel):
    """What the phased start an approved proposal approval resumed did (distinct from the approval's own status):
    ``started`` with its run, a typed refusal (``needs_configuration`` / ``workspace_required``), or ``failed``."""

    state: str
    reason: str | None = None
    message: str | None = None
    run_id: str | None = None


class ApprovalResponse(BaseModel):
    id: str
    task_run_id: str | None
    session_id: str | None
    requested_by: str
    approved_by: str | None
    action: str
    status: str
    reason: str | None
    created_at: str
    resolved_at: str | None
    # The decider's note; ``reason`` stays the reason the approval was requested for.
    decision_note: str | None = None
    # Only for an approval that resumed a chat's phased workflow start.
    workflow_start: WorkflowStartOutcome | None = None

    model_config = ConfigDict(from_attributes=True)


class ApprovalDecision(BaseModel):
    reason: str | None = None


class ApprovalMetadataResponse(BaseModel):
    """One approval's bounded metadata (``GET /api/v1/approvals/{id}``): no reason text.

    ``kind`` says what the approval pauses: a chat ``session`` turn, a ``task_run``, or a
    ``governance`` publication. Who may read it is ``services/approval/access``'s visibility rule.
    """

    id: str
    kind: Literal["session", "task_run", "governance"]
    status: str
    action: str
    session_id: str | None
    task_run_id: str | None
    requested_by: str
    approved_by: str | None
    created_at: str | None
    resolved_at: str | None
    # The approval detail page: what was asked (the change preview, stored masked), which
    # decisions the card offers, who decided, and where it belongs (Workspace, chat session, workflow run).
    payload: dict[str, Any] | None = None
    # The approval in words (``services/approval/presentation``): what runs, why the person is asked, the details.
    title: str = ""
    subtitle: str = ""
    details: list[str] = []
    offered_decisions: list[str] = []
    decision_note: str | None = None
    requested_by_name: str | None = None
    approved_by_name: str | None = None
    workspace_id: str | None = None
    workflow_run_id: str | None = None
