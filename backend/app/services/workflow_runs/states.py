"""The closed vocabulary of a workflow run.

A run is ``running`` while a phase may take turns or the engine advances, ``waiting`` while a
human-in-the-loop node waits (``waiting_kind``), ``paused`` when a limit stopped it (``pause_reason``),
and ends ``completed`` (with an ``outcome``), ``stopped`` (the user aborted) or ``failed`` (the engine could
not continue, with ``last_error``). Nothing ends or continues silently: every transition is an event.
"""

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

# What a waiting run waits for (the four human-in-the-loop kinds, plus a sub-workflow).
WAITING_REPLY = "waiting_for_reply"
WAITING_CONFIRMATION = "awaiting_confirmation"
WAITING_APPROVAL = "awaiting_approval"
WAITING_WATCH = "watching"
WAITING_SUB_WORKFLOW = "sub_workflow"
# A platform action's tool waits for its tool approval in the run's chat session.
WAITING_TOOL_APPROVAL = "awaiting_tool_approval"
# The independent reviewer reviews the change.
WAITING_REVIEW = "awaiting_review"
# The run's device cannot take its turn now (offline, paused, busy): it goes on when it can (``runtime_target``).
WAITING_DEVICE = "waiting_for_device"
# "B publish & prove": the published page waits for the deferred functional acceptance (a), and the
# publication waits for the audience principal's own retrieval receipt (``documentation/acceptance``, ``s1_graph``).
WAITING_FUNCTIONAL_ACCEPTANCE = "functional_acceptance"
WAITING_AUDIENCE_RECEIPT = "audience_receipt"
WAITING_KINDS = frozenset({WAITING_REPLY, WAITING_CONFIRMATION, WAITING_APPROVAL, WAITING_WATCH,
                           WAITING_SUB_WORKFLOW, WAITING_TOOL_APPROVAL, WAITING_REVIEW, WAITING_DEVICE,
                           WAITING_FUNCTIONAL_ACCEPTANCE, WAITING_AUDIENCE_RECEIPT})

# Why a paused run paused.
PAUSE_LOOP_LIMIT = "loop_limit"
PAUSE_BUDGET_LIMIT = "budget_limit"
PAUSE_NO_REPLY = "no_reply"
PAUSE_WATCH_TIMEOUT = "watch_timeout"
PAUSE_APPROVAL_TIMEOUT = "approval_timeout"
PAUSE_REVIEW_NO_DECISION = "review_no_decision"
# A recoverable platform-action failure routed to a pause node (``action_failures``).
PAUSE_ACTION_FAILED = "action_failed"
# The runtime cannot run the tests (preparation or a test command whose runner could not start), or the working
# folder has foreign uncommitted changes (``workspace``): fixed outside the run, then retried; no loop is consumed.
PAUSE_ENVIRONMENT_NOT_READY = "environment_not_ready"
PAUSE_WORKSPACE_DIRTY = "workspace_dirty"
# A TDD check the platform could not judge (its test evidence could not be keyed, ``evidence_pause``): a
# platform/data problem, re-checked after the fix; no loop is consumed.
PAUSE_EVIDENCE_UNRESOLVED = "evidence_unresolved"
# A configuration the publication needs is missing (fails closed before card (b)); a potentially sent
# publication could not be proven (reconcile first on retry); the audience receipt did not prove the page; the
# deferred functional acceptance did not arrive in time; no feature documentation was recorded.
PAUSE_NEEDS_CONFIGURATION = "needs_configuration"
# A person names what the run cannot decide itself (e.g. which app of a repository with several).
PAUSE_NEEDS_INPUT = "needs_input"
PAUSE_PUBLISH_UNVERIFIED = "publish_unverified"
PAUSE_AUDIENCE_UNPROVEN = "audience_unproven"
PAUSE_ACCEPTANCE_TIMEOUT = "acceptance_timeout"
PAUSE_DOCUMENTATION_MISSING = "documentation_missing"
# The agent turn of an Action-started run failed. A content policy refused the
# content the turn would send (permanent: never retried), or the turn failed in the runtime (the scheduler may retry
# it, the retry continues this run). The run pauses for its requester: continue runs the phase again, abort ends it.
PAUSE_CONTENT_BLOCKED = "content_blocked"
PAUSE_RUNTIME_FAILED = "runtime_failed"
# A push or pull request whose tree is not the one the run's CI pipeline ran green on (no pipeline yet, red, or
# another tree; ``pipeline_head``), after the platform already re-ran the pipeline once: continue re-runs it.
PAUSE_PIPELINE_NOT_FOR_HEAD = "pipeline_not_for_head"
# A phase's refusals rule reacted (``refusals``): the same request refused N times.
PAUSE_PHASE_SCOPE_EXCEEDED = "phase_scope_exceeded"
# A step that waits for its device heard nothing (device offline, or its job silent): ``device_silence``.
PAUSE_DEVICE_UNREACHABLE = "device_unreachable"
# ``runtime_failed`` split by what failed (it carried ten meanings, told apart
# only by ``detail.code``). ``pause_causes.json`` (``runtime_failed_split``) maps a code to its class; a pause keeps
# ``detail.code``, and an unmapped code stays ``runtime_failed``.
PAUSE_PHASE_NOT_FINISHED = "phase_not_finished"
PAUSE_PHASE_STALLED = "phase_stalled"
PAUSE_AGENT_LOOP = "agent_loop"
PAUSE_SERVICE_RESTARTED = "service_restarted"
PAUSE_TURN_FAILED = "turn_failed"
PAUSE_SEAT_LIMIT = "seat_limit"
PAUSE_SCENARIOS_FAILED = "scenarios_failed"
RUNTIME_FAILURE_REASONS = frozenset({PAUSE_RUNTIME_FAILED, PAUSE_PHASE_NOT_FINISHED, PAUSE_PHASE_STALLED,
                                     PAUSE_AGENT_LOOP, PAUSE_SERVICE_RESTARTED, PAUSE_TURN_FAILED, PAUSE_SEAT_LIMIT,
                                     PAUSE_SCENARIOS_FAILED})
ACTION_TURN_PAUSE_REASONS = frozenset({PAUSE_CONTENT_BLOCKED}) | RUNTIME_FAILURE_REASONS
# The only pauses an exception (subject ``exception``) may close, after an authorised, read-back follow-up.
EXCEPTION_PAUSE_REASONS = frozenset({PAUSE_AUDIENCE_UNPROVEN, PAUSE_DOCUMENTATION_MISSING, PAUSE_ACCEPTANCE_TIMEOUT})
PAUSE_REASONS = frozenset({PAUSE_LOOP_LIMIT, PAUSE_BUDGET_LIMIT, PAUSE_NO_REPLY, PAUSE_WATCH_TIMEOUT,
                           PAUSE_APPROVAL_TIMEOUT, PAUSE_REVIEW_NO_DECISION, PAUSE_ACTION_FAILED,
                           PAUSE_ENVIRONMENT_NOT_READY, PAUSE_WORKSPACE_DIRTY, PAUSE_EVIDENCE_UNRESOLVED,
                           PAUSE_NEEDS_CONFIGURATION, PAUSE_PUBLISH_UNVERIFIED, PAUSE_AUDIENCE_UNPROVEN,
                           PAUSE_ACCEPTANCE_TIMEOUT, PAUSE_DOCUMENTATION_MISSING, PAUSE_CONTENT_BLOCKED,
                           PAUSE_PIPELINE_NOT_FOR_HEAD, PAUSE_PHASE_SCOPE_EXCEEDED,
                           PAUSE_NEEDS_INPUT, PAUSE_DEVICE_UNREACHABLE}) | RUNTIME_FAILURE_REASONS

OUTCOME_DELIVERED = "delivered"
OUTCOME_DONE = "done"
OUTCOME_BLOCKED = "blocked"
OUTCOME_STOPPED = "stopped"
# Ended through a declared exception (missing proof, authorised and read-back follow-up); only new B
# versions route to it. There is no ``handed_over`` outcome (no cross-owner handoff).
OUTCOME_DONE_WITH_EXCEPTION = "done_with_exception"
OUTCOMES = frozenset({OUTCOME_DELIVERED, OUTCOME_DONE, OUTCOME_BLOCKED, OUTCOME_STOPPED, OUTCOME_DONE_WITH_EXCEPTION})

# The bound session's role and runtime.
ROLE_MAIN = "main"
RUNTIME_CHAT = "chat"

# Events (append-only history).
EVENT_STARTED = "run_started"
#: What started a run (``run.context["trigger"]``, set by an automatic start such as the PR review bot's
#: ``octryx_pr`` | ``sync`` | ``webhook``): kept in ``run_started.detail`` so an evaluation needs no /metrics.
CONTEXT_TRIGGER = "trigger"


def started_by(run: Any) -> dict[str, str]:
    """``{"trigger": …}`` for the ``run_started`` detail, ``{}`` for a run without one."""
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

# The routing resolution of a turn a run governs.
RUN_SELECTION_SOURCE = "workflow_run"
RUN_RESOLUTION_KEY = "workflow_run"
STATUS_HELD = "held"
