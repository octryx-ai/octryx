"""Fail open on uncertainty.

A control that cannot decide with certainty (an unreadable output, a check with no evidence it could judge, a piped
test run whose summary was cut) lets the agent go on and leaves a note instead of a block: one ``check_uncertain``
event per control, reason and pass (``control``, ``reason``, ``node_id``, ``entry``). A control blocks only on a clear
finding. Security controls (secrets, credentials, destructive commands, delivery) stay strict and never come here.

The nightly e2e counts these events per run; together with the pause causes (``pause_causes``) they show
where the platform was unsure.
"""

from __future__ import annotations

from collections.abc import Iterable
from hashlib import sha256
from typing import Any

from ...models import WorkflowRun

EVENT = "check_uncertain"
CONTEXT_KEY = "check_uncertain_seen"
PASS_KEY = "check_uncertain_pass"  # the controls unsure in the current pass (node and entry), for the pause cause
MAX_SEEN = 200


def note(db: Any, run: WorkflowRun, *, control: str, reason: str, node_id: str | None = None) -> bool:
    """Record that ``control`` let the run go on although it could not decide (once per pass); ``True`` if new."""
    from .records import record_event

    node = node_id if node_id is not None else run.current_node_id
    entry = dict(run.node_state or {}).get("entry")
    key = sha256(f"{node}|{entry}|{control}|{reason}".encode()).hexdigest()[:16]
    seen = list(dict(run.context or {}).get(CONTEXT_KEY) or [])
    if key in seen:
        return False
    passed = dict(dict(run.context or {}).get(PASS_KEY) or {})
    if (passed.get("node_id"), passed.get("entry")) != (node, entry):
        passed = {"node_id": node, "entry": entry, "controls": []}
    controls = [*passed["controls"], control[:120]][-20:]
    run.context = {**dict(run.context or {}), CONTEXT_KEY: [*seen, key][-MAX_SEEN:],
                   PASS_KEY: {**passed, "controls": list(dict.fromkeys(controls))}}
    record_event(db, run, EVENT, node_id=node, detail={"control": control[:120], "reason": reason[:600],
                                                       "entry": entry})
    return True


def note_results(db: Any, run: WorkflowRun, results: Iterable[Any], *, source: str) -> None:
    """One note per check result that passed uncertain (``CheckResult.uncertain``)."""
    for result in results:
        if getattr(result, "uncertain", ""):
            note(db, run, control=f"{source}:{result.type}", reason=result.uncertain)


def controls_in_pass(run: WorkflowRun) -> list[str]:
    """The controls that passed unsure in the run's current pass (``[]`` for another pass)."""
    passed = dict(dict(run.context or {}).get(PASS_KEY) or {})
    current = (run.current_node_id, dict(run.node_state or {}).get("entry"))
    return list(passed.get("controls") or []) if (passed.get("node_id"), passed.get("entry")) == current else []


__all__ = ["EVENT", "PASS_KEY", "controls_in_pass", "note", "note_results"]
