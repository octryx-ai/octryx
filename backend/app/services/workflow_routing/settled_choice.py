"""Whether a chat turn's workflow choice is already settled before the model runs.

Sending the Workflow catalog (~1.7k characters) and the ``select_workflow`` schema (~0.5k) with every chat model
call is waste when the router has already read the full catalog for this very message, or the person has chosen in
the composer. So when the choice is settled, the turn gets neither;
switching stays possible through ``list_available_workflows`` behind tool_search.

Not settled: the router could not decide (failure, timeout, no runtime, content refused, scope changed) or is
switched off, or a non-chat routing source (a DB policy match, a run phase) drives the turn. Then the catalog stays the
model's way to pick a workflow.
"""

from __future__ import annotations

from typing import Any

from .proposal_states import WORKFLOW_PROPOSAL_KEY, WORKFLOW_PROPOSAL_VERSION

COMPOSER_SELECTION_SOURCE = "explicit_workflow_key"
_UNDECIDED_REASONS = frozenset({
    "model_refused", "model_unavailable", "timeout", "proposal_failed", "invalid_answer", "admission_denied",
    "admission_needs_configuration", "no_runtime_configured", "content_blocked", "proposal_scope_changed",
    "policy_disabled", "no_published_definitions", "empty_message",
})


def workflow_choice_settled(routing_resolution: Any) -> bool:
    """True when the composer chose a workflow or the router decided this message (a workflow or none)."""
    if not isinstance(routing_resolution, dict):
        return False
    if routing_resolution.get("source") == COMPOSER_SELECTION_SOURCE:
        return True
    record = routing_resolution.get(WORKFLOW_PROPOSAL_KEY)
    if not isinstance(record, dict) or record.get("version") != WORKFLOW_PROPOSAL_VERSION:
        return False
    return str(record.get("reason_code") or "") not in _UNDECIDED_REASONS


__all__ = ["workflow_choice_settled"]
