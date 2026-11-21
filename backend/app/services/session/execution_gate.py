"""Execution gate that enforces the persisted execution profile at the runtime boundary.

The execution profile (see ``services/execution_profile_service.py``) records whether a
turn is allowed to run. This gate is the single enforcement point for that contract. ``run_agent`` evaluates it after
run preparation and must not start the model/tool loop when the decision is blocked; the turn ends
with an explicit user-facing message instead.

Enforcement rules:

- ``allowed`` runs.
- ``denied``, ``needs_approval``, ``needs_configuration``, ``needs_clarification``
  block with a status-specific message.
- A profile with an unknown or missing status blocks (deny-by-default for unclear
  execution state).
- An allowed profile whose policy is a pending workflow proposal
  (``policy.source == "workflow_proposal"`` and ``policy.status ==
  "needs_confirmation"``, see ``services/workflow_routing/proposal.py``) blocks
  with ``needs_confirmation``: a proposed workflow that can change things never
  starts without the user's confirmation.
- A turn without any execution profile is ``denied`` with the decision source
  ``missing_profile`` (Product Run end reason ``gate_missing_profile``). There is
  no compatibility allow: run preparation
  (``agent/core/context/run_context_routing.py``) builds a profile for every
  ``run_agent`` caller from its declared origin (chat routing, workflow, parent
  run, schedule, flow, worker profile or agent definition), and a caller that
  declares no origin gets a ``needs_configuration`` profile, never an allow.
  A missing profile can only mean corrupted or bypassed preparation state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.execution_profile_status import (
    EXECUTION_PROFILE_STATUS_ALLOWED,
    EXECUTION_PROFILE_STATUS_DENIED,
    EXECUTION_PROFILE_STATUS_NEEDS_APPROVAL,
    EXECUTION_PROFILE_STATUS_NEEDS_CLARIFICATION,
    EXECUTION_PROFILE_STATUS_NEEDS_CONFIGURATION,
)

from ..trace_gate_outcome import gate_outcome_marker
from ..workflow_routing.proposal_states import STATUS_NEEDS_CONFIRMATION, WORKFLOW_PROPOSAL_SOURCE

GATE_SOURCE_PROFILE = "execution_profile"
# Turn-trace ``source``/gate id of a persisted execution-gate outcome.
EXECUTION_GATE_TRACE_SOURCE = "execution_gate"
GATE_SOURCE_MISSING_PROFILE = "missing_profile"
GATE_SOURCE_UNKNOWN_STATUS = "unknown_execution_profile_status"
# Equal to the proposal vocabulary (``workflow_routing/proposal_states.py``); spelled out
# because the chat client's contract test reads these literals from this file.
GATE_SOURCE_WORKFLOW_PROPOSAL = "workflow_proposal"
GATE_STATUS_NEEDS_CONFIRMATION = "needs_confirmation"
_NEEDS_CONFIRMATION_MESSAGE = (
    "A workflow was suggested for this request. It runs as a workflow run and does not start without your "
    "confirmation. Nothing was executed. Start the suggested workflow or continue without a workflow."
)

_BLOCKED_STATUS_MESSAGES: dict[str, str] = {
    EXECUTION_PROFILE_STATUS_DENIED: (
        "This request was denied by execution policy and was not executed."
    ),
    EXECUTION_PROFILE_STATUS_NEEDS_APPROVAL: (
        "This request requires an approval before it can run. It was not executed. "
        "Resolve the pending approval and send the request again."
    ),
    EXECUTION_PROFILE_STATUS_NEEDS_CONFIGURATION: (
        "This request requires configuration before it can run. It was not executed. "
        "Complete the missing configuration and send the request again."
    ),
    EXECUTION_PROFILE_STATUS_NEEDS_CLARIFICATION: (
        "This request needs clarification before it can run. It was not executed. "
        "Please restate the request with the missing details."
    ),
}
# ``run_capability.declared.SOURCE_MISSING_DECLARATION`` (spelled out: no import cycle). The internal reason ("no
# profile origin ...") stays in the trace and the ``agent.run.blocked_by_execution_profile`` log; the person reads
# what to do.
_CAPABILITY_SOURCE_MISSING_DECLARATION = "missing_declaration"
_MISSING_ORIGIN_MESSAGE = (
    "This message was not run: Octryx could not tell how it was started, so nothing was executed. "
    "Send it again as a new message in this chat. If this keeps happening, ask your Workspace admin to look at it."
)


@dataclass(frozen=True, slots=True)
class ExecutionGateDecision:
    """Result of evaluating the execution profile before starting the agent loop."""

    allowed: bool
    status: str
    decision_source: str
    reason: str
    user_message: str

    def to_metadata(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "status": self.status,
            "decision_source": self.decision_source,
            "reason": self.reason,
        }

    def trace_output(self) -> dict[str, Any]:
        """Raw output persisted with a blocked turn's trace, marked as an explicit gate outcome."""
        output = {
            "source": EXECUTION_GATE_TRACE_SOURCE,
            "profile_status": self.status,
            "decision_source": self.decision_source,
            "reason": self.reason,
            **gate_outcome_marker(
                gate=EXECUTION_GATE_TRACE_SOURCE, label="execution gate", status=self.status, reason=self.reason
            ),
        }
        return output


def _pending_workflow_proposal(profile: dict[str, Any]) -> bool:
    policy = profile.get("policy") if isinstance(profile.get("policy"), dict) else {}
    return policy.get("source") == WORKFLOW_PROPOSAL_SOURCE and policy.get("status") == STATUS_NEEDS_CONFIRMATION


def _missing_origin(profile: dict[str, Any]) -> bool:
    """The run recorded no origin at all (``run_capability.resolution``: ``missing_declaration``)."""
    capability = profile.get("capability") if isinstance(profile.get("capability"), dict) else {}
    return capability.get("source") == _CAPABILITY_SOURCE_MISSING_DECLARATION


def evaluate_execution_gate(execution_profile: Any) -> ExecutionGateDecision:
    """Decide whether the runtime may start the agent loop for this turn."""
    if execution_profile is None:
        return ExecutionGateDecision(
            allowed=False,
            status=EXECUTION_PROFILE_STATUS_DENIED,
            decision_source=GATE_SOURCE_MISSING_PROFILE,
            reason="No execution profile was recorded for this turn.",
            user_message=(
                "This request was not executed because no execution profile was "
                "recorded for the turn. Run preparation should always produce one; "
                "please send the request again and have an administrator review the "
                "session if this repeats."
            ),
        )
    profile = execution_profile if isinstance(execution_profile, dict) else {}
    status = str(profile.get("status") or "").strip().lower()
    profile_reason = str(profile.get("reason") or "").strip()

    if status == EXECUTION_PROFILE_STATUS_ALLOWED and _pending_workflow_proposal(profile):
        return ExecutionGateDecision(
            allowed=False,
            status=GATE_STATUS_NEEDS_CONFIRMATION,
            decision_source=GATE_SOURCE_WORKFLOW_PROPOSAL,
            reason="A proposed workflow is waiting for the user's confirmation.",
            user_message=_NEEDS_CONFIRMATION_MESSAGE,
        )
    if status == EXECUTION_PROFILE_STATUS_ALLOWED:
        return ExecutionGateDecision(
            allowed=True,
            status=status,
            decision_source=GATE_SOURCE_PROFILE,
            reason=profile_reason or "Execution profile allowed this turn.",
            user_message="",
        )

    blocked_message = _BLOCKED_STATUS_MESSAGES.get(status)
    if blocked_message is not None:
        user_message = blocked_message
        if _missing_origin(profile):
            user_message = _MISSING_ORIGIN_MESSAGE
        elif profile_reason:
            user_message = f"{blocked_message}\n\nReason: {profile_reason}"
        return ExecutionGateDecision(
            allowed=False,
            status=status,
            decision_source=GATE_SOURCE_PROFILE,
            reason=profile_reason or f"Execution profile status is '{status}'.",
            user_message=user_message,
        )

    return ExecutionGateDecision(
        allowed=False,
        status=status or "missing",
        decision_source=GATE_SOURCE_UNKNOWN_STATUS,
        reason=f"Execution profile status '{status or 'missing'}' is not a known state.",
        user_message=(
            "This request was not executed because its execution state could not be "
            "determined. Please send the request again; if this repeats, an "
            "administrator should review the session's execution profile."
        ),
    )


__all__ = [
    "GATE_SOURCE_MISSING_PROFILE",
    "GATE_SOURCE_PROFILE",
    "GATE_SOURCE_UNKNOWN_STATUS",
    "GATE_SOURCE_WORKFLOW_PROPOSAL",
    "GATE_STATUS_NEEDS_CONFIRMATION",
    "ExecutionGateDecision",
    "evaluate_execution_gate",
]
