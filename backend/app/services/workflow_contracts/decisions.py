"""Explicit workflow decisions: the structured answer to a closed decision question.

A run-capability refusal (``services/run_capability/escalation``) stops a turn at a decision
boundary. The user's answer is never read from the prompt text. It arrives as the structured
``workflow_decisions`` field of the next send request (``{"<decision key>": "<value>"}``) on
``/api/v1/sessions/{id}/messages`` or ``/chat/api`` send, is validated against the closed
catalog below, is recorded in session metadata (``workflow_decisions``), and is folded into
every later turn's workflow contract and run capability. Readers take the decision from there only.

A recorded decision stays in force for the session until a later request records a different
value for the same key.

When a decision is asked, the loop persists a structured *decision request*
(:func:`build_workflow_decision_request`) on the clarification message's trace
(``raw_output.workflow_decision_request``). The turn execution summary re-validates it
(:func:`read_workflow_decision_request`) and hands the closed options to the chat UI, which
renders them as buttons. Clients never parse the options from the message text.
"""

from __future__ import annotations

from typing import Any

WORKFLOW_DECISIONS_KEY = "workflow_decisions"

CAPABILITY_ESCALATION_DECISION = "capability_escalation"
"""Whether a read-only session may raise its run capability to ``change`` (``services/run_capability``)."""

ALLOW_CHANGES = "allow_changes"
"""Raise this session's run capability to ``change``; ``deliver`` is never granted this way."""

STAY_READ_ONLY = "stay_read_only"
"""Keep this session read-only; capability refusals are answered without asking again."""

WORKFLOW_DECISION_OPTIONS: dict[str, tuple[str, ...]] = {
    CAPABILITY_ESCALATION_DECISION: (ALLOW_CHANGES, STAY_READ_ONLY),
}

WORKFLOW_DECISION_REQUEST_KEY = "workflow_decision_request"
"""Key of the structured decision request on a clarification message's trace ``raw_output``."""

# Fixed, server-owned button labels per decision value (never user or model text).
WORKFLOW_DECISION_OPTION_LABELS: dict[str, dict[str, str]] = {
    CAPABILITY_ESCALATION_DECISION: {
        ALLOW_CHANGES: "Allow changes in this session",
        STAY_READ_ONLY: "Stay read-only",
    },
}


class WorkflowDecisionError(ValueError):
    """A requested decision names an unknown key or a value outside its closed options."""


def validate_workflow_decisions(raw: Any) -> dict[str, str]:
    """Return the decisions as a clean mapping, or raise :class:`WorkflowDecisionError`."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise WorkflowDecisionError("workflow_decisions must be an object of decision key to value")
    decisions: dict[str, str] = {}
    for raw_key, raw_value in raw.items():
        key = str(raw_key or "").strip()
        options = WORKFLOW_DECISION_OPTIONS.get(key)
        if options is None:
            raise WorkflowDecisionError(f"unknown workflow decision: {key or '<empty>'}")
        value = str(raw_value or "").strip() if isinstance(raw_value, str) else ""
        if value not in options:
            raise WorkflowDecisionError(f"workflow decision {key} must be one of: {', '.join(options)}")
        decisions[key] = value
    return decisions


def recorded_workflow_decisions(session_metadata: dict[str, Any] | None) -> dict[str, str]:
    """The valid decisions recorded on a session; malformed entries are dropped (fail closed)."""
    stored = (session_metadata or {}).get(WORKFLOW_DECISIONS_KEY)
    if not isinstance(stored, dict):
        return {}
    return {
        key: value
        for key, value in stored.items()
        if isinstance(value, str) and value in WORKFLOW_DECISION_OPTIONS.get(key, ())
    }


def record_workflow_decisions(metadata: dict[str, Any], decisions: dict[str, str] | None) -> None:
    """Merge validated ``decisions`` into the session ``metadata`` in place (a later value wins)."""
    if not decisions:
        return
    metadata[WORKFLOW_DECISIONS_KEY] = {**recorded_workflow_decisions(metadata), **decisions}


def apply_workflow_decisions_to_contract(
    workflow_contract: dict[str, Any] | None,
    session_metadata: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Carry the session's recorded decisions on the turn's workflow contract."""
    if not isinstance(workflow_contract, dict) or not workflow_contract:
        return workflow_contract
    decisions = recorded_workflow_decisions(session_metadata)
    if not decisions:
        return workflow_contract
    return {**workflow_contract, WORKFLOW_DECISIONS_KEY: decisions}


def workflow_decision(workflow_contract: dict[str, Any] | None, key: str) -> str:
    """The contract's recorded value for ``key``, or ``""`` when the decision is still open."""
    contract = workflow_contract if isinstance(workflow_contract, dict) else {}
    return recorded_workflow_decisions(contract).get(key, "")


def build_workflow_decision_request(key: str, workflow_contract: dict[str, Any] | None) -> dict[str, Any] | None:
    """The structured request for decision ``key`` with its closed options, or ``None``.

    ``recorded_value`` is the value already recorded on the contract (``None`` while open),
    so a hold notice can offer the other option without repeating the current one.
    """
    options = WORKFLOW_DECISION_OPTIONS.get(str(key or ""))
    if options is None:
        return None
    labels = WORKFLOW_DECISION_OPTION_LABELS.get(key, {})
    return {
        "decision_key": key,
        "options": [{"value": value, "label": labels.get(value, value)} for value in options],
        "recorded_value": workflow_decision(workflow_contract, key) or None,
    }


def read_workflow_decision_request(raw: Any) -> dict[str, Any] | None:
    """Re-validate a persisted decision request against the closed catalog (fail closed).

    The options and labels are always re-derived from the catalog, so a stored value can only
    select a known decision, never inject its own options or text.
    """
    if not isinstance(raw, dict):
        return None
    key = raw.get("decision_key")
    if not isinstance(key, str) or key not in WORKFLOW_DECISION_OPTIONS:
        return None
    recorded = raw.get("recorded_value")
    contract = {WORKFLOW_DECISIONS_KEY: {key: recorded}} if isinstance(recorded, str) else None
    return build_workflow_decision_request(key, contract)


__all__ = [
    "ALLOW_CHANGES",
    "CAPABILITY_ESCALATION_DECISION",
    "STAY_READ_ONLY",
    "WORKFLOW_DECISIONS_KEY",
    "WORKFLOW_DECISION_OPTIONS",
    "WORKFLOW_DECISION_OPTION_LABELS",
    "WORKFLOW_DECISION_REQUEST_KEY",
    "WorkflowDecisionError",
    "apply_workflow_decisions_to_contract",
    "build_workflow_decision_request",
    "read_workflow_decision_request",
    "record_workflow_decisions",
    "recorded_workflow_decisions",
    "validate_workflow_decisions",
    "workflow_decision",
]
