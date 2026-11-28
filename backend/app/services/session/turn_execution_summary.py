"""Pure builder of the ``turn_execution_summary.v1`` read model of one agent turn."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.agent.runtime.runtime_errors import RUNTIME_ERROR_ALIAS_DENIED, RUNTIME_ERROR_DATA_POLICY_DENIED
from app.services.execution_profile_status import EXECUTION_PROFILE_STATUS_ALLOWED

from ..answer_evidence.record import read_answer_evidence
from ..execution_profile_service import EXECUTION_PROFILE_VERSION
from ..prompt_catalog import render_prompt
from ..workflow_checks.results import read_workflow_checks
from ..workflow_contracts.decisions import read_workflow_decision_request
from .execution_gate import GATE_SOURCE_PROFILE, GATE_SOURCE_WORKFLOW_PROPOSAL, GATE_STATUS_NEEDS_CONFIRMATION
from .turn_execution_snapshot import (
    RUNTIME_OUTCOME_FINISHED,
    RUNTIME_OUTCOME_KEY,
    RUNTIME_OUTCOME_STOPPED,
    RUNTIME_STOP_REASON_KEY,
    UNKNOWN_VALUE,
    closed_value,
    read_agent_reply_contract,
    read_turn_execution_snapshot,
    safe_token,
)
from .turn_run_identity import ResolvedTurnRun, build_run_identity

TURN_EXECUTION_SUMMARY_VERSION = "turn_execution_summary.v1"

SUMMARY_STATES = (
    "finished_unverified",
    "denied",
    "needs_approval",
    "needs_configuration",
    "needs_clarification",
    "needs_confirmation",
    # A phased workflow's start was confirmed and its run started (``workflow_routing.phased_start``).
    "started",
    "blocked_unknown",
    "waiting_approval",
    "stopped",
    "failed",
    "cancelled",
    "unknown",
)
RUNTIME_OUTCOMES = frozenset({"finished", "stopped", "failed", "cancelled"})
TOOL_CALL_STATUSES = frozenset({"success", "error"})
APPROVAL_STATUSES = frozenset({"pending", "approved", "rejected", "denied", "expired", "cancelled"})
MAX_CAPABILITIES = 50
MAX_APPROVALS = 20
MAX_ARTIFACTS = 50
_MAX_COUNT = 10**12

# Gate-blocked statuses that map one-to-one onto a summary state.
_GATE_BLOCKED_STATES = frozenset({"denied", "needs_approval", "needs_configuration", "needs_clarification"})

# A failed dispatch that the model gateway's admission refused before any request is
# a governance outcome, not a runtime failure; keyed by the typed admission class.
_ADMISSION_REFUSAL_REASONS = {
    RUNTIME_ERROR_ALIAS_DENIED: "model_alias_not_admitted",
    RUNTIME_ERROR_DATA_POLICY_DENIED: "model_data_policy_denied",
}

# Fixed server-owned explanations: (source, text). Free-text profile/gate reasons are
# never forwarded because they can echo user input or internal configuration.
_REASONS: dict[str, tuple[str, str]] = {
    "runtime_finished": ("runtime", "The agent turn finished; no verification contract checked its result."),
    "runtime_failed": ("runtime", "The agent turn failed before it finished."),
    "runtime_cancelled": ("runtime", "The agent turn was cancelled."),
    "runtime_stopped_step_tool_required": (
        "runtime",
        "The agent stopped: a step that must use one of its tools answered without one after a reminder.",
    ),
    "runtime_stopped_step_stalled": (
        "runtime",
        "The agent stopped: its final step kept answering without its required tools until its attempt limit.",
    ),
    "runtime_stopped_answer_evidence_uncited": (
        "runtime",
        "The answer was withheld: after a reminder it still did not cite the sources this turn found.",
    ),
    "runtime_stopped_answer_evidence_invented_url": (
        "runtime",
        "The answer was withheld: after a reminder it still cited a link none of this turn's sources contain.",
    ),
    # The agent's checked reply format refused its final reply (shown unchanged, never repaired).
    "runtime_stopped_agent_reply_not_json": (
        "runtime",
        "The agent stopped: its final reply is not the single JSON object its reply format requires.",
    ),
    "runtime_stopped_agent_reply_schema_mismatch": (
        "runtime",
        "The agent stopped: its final reply does not match the fields its reply format declares.",
    ),
    "runtime_stopped_agent_reply_contract_invalid": (
        "runtime",
        "The agent stopped: its reply format is not valid, so its final reply could not be checked.",
    ),
    "runtime_outcome_unknown": ("runtime", "The runtime outcome of this turn is not recorded."),
    "intermediate_trace": ("runtime", "This step is part of a longer turn; the turn's last message shows its outcome."),
    "approval_pending": ("approval", "A tool action in this turn is waiting for an approval decision."),
    "approval_state_unknown": ("approval", "An approval requested in this turn could not be resolved."),
    "clarification_requested": ("runtime", "The agent paused this turn to ask for clarification."),
    "workflow_decision_requested": ("workflow", "The workflow paused this turn until you record a decision."),
    "gate_denied": ("execution_gate", "Execution policy denied this request; it was not executed."),
    "gate_needs_approval": ("execution_gate", "This request requires an approval before it can run."),
    "gate_needs_configuration": ("execution_gate", "This request requires configuration before it can run."),
    "gate_needs_clarification": ("execution_gate", "This request needs clarification before it can run."),
    "gate_needs_confirmation": ("execution_gate", "A suggested workflow waits for your confirmation; nothing ran."),
    "workflow_run_started": ("workflow", "The workflow run started for its Work item; it continues in its own chat."),
    "gate_needs_start_confirmation": ("execution_gate", "A workflow run waits for your start; nothing ran yet."),
    "gate_blocked_unknown": ("execution_gate", "The request was blocked because its execution state is unclear."),
    "model_alias_not_admitted": (
        "model_admission",
        "This project is not granted the model alias for this request; no model was called.",
    ),
    "model_data_policy_denied": (
        "model_admission",
        "The Workspace data policy does not permit this request on this model alias; no model was called.",
    ),
    "missing_snapshot": ("trace", "No execution decision was recorded for this turn."),
    "malformed_snapshot": ("trace", "The recorded execution decision for this turn is not readable."),
    "inconsistent_snapshot": ("trace", "The recorded execution decision for this turn is inconsistent."),
}

_CONTACT_ADMIN = "contact_administrator"
_NO_ACTION: tuple[str, str | None] = ("none", None)

# One server-provided next action per reason: (kind, label). A gate-level
# ``needs_approval`` creates no Approval row, so it never points at a pending one.
_NEXT_ACTIONS: dict[str, tuple[str, str | None]] = {
    "runtime_finished": _NO_ACTION,
    "runtime_failed": ("retry", "Send the request again."),
    "runtime_cancelled": ("retry", "Send the request again."),
    "runtime_stopped_step_tool_required": (
        "complete_configuration",
        "Rephrase the request so the step can use its tools, or ask an administrator to set its tool use to optional.",
    ),
    "runtime_stopped_step_stalled": (
        "complete_configuration",
        "Ask an administrator to review the agent's final step and its tools.",
    ),
    "runtime_stopped_answer_evidence_uncited": (
        "retry",
        "Open the sources this turn found, or send the request again.",
    ),
    "runtime_stopped_answer_evidence_invented_url": (
        "retry",
        "Open the sources this turn found, or send the request again.",
    ),
    "runtime_stopped_agent_reply_not_json": (
        "retry",
        "Send the request again, or ask an administrator to review the agent's reply format.",
    ),
    "runtime_stopped_agent_reply_schema_mismatch": (
        "retry",
        "Send the request again, or ask an administrator to review the agent's reply format.",
    ),
    "runtime_stopped_agent_reply_contract_invalid": (
        "complete_configuration",
        "Ask an administrator to fix the agent's reply format.",
    ),
    "runtime_outcome_unknown": _NO_ACTION,
    "intermediate_trace": _NO_ACTION,
    "approval_pending": ("resolve_approval", "Approve or reject the pending action."),
    "approval_state_unknown": (_CONTACT_ADMIN, "Ask an administrator to check the approval requested in this turn."),
    "clarification_requested": ("provide_clarification", "Answer the agent's question to continue."),
    "workflow_decision_requested": ("provide_clarification", "Choose one of the offered decisions to continue."),
    "gate_denied": (_CONTACT_ADMIN, "Ask an administrator to review the execution policy."),
    "gate_needs_approval": (
        _CONTACT_ADMIN,
        "Ask an administrator to authorize this kind of request; no approval request was created.",
    ),
    "gate_needs_configuration": ("complete_configuration", "Complete the missing configuration, then retry."),
    "gate_needs_clarification": ("provide_clarification", "Restate the request with the missing details."),
    # The label is prompt catalog data (``workflow.proposal.gate_needs_confirmation``), rendered at build time.
    "gate_needs_confirmation": ("confirm_workflow_proposal", None),
    "workflow_run_started": _NO_ACTION,
    # The start card's own words, not the proposal's.
    "gate_needs_start_confirmation": (
        "confirm_workflow_proposal", "Start the run, choose another workflow, or don't start."),
    "gate_blocked_unknown": (_CONTACT_ADMIN, "Ask an administrator to review this session."),
    "model_alias_not_admitted": (
        "complete_configuration",
        "Ask an administrator to grant the model alias to this project, then retry.",
    ),
    "model_data_policy_denied": (_CONTACT_ADMIN, "Ask an administrator to review the model's data policy."),
    "missing_snapshot": _NO_ACTION,
    "malformed_snapshot": _NO_ACTION,
    "inconsistent_snapshot": _NO_ACTION,
}


_CATALOG_ACTION_LABELS = {"gate_needs_confirmation": "workflow.proposal.gate_needs_confirmation"}


@dataclass(frozen=True, slots=True)
class TurnToolCallEvidence:
    name: Any
    status: Any
    # How many calls this entry stands for (an agent step's aggregated tool-call fact).
    count: int = 1


@dataclass(frozen=True, slots=True)
class TurnApprovalEvidence:
    approval_id: Any
    tool_name: Any
    status: Any
    created_at: str | None = None
    resolved_at: str | None = None


@dataclass(frozen=True, slots=True)
class TurnArtifactEvidence:
    artifact_id: Any
    tool_name: Any
    size_bytes: Any
    created_at: str | None = None


@dataclass(frozen=True, slots=True)
class TurnExecutionEvidence:
    trace_id: str
    session_id: str
    message_id: str | None
    provider: Any
    model: Any
    context_snapshot: Any
    runtime_outcome: str
    # The model gateway admission class that refused every runtime target of a
    # failed dispatch (``product_run.turn_outcome.admission_refusal_of_trace``).
    admission_refusal: str | None = None
    # A later trace of the same user turn exists; this trace is not terminal.
    intermediate: bool = False
    clarification_requested: bool = False
    # Structured workflow decision request of the final trace (engine/decisions.py).
    decision_request: Any = None
    usage: Any = None
    tool_calls: tuple[TurnToolCallEvidence, ...] = field(default_factory=tuple)
    approvals: tuple[TurnApprovalEvidence, ...] = field(default_factory=tuple)
    artifacts: tuple[TurnArtifactEvidence, ...] = field(default_factory=tuple)
    # The stamped Run/Attempt as stored, resolved owner-scoped (``turn_run_identity``).
    product_run: ResolvedTurnRun | None = None
    # What content policies changed or refused in this turn (closed ``content_routing.notices``; final trace only).
    content_obligations: tuple[dict[str, Any], ...] = ()
    # The turn was held for a phased workflow's start and the person's Allow started its run (``phased_start``).
    workflow_run_started: bool = False


def runtime_outcome_from_trace(context_snapshot: Any, raw_output: Any) -> str:
    # Explicit markers only: a trace without error and without marker is ``unknown``.
    if isinstance(raw_output, dict) and raw_output.get("error"):
        return "failed"
    if (device := _device_outcome(context_snapshot, raw_output)) is not None:
        return device
    _status, snapshot = read_turn_execution_snapshot(context_snapshot)
    if snapshot is not None and snapshot[RUNTIME_OUTCOME_KEY] == RUNTIME_OUTCOME_FINISHED:
        return "finished"
    if snapshot is not None and snapshot[RUNTIME_OUTCOME_KEY] == RUNTIME_OUTCOME_STOPPED:
        return "stopped"
    return UNKNOWN_VALUE


# A Mac turn's trace (devices/run_trace.py) has no execution snapshot: the device reports the outcome itself
# (``device_status``), and the platform marks a refused or failed job (``status``). Without
# reading them, every Mac answer, the run's independent review among them, reads "Status unknown · No execution
# decision was recorded".
DEVICE_TRACE_SOURCE = "device"


def _is_device_trace(context_snapshot: Any) -> bool:
    return isinstance(context_snapshot, dict) and context_snapshot.get("source") == DEVICE_TRACE_SOURCE


def _device_outcome(context_snapshot: Any, raw_output: Any) -> str | None:
    if not _is_device_trace(context_snapshot) or not isinstance(raw_output, dict):
        return None
    if raw_output.get("status") in ("failed", "blocked"):
        return "failed"
    reported = str(raw_output.get("device_status") or "")
    if not reported:
        return None
    return {"success": "finished", "stopped": "stopped"}.get(reported, "failed")


def _bounded_count(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > _MAX_COUNT:
        return None
    return value


def _usage(usage: Any) -> dict[str, int | None]:
    data = usage if isinstance(usage, dict) else {}
    tokens_in = data.get("prompt_tokens", data.get("input_tokens"))
    tokens_out = data.get("completion_tokens", data.get("output_tokens"))
    return {"tokens_in": _bounded_count(tokens_in), "tokens_out": _bounded_count(tokens_out)}


def _capabilities(tool_calls: tuple[TurnToolCallEvidence, ...]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for call in tool_calls:
        name = safe_token(call.name)
        if name is None:
            continue
        count = _bounded_count(call.count)
        if not count:
            continue
        entry = grouped.setdefault(name, {"name": name, "calls": 0, "succeeded": 0, "failed": 0})
        entry["calls"] += count
        status = closed_value(call.status, TOOL_CALL_STATUSES)
        if status == "success":
            entry["succeeded"] += count
        elif status == "error":
            entry["failed"] += count
    return list(grouped.values())[:MAX_CAPABILITIES]


def _approvals(approvals: tuple[TurnApprovalEvidence, ...]) -> list[dict[str, Any]]:
    return [
        {
            "approval_id": safe_token(item.approval_id),
            "tool_name": safe_token(item.tool_name),
            "status": closed_value(item.status, APPROVAL_STATUSES),
            "created_at": safe_token(item.created_at),
            "resolved_at": safe_token(item.resolved_at),
        }
        for item in approvals[:MAX_APPROVALS]
    ]


def _artifacts(artifacts: tuple[TurnArtifactEvidence, ...]) -> list[dict[str, Any]]:
    return [
        {
            "artifact_id": safe_token(item.artifact_id),
            "tool_name": safe_token(item.tool_name),
            "size_bytes": _bounded_count(item.size_bytes),
            "created_at": safe_token(item.created_at),
        }
        for item in artifacts[:MAX_ARTIFACTS]
    ]


def _profile_section(snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    if snapshot is None:
        return None
    profile = snapshot["execution_profile"]
    gate = snapshot["gate"]
    return {
        "version": profile["version"] if profile["version"] == EXECUTION_PROFILE_VERSION else None,
        "profile_id": profile["profile_id"],
        "status": profile["status"],
        "decision_source": profile["decision_source"],
        "workflow_key": profile["workflow_key"],
        "execution_strategy": profile["execution_strategy"],
        # The run capability this turn executed under, and whether the user's
        # capability_escalation decision raised it (services/run_capability).
        "capability": dict(profile["capability"]),
        "tool_surface": dict(snapshot["tool_surface"]),  # source and governed set key
        "gate": {
            "outcome": "allowed" if gate["allowed"] else "blocked",
            "status": gate["status"],
            "decision_source": gate["decision_source"],
        },
    }


def _allowed_turn_state(
    evidence: TurnExecutionEvidence, approvals: list[dict[str, Any]], snapshot: dict[str, Any]
) -> str:
    if evidence.intermediate is True:
        return "intermediate_trace"
    outcome = closed_value(evidence.runtime_outcome, RUNTIME_OUTCOMES)
    if outcome == "failed":
        return _ADMISSION_REFUSAL_REASONS.get(evidence.admission_refusal or "", "runtime_failed")
    if outcome == "cancelled":
        return "runtime_cancelled"
    if outcome == "stopped":
        # The stop reason is closed by the snapshot reader; a stop without one never gets here.
        return f"runtime_stopped_{snapshot[RUNTIME_STOP_REASON_KEY]}"
    # Pending approvals and clarification pauses are explicit per-turn evidence and
    # never claim completion, so they apply even before a finished marker exists.
    pending = [item for item in approvals if item["status"] == "pending"]
    if pending:
        return "approval_pending"
    if any(item["status"] == UNKNOWN_VALUE for item in approvals):
        return "approval_state_unknown"
    if read_workflow_decision_request(evidence.decision_request) is not None:
        return "workflow_decision_requested"
    if evidence.clarification_requested is True:
        return "clarification_requested"
    if outcome == "finished":
        return "runtime_finished"
    return "runtime_outcome_unknown"


_STATE_BY_REASON: dict[str, str] = {
    "runtime_finished": "finished_unverified",
    "runtime_failed": "failed",
    "runtime_cancelled": "cancelled",
    "runtime_stopped_step_tool_required": "stopped",
    "runtime_stopped_step_stalled": "stopped",
    "runtime_stopped_answer_evidence_uncited": "stopped",
    "runtime_stopped_answer_evidence_invented_url": "stopped",
    "runtime_stopped_agent_reply_not_json": "stopped",
    "runtime_stopped_agent_reply_schema_mismatch": "stopped",
    "runtime_stopped_agent_reply_contract_invalid": "stopped",
    "runtime_outcome_unknown": "unknown",
    "intermediate_trace": "unknown",
    "approval_pending": "waiting_approval",
    "approval_state_unknown": "unknown",
    "clarification_requested": "needs_clarification",
    "workflow_decision_requested": "needs_clarification",
    "gate_denied": "denied",
    "gate_needs_approval": "needs_approval",
    "gate_needs_configuration": "needs_configuration",
    "gate_needs_clarification": "needs_clarification",
    "gate_needs_confirmation": "needs_confirmation",
    "workflow_run_started": "started",
    "gate_needs_start_confirmation": "needs_confirmation",
    "gate_blocked_unknown": "blocked_unknown",
    "model_alias_not_admitted": "needs_configuration",
    "model_data_policy_denied": "denied",
    "missing_snapshot": "unknown",
    "malformed_snapshot": "unknown",
    "inconsistent_snapshot": "unknown",
}


# The device's own outcome: finished is unverified (the platform did not check the answer), stopped is the owner's.
_DEVICE_REASON = {"finished": "runtime_finished", "failed": "runtime_failed", "stopped": "runtime_cancelled"}


def _reason_code(
    evidence: TurnExecutionEvidence,
    snapshot_status: str,
    snapshot: dict[str, Any] | None,
    approvals: list[dict[str, Any]],
) -> str:
    if snapshot_status == "missing":
        if _is_device_trace(evidence.context_snapshot):
            return _DEVICE_REASON.get(evidence.runtime_outcome, "runtime_outcome_unknown")
        return "missing_snapshot"
    if snapshot is None:
        return "malformed_snapshot"
    profile = snapshot["execution_profile"]
    gate = snapshot["gate"]
    if gate["allowed"]:
        # An allowed gate must agree with an allowed v1 profile; anything else is
        # corrupted state and must never render as a finished turn.
        if profile["status"] != EXECUTION_PROFILE_STATUS_ALLOWED or profile["version"] != EXECUTION_PROFILE_VERSION:
            return "inconsistent_snapshot"
        return _allowed_turn_state(evidence, approvals, snapshot)
    if gate["decision_source"] == GATE_SOURCE_PROFILE and gate["status"] in _GATE_BLOCKED_STATES:
        if profile["status"] != gate["status"]:
            return "inconsistent_snapshot"
        if gate["status"] == "needs_clarification" and read_workflow_decision_request(evidence.decision_request):
            # The gate held the turn for a closed workflow decision: offer its options.
            return "workflow_decision_requested"
        return f"gate_{gate['status']}"
    if gate["decision_source"] == GATE_SOURCE_WORKFLOW_PROPOSAL and gate["status"] == GATE_STATUS_NEEDS_CONFIRMATION:
        # The proposal gate blocks an otherwise allowed profile, and only for a recorded
        # pending proposal; anything else is corrupted state.
        proposal = snapshot.get("workflow_proposal") or {}
        if profile["status"] != EXECUTION_PROFILE_STATUS_ALLOWED or proposal.get("status") != "needs_confirmation":
            return "inconsistent_snapshot"
        # A held turn whose run has started no longer waits for confirmation.
        if evidence.workflow_run_started:
            return "workflow_run_started"
        return "gate_needs_start_confirmation" if proposal.get("phased") else "gate_needs_confirmation"
    return "gate_blocked_unknown"


def build_turn_execution_summary(evidence: TurnExecutionEvidence) -> dict[str, Any]:
    snapshot_status, snapshot = read_turn_execution_snapshot(evidence.context_snapshot)
    approvals = _approvals(evidence.approvals)
    reason_code = _reason_code(evidence, snapshot_status, snapshot, approvals)
    run_identity = build_run_identity(evidence.context_snapshot, evidence.product_run)
    state = _STATE_BY_REASON[reason_code]
    reason_source, reason_text = _REASONS[reason_code]
    action_kind, action_label = _NEXT_ACTIONS[reason_code]
    if reason_code in _CATALOG_ACTION_LABELS:
        action_label = render_prompt(_CATALOG_ACTION_LABELS[reason_code])
    gate_blocked = snapshot is not None and not snapshot["gate"]["allowed"]
    agent = snapshot["agent"] if snapshot is not None else {"id": None, "name": None, "selection_source": None}
    return {
        "version": TURN_EXECUTION_SUMMARY_VERSION,
        "trace_id": safe_token(evidence.trace_id),
        "session_id": safe_token(evidence.session_id),
        "message_id": safe_token(evidence.message_id),
        "run_identity": run_identity,
        "state": state,
        "state_reason": {"code": reason_code, "source": reason_source, "text": reason_text},
        "next_action": {"kind": action_kind, "label": action_label},
        "execution_profile": _profile_section(snapshot),
        "agent": {"id": agent["id"], "name": agent["name"], "selection_source": agent["selection_source"]},
        # A gate-blocked turn never reached a model; its trace provider is the gate.
        "model": {
            "provider": None if gate_blocked else safe_token(evidence.provider),
            "model": None if gate_blocked else safe_token(evidence.model),
        },
        "capabilities_used": _capabilities(evidence.tool_calls),
        "approvals": approvals,
        "artifacts": _artifacts(evidence.artifacts),
        "usage": _usage(evidence.usage),
        # Closed options only (re-derived from the decision catalog), and only while the
        # turn's state is the decision request itself.
        "decision_request": (
            read_workflow_decision_request(evidence.decision_request)
            if reason_code == "workflow_decision_requested"
            else None
        ),
        # Closed proposal fields only (status, reason code, key, display title, confidence);
        # the model-written reason is never part of the summary.
        "workflow_proposal": snapshot.get("workflow_proposal") if snapshot is not None else None,
        # The answer evidence guard's closed decision and counts (``unsourced`` is the UI marker); else null.
        "answer_evidence": read_answer_evidence(evidence.context_snapshot),
        # The selected workflow's check result on this trace: state, whether reminded, per-check outcome.
        "workflow_checks": read_workflow_checks(evidence.context_snapshot),
        # The checked reply format's closed result on this trace; null for text or unchecked replies.
        "reply_contract": read_agent_reply_contract(evidence.context_snapshot),
        # Content policy notices: kind, reason, detector counts, policies, decision, model change; no data.
        "content_obligations": list(evidence.content_obligations),
    }


__all__ = [
    "SUMMARY_STATES",
    "TURN_EXECUTION_SUMMARY_VERSION",
    "TurnApprovalEvidence",
    "TurnArtifactEvidence",
    "TurnExecutionEvidence",
    "TurnToolCallEvidence",
    "build_turn_execution_summary",
    "runtime_outcome_from_trace",
]
