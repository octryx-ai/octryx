"""Bounded per-turn snapshot of the execution profile and execution-gate decision.

The session's ``execution_profile`` metadata is overwritten on every turn, so it
cannot explain an older turn. ``run_agent`` captures this snapshot right after the
execution gate decided (allowed and blocked paths alike) and every ``TurnTrace``
persisted for that turn stores it under ``TURN_EXECUTION_SNAPSHOT_KEY`` inside
``context_snapshot_json`` (no schema migration; the key is written once per turn and
carried over when the loop refreshes the trace context).

Security contract: the snapshot is an allow-list projection. It never stores the
profile's free-text ``reason``, routing reasons, workflow contracts, policy
dictionaries, runtime/LLM-router payloads, or prompts. Every retained value is a
closed enum, a boolean, a bounded integer, or a charset-validated bounded token;
anything else is dropped to ``None`` (or ``"unknown"`` for enums). Readers re-validate
with the same rules so a malformed or foreign value can never pass through.

Turn identity: ``turn.user_message_id`` is the session's
``current_turn_user_message_id`` at preparation time, so every trace of one user turn
(tool-only assistant messages, suppressed traces, the final answer) shares it.
``turn.sequence`` is assigned per bound turn when a trace is stamped.

Runtime outcome: ``runtime_outcome`` is absent until the loop explicitly marks the
final trace: ``RUNTIME_OUTCOME_FINISHED`` for an accepted normal completion, or
``RUNTIME_OUTCOME_STOPPED`` with a closed ``runtime_stop_reason`` when a runtime guard
ended the turn with an explicit stop answer, including the answer-evidence guard's
final refusal and a final reply its agent's checked reply contract refused.
Readers drop anything else (and a stop without a recognised reason), so
a missing or foreign marker never reads as finished or stopped.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.agent_reply_contract_schema import (
    KIND_JSON_OBJECT,
    REASON_CONTRACT_INVALID,
    REASON_NOT_JSON,
    REASON_SCHEMA_MISMATCH,
    STATUS_SATISFIED,
    STATUS_VIOLATED,
)
from app.services.execution_profile_status import (
    EXECUTION_PROFILE_STATUS_ALLOWED,
    EXECUTION_PROFILE_STATUS_DENIED,
    EXECUTION_PROFILE_STATUS_NEEDS_APPROVAL,
    EXECUTION_PROFILE_STATUS_NEEDS_CLARIFICATION,
    EXECUTION_PROFILE_STATUS_NEEDS_CONFIGURATION,
)

from ..run_capability.classes import CAPABILITY_CLASSES
from ..workflow_routing.proposal_states import (
    PROPOSAL_CONFIDENCES,
    PROPOSAL_REASON_CODES,
    PROPOSAL_STATUSES,
    WORKFLOW_PROPOSAL_KEY,
    WORKFLOW_PROPOSAL_VERSION,
)
from ..workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY
from .agent_selection_sources import AGENT_SELECTION_SOURCE_METADATA_KEY, closed_agent_selection_source
from .execution_gate import (
    GATE_SOURCE_MISSING_PROFILE,
    GATE_SOURCE_PROFILE,
    GATE_SOURCE_UNKNOWN_STATUS,
    GATE_SOURCE_WORKFLOW_PROPOSAL,
    GATE_STATUS_NEEDS_CONFIRMATION,
    ExecutionGateDecision,
)
from .turn_tool_surface_record import (
    TOOL_SURFACE_SET_METADATA_KEY,
    TOOL_SURFACE_SOURCE_METADATA_KEY,
    TOOL_SURFACE_SOURCES,
)

TURN_EXECUTION_SNAPSHOT_KEY = "turn_execution_snapshot"
TURN_EXECUTION_SNAPSHOT_VERSION = "turn_execution_snapshot.v1"
RUNTIME_OUTCOME_KEY = "runtime_outcome"
RUNTIME_OUTCOME_FINISHED = "finished"
RUNTIME_OUTCOME_STOPPED = "stopped"
RUNTIME_STOP_REASON_KEY = "runtime_stop_reason"
# Closed stop reasons: a final step that must use a tool declined after one reminder,
# or kept answering without its required tools until the step's attempt limit; or the
# answer-evidence guard withheld the final answer after its one reminder because it still
# cited none of the turn's sources, or cited a link no source of the turn carries.
RUNTIME_STOP_STEP_TOOL_REQUIRED = "step_tool_required"
RUNTIME_STOP_STEP_STALLED = "step_stalled"
RUNTIME_STOP_ANSWER_EVIDENCE_UNCITED = "answer_evidence_uncited"
RUNTIME_STOP_ANSWER_EVIDENCE_INVENTED_URL = "answer_evidence_invented_url"
# The agent's checked reply contract refused the final reply: one stop reason per
# closed validator code (``services/agent_reply_contract.check_reply``), same spelling.
RUNTIME_STOP_REPLY_CONTRACT_REASONS = frozenset({REASON_NOT_JSON, REASON_SCHEMA_MISMATCH, REASON_CONTRACT_INVALID})
RUNTIME_STOP_REASONS = frozenset(
    {
        RUNTIME_STOP_STEP_TOOL_REQUIRED,
        RUNTIME_STOP_STEP_STALLED,
        RUNTIME_STOP_ANSWER_EVIDENCE_UNCITED,
        RUNTIME_STOP_ANSWER_EVIDENCE_INVENTED_URL,
        *RUNTIME_STOP_REPLY_CONTRACT_REASONS,
    }
)
# The context-snapshot key of a checked final reply's result: exactly ``check_reply``'s closed dict.
AGENT_REPLY_CONTRACT_KEY = "agent_reply_contract"
# Markers a runtime producer may write. ``failed`` is read from the trace's explicit
# ``raw_output.error`` marker instead; ``cancelled`` has no producer yet.
PRODUCED_RUNTIME_OUTCOMES = frozenset({RUNTIME_OUTCOME_FINISHED, RUNTIME_OUTCOME_STOPPED})
_MAX_SEQUENCE = 10**6

UNKNOWN_VALUE = "unknown"
PROFILE_STATUSES = frozenset(
    {
        EXECUTION_PROFILE_STATUS_ALLOWED,
        EXECUTION_PROFILE_STATUS_DENIED,
        EXECUTION_PROFILE_STATUS_NEEDS_APPROVAL,
        EXECUTION_PROFILE_STATUS_NEEDS_CLARIFICATION,
        EXECUTION_PROFILE_STATUS_NEEDS_CONFIGURATION,
    }
)
GATE_STATUSES = PROFILE_STATUSES | {"missing", GATE_STATUS_NEEDS_CONFIRMATION}
GATE_SOURCES = frozenset(
    {GATE_SOURCE_PROFILE, GATE_SOURCE_MISSING_PROFILE, GATE_SOURCE_UNKNOWN_STATUS, GATE_SOURCE_WORKFLOW_PROPOSAL}
)
_PROPOSAL_CONFIDENCE_VALUES = frozenset(PROPOSAL_CONFIDENCES)
CAPABILITY_CLASS_VALUES = frozenset(CAPABILITY_CLASSES)
_TOOL_SURFACE_SOURCE_VALUES = frozenset(TOOL_SURFACE_SOURCES)

# Identifiers such as profile ids, workflow ids/keys, strategies, provider and model
# names. Whitespace, quotes, "=" and control characters are excluded so free text,
# key=value secrets, and headers cannot pass as a token.
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+\-]{0,159}$")
# Human display names (agent names): letters, digits, and light punctuation only.
_SAFE_DISPLAY = re.compile(r"^[\w][\w .,:()/+&'\-]{0,119}$")


def safe_token(value: Any) -> str | None:
    """Return ``value`` if it is a bounded identifier token, otherwise ``None``."""
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    return candidate if _SAFE_TOKEN.fullmatch(candidate) else None


def safe_display_name(value: Any) -> str | None:
    """Return ``value`` if it is a bounded plain display name, otherwise ``None``."""
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    return candidate if _SAFE_DISPLAY.fullmatch(candidate) else None


def closed_value(value: Any, allowed: frozenset[str]) -> str:
    """Map ``value`` onto a closed enum; anything unrecognized becomes ``unknown``."""
    candidate = value.strip().lower() if isinstance(value, str) else ""
    return candidate if candidate in allowed else UNKNOWN_VALUE


def bounded_sequence(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > _MAX_SEQUENCE:
        return None
    return value


def _turn_section(raw: Any) -> dict[str, Any]:
    turn = raw if isinstance(raw, dict) else {}
    return {
        "user_message_id": safe_token(turn.get("user_message_id")),
        "sequence": bounded_sequence(turn.get("sequence")),
    }


def _explicit_workflow_key(session_metadata: dict[str, Any], workflow_id: str | None) -> str | None:
    # Only a resolution that matched the same workflow as this turn's profile may
    # name the workflow key; a stale or unrelated resolution contributes nothing.
    resolution = session_metadata.get(ROUTING_RESOLUTION_KEY)
    if not isinstance(resolution, dict) or workflow_id is None:
        return None
    if safe_token(resolution.get("workflow_id")) != workflow_id:
        return None
    return safe_token(resolution.get("workflow_key"))


def _capability_section(raw: Any) -> dict[str, Any]:
    # Closed projection of the profile's run capability (services/run_capability).
    capability = raw if isinstance(raw, dict) else {}
    return {
        "class": closed_value(capability.get("class"), CAPABILITY_CLASS_VALUES),
        "source": safe_token(capability.get("source")),
        "enforced": capability.get("enforced") is True,
        "escalated": capability.get("escalated") is True,
        "agent_type_ignored": capability.get("agent_type_ignored") is True,
    }


def workflow_proposal_section(raw: Any) -> dict[str, Any] | None:
    """Closed projection of a proposal record; the model-written ``reason`` never enters it."""
    if not isinstance(raw, dict):
        return None
    confidence = raw.get("confidence")
    change_capable = raw.get("change_capable")
    return {
        "status": closed_value(raw.get("status"), PROPOSAL_STATUSES),
        "reason_code": closed_value(raw.get("reason_code"), PROPOSAL_REASON_CODES),
        "proposal_id": safe_token(raw.get("proposal_id")),
        "workflow_key": safe_token(raw.get("workflow_key")),
        "workflow_title": safe_display_name(raw.get("workflow_title")),
        "confidence": closed_value(confidence, _PROPOSAL_CONFIDENCE_VALUES) if confidence is not None else None,
        "change_capable": change_capable if isinstance(change_capable, bool) else None,
        # A phased workflow's start (``workflow_routing.phased_start``): its card asks to start a run.
        "phased": raw.get("phased") is True,
    }


def _turn_workflow_proposal(session_metadata: dict[str, Any]) -> dict[str, Any] | None:
    resolution = session_metadata.get(ROUTING_RESOLUTION_KEY)
    record = resolution.get(WORKFLOW_PROPOSAL_KEY) if isinstance(resolution, dict) else None
    if not isinstance(record, dict) or record.get("version") != WORKFLOW_PROPOSAL_VERSION:
        return None
    return workflow_proposal_section(record)


def tool_surface_section(source: Any, surface_set: Any) -> dict[str, Any]:
    """Closed projection of the turn's tool surface: its source and governed set key."""
    return {"source": closed_value(source, _TOOL_SURFACE_SOURCE_VALUES), "set": safe_token(surface_set)}


def build_turn_execution_snapshot(
    *,
    execution_profile: Any,
    gate: ExecutionGateDecision,
    session_metadata: dict[str, Any] | None,
    agent_definition: dict[str, Any] | None,
) -> dict[str, Any]:
    """Project the run-time profile and gate decision into the bounded snapshot."""
    profile = execution_profile if isinstance(execution_profile, dict) else {}
    metadata = session_metadata if isinstance(session_metadata, dict) else {}
    agent = agent_definition if isinstance(agent_definition, dict) else {}
    workflow_id = safe_token(profile.get("workflow_id"))
    return {
        "version": TURN_EXECUTION_SNAPSHOT_VERSION,
        "execution_profile": {
            "present": isinstance(execution_profile, dict),
            "version": safe_token(profile.get("version")),
            "status": closed_value(profile.get("status"), PROFILE_STATUSES),
            "profile_id": safe_token(profile.get("profile_id")),
            "decision_source": safe_token(profile.get("decision_source")),
            "execution_strategy": safe_token(profile.get("execution_strategy")),
            "effective_agent_type": safe_token(profile.get("effective_agent_type")),
            "workflow_id": workflow_id,
            "workflow_key": _explicit_workflow_key(metadata, workflow_id),
            "capability": _capability_section(profile.get("capability")),
        },
        "gate": {
            "allowed": gate.allowed is True,
            "status": closed_value(gate.status, GATE_STATUSES),
            "decision_source": closed_value(gate.decision_source, GATE_SOURCES),
        },
        "agent": {
            "id": safe_token(agent.get("id")),
            "name": safe_display_name(agent.get("name")),
            "selection_source": closed_agent_selection_source(metadata.get(AGENT_SELECTION_SOURCE_METADATA_KEY)),
        },
        "turn": _turn_section({"user_message_id": metadata.get("current_turn_user_message_id")}),
        "workflow_proposal": _turn_workflow_proposal(metadata),
        "tool_surface": tool_surface_section(
            metadata.get(TOOL_SURFACE_SOURCE_METADATA_KEY), metadata.get(TOOL_SURFACE_SET_METADATA_KEY)
        ),
    }


def read_turn_execution_snapshot(context_snapshot: Any) -> tuple[str, dict[str, Any] | None]:
    """Read and re-validate the snapshot stored on a trace's context snapshot.

    Returns ``("missing", None)`` for a trace without a snapshot, ``("malformed", None)`` for
    anything that does not match the v1 shape, and ``("ok", snapshot)`` with every
    value re-sanitized otherwise.
    """
    context = context_snapshot if isinstance(context_snapshot, dict) else {}
    raw = context.get(TURN_EXECUTION_SNAPSHOT_KEY)
    if raw is None:
        return "missing", None
    if not isinstance(raw, dict) or raw.get("version") != TURN_EXECUTION_SNAPSHOT_VERSION:
        return "malformed", None
    profile = raw.get("execution_profile")
    gate = raw.get("gate")
    agent = raw.get("agent") if isinstance(raw.get("agent"), dict) else {}
    surface = raw.get("tool_surface") if isinstance(raw.get("tool_surface"), dict) else {}
    if not isinstance(profile, dict) or not isinstance(gate, dict) or not isinstance(gate.get("allowed"), bool):
        return "malformed", None
    return "ok", {
        "version": TURN_EXECUTION_SNAPSHOT_VERSION,
        "execution_profile": {
            "present": profile.get("present") is True,
            "version": safe_token(profile.get("version")),
            "status": closed_value(profile.get("status"), PROFILE_STATUSES),
            "profile_id": safe_token(profile.get("profile_id")),
            "decision_source": safe_token(profile.get("decision_source")),
            "execution_strategy": safe_token(profile.get("execution_strategy")),
            "effective_agent_type": safe_token(profile.get("effective_agent_type")),
            "workflow_id": safe_token(profile.get("workflow_id")),
            "workflow_key": safe_token(profile.get("workflow_key")),
            "capability": _capability_section(profile.get("capability")),
        },
        "gate": {
            "allowed": gate["allowed"],
            "status": closed_value(gate.get("status"), GATE_STATUSES),
            "decision_source": closed_value(gate.get("decision_source"), GATE_SOURCES),
        },
        "agent": {
            "id": safe_token(agent.get("id")),
            "name": safe_display_name(agent.get("name")),
            "selection_source": closed_agent_selection_source(agent.get("selection_source")),
        },
        "turn": _turn_section(raw.get("turn")),
        "workflow_proposal": workflow_proposal_section(raw.get("workflow_proposal")),
        "tool_surface": tool_surface_section(surface.get("source"), surface.get("set")),
        **_runtime_outcome_section(raw),
    }


def _runtime_outcome_section(raw: dict[str, Any]) -> dict[str, Any]:
    outcome = raw.get(RUNTIME_OUTCOME_KEY)
    stop_reason = raw.get(RUNTIME_STOP_REASON_KEY)
    if outcome == RUNTIME_OUTCOME_STOPPED and stop_reason not in RUNTIME_STOP_REASONS:
        outcome = None
    return {
        RUNTIME_OUTCOME_KEY: outcome if outcome in PRODUCED_RUNTIME_OUTCOMES else None,
        RUNTIME_STOP_REASON_KEY: stop_reason if outcome == RUNTIME_OUTCOME_STOPPED else None,
    }



def with_runtime_stop(context_snapshot: dict[str, Any], stop_reason: str) -> dict[str, Any]:
    """A copy of ``context_snapshot`` whose turn snapshot records a stop with a closed reason.

    For a producer handing its final stop answer to persistence. A context without a turn
    snapshot, or a reason outside ``RUNTIME_STOP_REASONS``, is copied unchanged. Persistence
    still re-stamps the bound snapshot (``stamp_turn_execution_snapshot``) and marks the stored
    trace itself, so a caller-supplied snapshot is never the trusted record.
    """
    copied = dict(context_snapshot or {})
    snapshot = copied.get(TURN_EXECUTION_SNAPSHOT_KEY)
    if stop_reason in RUNTIME_STOP_REASONS and isinstance(snapshot, dict):
        copied[TURN_EXECUTION_SNAPSHOT_KEY] = {
            **snapshot,
            RUNTIME_OUTCOME_KEY: RUNTIME_OUTCOME_STOPPED,
            RUNTIME_STOP_REASON_KEY: stop_reason,
        }
    return copied


def read_agent_reply_contract(context_snapshot: Any) -> dict[str, Any] | None:
    """The closed reply-contract check result a trace records, or ``None`` (text, unchecked, stale or foreign).

    Only ``{"kind": "json_object", "status": "satisfied", "reason": None}`` or a ``violated`` status
    with one of the closed validator codes passes, and only where it agrees with the trace's own
    runtime outcome: ``satisfied`` on a ``finished`` trace, ``violated`` on a ``stopped`` trace whose
    stop reason is that code. A record left from an earlier candidate on a trace that ended another
    way therefore reads as no record. Corrupt values (any type) read as no record and
    never raise.
    """
    record = context_snapshot.get(AGENT_REPLY_CONTRACT_KEY) if isinstance(context_snapshot, dict) else None
    if not isinstance(record, dict) or set(record) != {"kind", "status", "reason"}:
        return None
    kind, status, reason = record["kind"], record["status"], record["reason"]
    if not isinstance(kind, str) or not isinstance(status, str) or not (reason is None or isinstance(reason, str)):
        return None
    turn = context_snapshot.get(TURN_EXECUTION_SNAPSHOT_KEY)
    marker = _runtime_outcome_section(turn) if isinstance(turn, dict) else {}
    outcome, stop_reason = marker.get(RUNTIME_OUTCOME_KEY), marker.get(RUNTIME_STOP_REASON_KEY)
    if kind != KIND_JSON_OBJECT:
        return None
    if status == STATUS_SATISFIED and reason is None and outcome == RUNTIME_OUTCOME_FINISHED:
        return {"kind": KIND_JSON_OBJECT, "status": STATUS_SATISFIED, "reason": None}
    if (
        status == STATUS_VIOLATED
        and reason in RUNTIME_STOP_REPLY_CONTRACT_REASONS
        and outcome == RUNTIME_OUTCOME_STOPPED
        and stop_reason == reason
    ):
        return {"kind": KIND_JSON_OBJECT, "status": STATUS_VIOLATED, "reason": reason}
    return None


__all__ = [
    "AGENT_REPLY_CONTRACT_KEY",
    "GATE_SOURCES",
    "GATE_STATUSES",
    "PRODUCED_RUNTIME_OUTCOMES",
    "PROFILE_STATUSES",
    "RUNTIME_OUTCOME_FINISHED",
    "RUNTIME_OUTCOME_KEY",
    "RUNTIME_OUTCOME_STOPPED",
    "RUNTIME_STOP_ANSWER_EVIDENCE_INVENTED_URL",
    "RUNTIME_STOP_ANSWER_EVIDENCE_UNCITED",
    "RUNTIME_STOP_REASONS",
    "RUNTIME_STOP_REASON_KEY",
    "RUNTIME_STOP_REPLY_CONTRACT_REASONS",
    "RUNTIME_STOP_STEP_STALLED",
    "RUNTIME_STOP_STEP_TOOL_REQUIRED",
    "TURN_EXECUTION_SNAPSHOT_KEY",
    "TURN_EXECUTION_SNAPSHOT_VERSION",
    "UNKNOWN_VALUE",
    "bounded_sequence",
    "build_turn_execution_snapshot",
    "closed_value",
    "read_agent_reply_contract",
    "read_turn_execution_snapshot",
    "safe_display_name",
    "safe_token",
    "tool_surface_section",
    "with_runtime_stop",
    "workflow_proposal_section",
]
