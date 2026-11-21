"""Readable run events for the companion's watch view: a sentence per event and whether it is technical.

``technical`` events (sessions bound, preparation reports, continuations, loop counters, WIP pushes, …) are
bookkeeping a watcher can hide; the rest say what happened in words, never with template placeholders.
"""

from __future__ import annotations

from typing import Any

from ...models import WorkflowRunEvent

TECHNICAL = frozenset({
    "session_bound", "workspace_preparation_reported", "device_continuation_started", "server_continuation_started",
    "server_continuation_refused", "device_continuation_refused", "phase_output_recorded", "loop_iteration",
    "gate_evaluated", "wip_pushed", "wip_failed", "branch_adopted", "branch_fast_forwarded", "reminder",
    "failure_path", "runtime_target_changed", "action_turn_redriven",
})
_ACTIONS = {
    "jira.create_issue": "Jira ticket", "jira.comment": "Jira comment", "jira.transition": "Jira status",
    "scm.create_branch": "Branch", "scm.push": "Push", "scm.open_pr": "Pull request",
    "workspace.prepare": "Working folder prepared", "work.draft_change_plan": "Change plan drafted",
    "work.create_stories": "Stories created",
    "documentation.tree_unchanged": "Documentation checked",
    "documentation.publish_spec": "Spec page", "documentation.publish_feature": "Feature page",
}
_RESULTS = {"succeeded": "done", "failed": "failed", "skipped": "skipped", "pending": "waiting for approval"}
_DECISIONS = {"confirmed": "confirmed", "changed": "asked for a change", "stopped": "stopped",
              "approved": "approved", "rejected": "rejected", "continue": "continued", "abort": "aborted"}
_WAITING = {"awaiting_confirmation": "Waiting for your confirmation", "awaiting_approval": "Waiting for an approval",
            "awaiting_tool_approval": "Waiting for a tool approval", "waiting_for_reply": "Waiting for your answer",
            "watching": "Waiting for CI / the pull request", "waiting_for_device": "Waiting for the device",
            "awaiting_review": "Waiting for the review", "sub_workflow": "Waiting for a sub-workflow"}


def _words(value: Any) -> str:
    return str(value or "").replace("_", " ").replace(".", " ").strip()


def _size_text(kind: str, detail: dict[str, Any]) -> str:
    """The team sees why a run takes a lighter path and what it leaves out."""
    skips = ", ".join(str(node) for node in detail.get("skips") or [])
    tail = f"; skips {skips}" if skips else ""
    if kind == "size_escalated":
        return f"Class raised from {detail.get('from')} to {detail.get('to')} ({detail.get('cause')}){tail}"
    if not detail.get("class"):
        return f"No size class: {detail.get('matched')}"
    rule = f"by rule {detail['rule']}" if detail.get("rule") else "by default"
    return f"Class {detail['class']} {rule}: {detail.get('matched')}{tail}"


def event_text(event: WorkflowRunEvent, titles: dict[str, str]) -> tuple[str, bool]:
    """``(text, technical)`` for one run event."""
    detail = dict(event.detail or {})
    node = titles.get(event.node_id or "", _words(event.node_id))
    kind = event.kind
    if kind == "run_started":
        text = "Run started"
    elif kind == "node_entered":
        text = f"Started: {node}"
    elif kind == "phase_turn":
        text = f"{node}: {'passed' if detail.get('state') == 'passed' else 'not passed yet'}"
    elif kind == "paused":
        from ..workflow_runs.limits import pause_message

        text = f"Paused: {pause_message(None, str(detail.get('reason') or ''), detail)[:300]}"
    elif kind == "waiting":
        text = _WAITING.get(str(detail.get("waiting_kind") or ""), "Waiting")
        if detail.get("action"):
            text = f"Waiting: {_ACTIONS.get(str(detail['action']), _words(detail['action']))}"
    elif kind == "stopped":
        text = f"Stopped: {str(detail.get('reason') or '')[:300]}".rstrip(": ")
    elif kind == "decision":
        subject = node or _words(detail.get("subject")).capitalize() or "Next step"
        text = f"{subject}: {_DECISIONS.get(str(detail.get('action') or ''), _words(detail.get('action')))}"
    elif kind == "platform_action":
        action = str(detail.get("action") or "")
        result = _RESULTS.get(str(detail.get("result")), _words(detail.get("result")))
        text = f"{_ACTIONS.get(action, _words(action).capitalize())}: {result}"
    elif kind == "subagent_reported":
        text = f"{node}: a helper agent {'finished' if detail.get('state') == 'passed' else 'reported a problem'}"
    elif kind.startswith("handover_"):
        text = {"handover_requested": "Handover requested", "handover_accepted": "Handed over",
                "handover_declined": "Handover declined"}.get(kind, _words(kind))
        if detail.get("reason"):
            text += f": {str(detail['reason'])[:200]}"
    elif kind in ("routed_to", "routed_from"):
        # Routing by type: which workflow took over the triaged item, or which triage started this run.
        workflow = _words(detail.get("workflow_key")) or "a workflow"
        text = (f"Routed to {workflow}" if kind == "routed_to" else f"Started by the triage ({workflow})") + (
            f" as {detail['type']}" if detail.get("type") else "")
    elif kind in ("runtime_profile_governed", "seat_returned", "seat_fallback_model"):
        # The seat → company switch, the company model it runs on and the return after the reset:
        # visible on the phone, never technical.
        text = str(detail.get("message") or _words(kind).capitalize())[:300]
    elif kind in ("size_classified", "size_escalated"):
        text = _size_text(kind, detail)
    elif kind == "routing_no_route":
        text = str(detail.get("message") or "No route for this type")[:300]
    elif kind == "routing_failed":
        text = f"Follow-up not started: {str(detail.get('message') or _words(detail.get('code')))[:300]}"
    else:
        text = _words(kind).capitalize() + (f" ({node})" if node else "")
    return text, kind in TECHNICAL


__all__ = ["TECHNICAL", "event_text"]
