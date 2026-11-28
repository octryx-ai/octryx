"""Fail open on uncertainty."""

from __future__ import annotations

from collections.abc import Iterable
from hashlib import sha256
from typing import Any

from ...models import WorkflowRun

EVENT = "check_uncertain"
CONTEXT_KEY = "check_uncertain_seen"
PASS_KEY = "check_uncertain_pass"
MAX_SEEN = 200


def note(db: Any, run: WorkflowRun, *, control: str, reason: str, node_id: str | None = None) -> bool:
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
    for result in results:
        if getattr(result, "uncertain", ""):
            note(db, run, control=f"{source}:{result.type}", reason=result.uncertain)


def controls_in_pass(run: WorkflowRun) -> list[str]:
    passed = dict(dict(run.context or {}).get(PASS_KEY) or {})
    current = (run.current_node_id, dict(run.node_state or {}).get("entry"))
    return list(passed.get("controls") or []) if (passed.get("node_id"), passed.get("entry")) == current else []


__all__ = ["EVENT", "PASS_KEY", "controls_in_pass", "note", "note_results"]
