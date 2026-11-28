"""Explicit workflow decisions: the structured answer to a closed decision question."""

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
    pass


def validate_workflow_decisions(raw: Any) -> dict[str, str]:
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
    stored = (session_metadata or {}).get(WORKFLOW_DECISIONS_KEY)
    if not isinstance(stored, dict):
        return {}
    return {
        key: value
        for key, value in stored.items()
        if isinstance(value, str) and value in WORKFLOW_DECISION_OPTIONS.get(key, ())
    }


def record_workflow_decisions(metadata: dict[str, Any], decisions: dict[str, str] | None) -> None:
    if not decisions:
        return
    metadata[WORKFLOW_DECISIONS_KEY] = {**recorded_workflow_decisions(metadata), **decisions}


def apply_workflow_decisions_to_contract(
    workflow_contract: dict[str, Any] | None,
    session_metadata: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(workflow_contract, dict) or not workflow_contract:
        return workflow_contract
    decisions = recorded_workflow_decisions(session_metadata)
    if not decisions:
        return workflow_contract
    return {**workflow_contract, WORKFLOW_DECISIONS_KEY: decisions}


def workflow_decision(workflow_contract: dict[str, Any] | None, key: str) -> str:
    contract = workflow_contract if isinstance(workflow_contract, dict) else {}
    return recorded_workflow_decisions(contract).get(key, "")


def build_workflow_decision_request(key: str, workflow_contract: dict[str, Any] | None) -> dict[str, Any] | None:
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
