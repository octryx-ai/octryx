"""The closed vocabulary of a workflow run."""

from __future__ import annotations

from typing import Any

KIND_PHASED = "phased"

STATUS_RUNNING = "running"
STATUS_WAITING = "waiting"
STATUS_PAUSED = "paused"
STATUS_COMPLETED = "completed"
STATUS_STOPPED = "stopped"
STATUS_FAILED = "failed"
ACTIVE_STATUSES = frozenset({STATUS_RUNNING, STATUS_WAITING, STATUS_PAUSED})
TERMINAL_STATUSES = frozenset({STATUS_COMPLETED, STATUS_STOPPED, STATUS_FAILED})

WAITING_REPLY = "waiting_for_reply"
WAITING_CONFIRMATION = "awaiting_confirmation"
WAITING_APPROVAL = "awaiting_approval"
WAITING_WATCH = "watching"
WAITING_SUB_WORKFLOW = "sub_workflow"
WAITING_TOOL_APPROVAL = "awaiting_tool_approval"
WAITING_REVIEW = "awaiting_review"
WAITING_DEVICE = "waiting_for_device"
WAITING_FUNCTIONAL_ACCEPTANCE = "functional_acceptance"
WAITING_AUDIENCE_RECEIPT = "audience_receipt"
WAITING_KINDS = frozenset({WAITING_REPLY, WAITING_CONFIRMATION, WAITING_APPROVAL, WAITING_WATCH,
                           WAITING_SUB_WORKFLOW, WAITING_TOOL_APPROVAL, WAITING_REVIEW, WAITING_DEVICE,
                           WAITING_FUNCTIONAL_ACCEPTANCE, WAITING_AUDIENCE_RECEIPT})

PAUSE_LOOP_LIMIT = "loop_limit"
PAUSE_BUDGET_LIMIT = "budget_limit"
PAUSE_NO_REPLY = "no_reply"
PAUSE_WATCH_TIMEOUT = "watch_timeout"
PAUSE_APPROVAL_TIMEOUT = "approval_timeout"
PAUSE_REVIEW_NO_DECISION = "review_no_decision"
PAUSE_ACTION_FAILED = "action_failed"
# The runtime cannot run the tests (preparation or a test command whose runner could not start), or the working
# folder has foreign uncommitted changes (``workspace``): fixed outside the run, then retried; no loop is consumed.
PAUSE_ENVIRONMENT_NOT_READY = "environment_not_ready"
PAUSE_WORKSPACE_DIRTY = "workspace_dirty"
# A TDD check the platform could not judge (its test evidence could not be keyed, ``evidence_pause``): a
# platform/data problem, re-checked after the fix; no loop is consumed.
PAUSE_EVIDENCE_UNRESOLVED = "evidence_unresolved"
PAUSE_NEEDS_CONFIGURATION = "needs_configuration"
PAUSE_NEEDS_INPUT = "needs_input"
PAUSE_PUBLISH_UNVERIFIED = "publish_unverified"
PAUSE_AUDIENCE_UNPROVEN = "audience_unproven"
PAUSE_ACCEPTANCE_TIMEOUT = "acceptance_timeout"
PAUSE_DOCUMENTATION_MISSING = "documentation_missing"
# Content-policy refusals are permanent; a runtime failure may be retried by the scheduler on the same run.
PAUSE_CONTENT_BLOCKED = "content_blocked"
PAUSE_RUNTIME_FAILED = "runtime_failed"
# Paused only after the platform already re-ran the pipeline once.
PAUSE_PIPELINE_NOT_FOR_HEAD = "pipeline_not_for_head"
PAUSE_PHASE_SCOPE_EXCEEDED = "phase_scope_exceeded"
PAUSE_DEVICE_UNREACHABLE = "device_unreachable"
# A phase on the server runners needs a person's seat, which only exists on that person's device.
PAUSE_SEAT_REQUIRED = "seat_required"
# ``runtime_failed`` split by what failed: ``pause_causes.json`` maps a code to its class, an unmapped code stays.
PAUSE_PHASE_NOT_FINISHED = "phase_not_finished"
PAUSE_PHASE_STALLED = "phase_stalled"
PAUSE_AGENT_LOOP = "agent_loop"
PAUSE_SERVICE_RESTARTED = "service_restarted"
PAUSE_TURN_FAILED = "turn_failed"
PAUSE_SEAT_LIMIT = "seat_limit"
PAUSE_SCENARIOS_FAILED = "scenarios_failed"
# A loop back from a failed check (gate, pipeline, CI) ran out of attempts: the run never offers red work as done.
PAUSE_CHECKS_FAILED = "checks_failed"
ROUND_LIMIT_REASONS = frozenset({PAUSE_LOOP_LIMIT, PAUSE_CHECKS_FAILED})
# A write to an expensive path or outside the approved plan: a person approves the plan or the path.
PAUSE_NEEDS_APPROVAL = "needs_approval"
RUNTIME_FAILURE_REASONS = frozenset({PAUSE_RUNTIME_FAILED, PAUSE_PHASE_NOT_FINISHED, PAUSE_PHASE_STALLED,
                                     PAUSE_AGENT_LOOP, PAUSE_SERVICE_RESTARTED, PAUSE_TURN_FAILED, PAUSE_SEAT_LIMIT,
                                     PAUSE_SCENARIOS_FAILED})
ACTION_TURN_PAUSE_REASONS = frozenset({PAUSE_CONTENT_BLOCKED}) | RUNTIME_FAILURE_REASONS
# The only pauses an exception (subject ``exception``) may close, after an authorised, read-back follow-up.
EXCEPTION_PAUSE_REASONS = frozenset({PAUSE_AUDIENCE_UNPROVEN, PAUSE_DOCUMENTATION_MISSING, PAUSE_ACCEPTANCE_TIMEOUT})
PAUSE_REASONS = frozenset({PAUSE_LOOP_LIMIT, PAUSE_CHECKS_FAILED, PAUSE_NEEDS_APPROVAL, PAUSE_BUDGET_LIMIT,
                           PAUSE_NO_REPLY, PAUSE_WATCH_TIMEOUT,
                           PAUSE_APPROVAL_TIMEOUT, PAUSE_REVIEW_NO_DECISION, PAUSE_ACTION_FAILED,
                           PAUSE_ENVIRONMENT_NOT_READY, PAUSE_WORKSPACE_DIRTY, PAUSE_EVIDENCE_UNRESOLVED,
                           PAUSE_NEEDS_CONFIGURATION, PAUSE_PUBLISH_UNVERIFIED, PAUSE_AUDIENCE_UNPROVEN,
                           PAUSE_ACCEPTANCE_TIMEOUT, PAUSE_DOCUMENTATION_MISSING, PAUSE_CONTENT_BLOCKED,
                           PAUSE_PIPELINE_NOT_FOR_HEAD, PAUSE_PHASE_SCOPE_EXCEEDED,
                           PAUSE_NEEDS_INPUT, PAUSE_DEVICE_UNREACHABLE, PAUSE_SEAT_REQUIRED}) | RUNTIME_FAILURE_REASONS

OUTCOME_DELIVERED = "delivered"
OUTCOME_DONE = "done"
OUTCOME_BLOCKED = "blocked"
OUTCOME_STOPPED = "stopped"
# Only new B versions route to it; there is no cross-owner ``handed_over`` outcome.
OUTCOME_DONE_WITH_EXCEPTION = "done_with_exception"
OUTCOMES = frozenset({OUTCOME_DELIVERED, OUTCOME_DONE, OUTCOME_BLOCKED, OUTCOME_STOPPED, OUTCOME_DONE_WITH_EXCEPTION})

ROLE_MAIN = "main"
RUNTIME_CHAT = "chat"

EVENT_STARTED = "run_started"
#: Kept in ``run_started.detail`` so an evaluation needs no /metrics.
CONTEXT_TRIGGER = "trigger"


def started_by(run: Any) -> dict[str, str]:
    trigger = str(dict(getattr(run, "context", None) or {}).get(CONTEXT_TRIGGER) or "")
    return {"trigger": trigger[:40]} if trigger else {}
EVENT_SESSION_BOUND = "session_bound"
EVENT_NODE_ENTERED = "node_entered"
EVENT_PHASE_TURN = "phase_turn"
EVENT_DUPLICATE_RESULT_IGNORED = "duplicate_result_ignored"
EVENT_GATE = "gate_evaluated"
EVENT_LOOP = "loop_iteration"
EVENT_WAITING = "waiting"
EVENT_PAUSED = "paused"
EVENT_RESUMED = "resumed"
EVENT_DECISION = "decision"
EVENT_ACTION = "platform_action"
EVENT_COMPLETED = "completed"
EVENT_STOPPED = "stopped"
EVENT_FAILED = "failed"

RUN_SELECTION_SOURCE = "workflow_run"
RUN_RESOLUTION_KEY = "workflow_run"
STATUS_HELD = "held"
