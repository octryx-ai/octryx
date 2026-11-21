"""The device continuation's marker in the run context: which pass it continues and in which state."""

from __future__ import annotations

from typing import Any

from ....models import Session, WorkflowRun
from ..states import STATUS_RUNNING

CONTEXT_KEY = "device_continuation"
STATE_PENDING = "pending"
STATE_STARTED = "started"
STATE_REFUSED = "refused"
PROVENANCE = "workflow_continuation"


def _marker(run: WorkflowRun) -> dict[str, Any]:
    return dict(dict(run.context or {}).get(CONTEXT_KEY) or {})


def _set_marker(run: WorkflowRun, marker: dict[str, Any] | None) -> None:
    context = dict(run.context or {})
    if marker is None:
        context.pop(CONTEXT_KEY, None)
    else:
        context[CONTEXT_KEY] = marker
    run.context = context


def _device_target(thread: Session | None) -> dict[str, Any] | None:
    target = dict(thread.metadata_ or {}).get("execution_target") if thread is not None else None
    if not isinstance(target, dict) or target.get("kind") != "device":
        return None
    # A platform-driven continuation never inherits the person's per-turn mode (bypass): it runs in
    # the device's default mode, where Claude Code asks and the approvals reach the person.
    return {**target, "permission_mode": ""}


def _parse_time(value: str):
    from datetime import datetime

    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


#: The marker of a runtime step's turn: the phase its agent goes on with once the step succeeded.
THEN_KEY = "then_phase"


#: The marker of a pass a person restarted in a new chat: its turn starts a fresh session (no resume).
FRESH_KEY = "fresh"


def continuation_state(run: WorkflowRun) -> dict[str, Any] | None:
    """The current pass's continuation for the run contract (a refused one names why; nothing retries it)."""
    marker = _marker(run)
    if not marker or (marker.get("node_id"), marker.get("entry")) != (
            run.current_node_id, dict(run.node_state or {}).get("entry")):
        return None
    return {"state": marker.get("state"), **({"reason": marker["reason"]} if marker.get("reason") else {})}


def _current_pass_started(run: WorkflowRun, marker: dict[str, Any]) -> bool:
    return (run.status == STATUS_RUNNING and marker.get("state") == STATE_STARTED
            and (marker.get("node_id"), marker.get("entry")) == (run.current_node_id,
                                                                 dict(run.node_state or {}).get("entry")))


BUSY_SINCE_KEY = "device_busy_since"
