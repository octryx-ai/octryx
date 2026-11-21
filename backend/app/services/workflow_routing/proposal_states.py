"""Closed vocabulary of workflow proposals, shared by the resolver, the gate and the read models.

Constants only (no imports), so the execution gate, the trace snapshot and the turn execution
summary can depend on it without pulling in the proposal machinery.
"""

from __future__ import annotations

WORKFLOW_PROPOSAL_KEY = "workflow_proposal"
WORKFLOW_PROPOSAL_SOURCE = "workflow_proposal"
WORKFLOW_PROPOSAL_VERSION = "workflow_proposal.v1"
# Explicit "no workflow" selection (composer option, "continue without workflow"): no
# proposal call, no workflow. A published workflow cannot be selected under this key.
WORKFLOW_KEY_NONE = "none"

STATUS_NEEDS_CONFIRMATION = "needs_confirmation"
STATUS_NONE = "none"
STATUS_DISABLED = "disabled"
# The turn runs as a plain chat and the workflow is shown next to the answer as an optional offer.
STATUS_OFFERED = "offered"
PROPOSAL_STATUSES = frozenset({STATUS_NEEDS_CONFIRMATION, STATUS_NONE, STATUS_DISABLED, STATUS_OFFERED})
PROPOSAL_CONFIDENCES = ("low", "medium", "high")

PROPOSAL_REASON_CODES = frozenset(
    {
        "low_confidence",
        "no_match",
        "unknown_key",
        "invalid_answer",
        "model_refused",
        "model_unavailable",
        "timeout",
        "admission_denied",
        "admission_needs_configuration",
        "no_runtime_configured",
        "content_blocked",
        "no_published_definitions",
        "empty_message",
        # A greeting or thanks ("Thanks!", "Hi"): no workflow can fit, so no router call is made.
        "conversational_message",
        "proposal_failed",
        "policy_disabled",
        "user_selected_no_workflow",
        # The proposal resolved before the chat preparation lock no longer matches the turn
        # (Workspace or message changed in between); no call is made under the lock.
        "proposal_scope_changed",
        # An admitted agent the user chose directly (explicit, exact mention, the session's bound
        # agent) controls the turn and no workflow was chosen: no automatic proposal call.
        "direct_agent_selected",
        # A proposal that would wait for the user, but the user's words do not ask for the
        # workflow's outcome: the turn runs as a plain chat, the workflow is offered next to it.
        "offered_not_requested",
        # A phased workflow (proposed, or chosen in the composer, or by "Other workflow"): it starts as a workflow
        # run for a Work item after the one start confirmation (``phased_start``).
        "workflow_run_required",
        "explicit_phased_selection",
        "user_chose_other",
    }
)

__all__ = [
    "PROPOSAL_CONFIDENCES",
    "PROPOSAL_REASON_CODES",
    "PROPOSAL_STATUSES",
    "STATUS_DISABLED",
    "STATUS_NEEDS_CONFIRMATION",
    "STATUS_NONE",
    "STATUS_OFFERED",
    "WORKFLOW_KEY_NONE",
    "WORKFLOW_PROPOSAL_KEY",
    "WORKFLOW_PROPOSAL_SOURCE",
    "WORKFLOW_PROPOSAL_VERSION",
]
