"""One agent session across a run's phases when its size class says ``session: "shared"`` (``size_classes``)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from ..graph import PhasedNode

RESUME_RUN = "run"
SHARED = "shared"
SAME_TURN = "same_turn"
#: The phase settings whose change starts a session of its own (a role, a model).
NEW_SESSION_KEYS = ("agent", "model")


def shares(run: WorkflowRun | None) -> bool:
    from ..size_class import class_config, size_of

    value = class_config(run).get("session")
    return value == SHARED or (value is None and bool(size_of(run)))


def phase_change(run: WorkflowRun | None) -> str:
    from ..size_class import class_config

    return str(class_config(run).get("phase_change") or (SAME_TURN if shares(run) else ""))


async def shared_run_session(db: AsyncSession, run: WorkflowRun, node: PhasedNode,
                             target: dict[str, Any]) -> tuple[str, str]:
    from ..graph import graph_for_run
    from .phase_sessions import RESUME_PHASE, SESSION_KEY, _session_here

    if not shares(run):
        return "", ""
    last = dict(dict(run.context or {}).get(SESSION_KEY) or {})
    before = (await graph_for_run(db, run)).nodes.get(str(last.get("node_id") or ""))
    if before is not None and any(dict(before.config or {}).get(key) != dict(node.config or {}).get(key)
                                  for key in NEW_SESSION_KEYS):
        return "", ""
    session = await _session_here(db, last, target)
    if not session:
        return "", ""
    return session, RESUME_PHASE if last.get("node_id") == node.id else RESUME_RUN


def next_phase_prompt(run: WorkflowRun, node: PhasedNode) -> str:
    from ..phase_contract import phase_definition
    from ..run_texts import run_text
    from .continuation_prompts import _change_plan_note, read_contract
    from .gate_failure import back_prompt

    if back := back_prompt(run, node, read_contract(run)):
        return back  # back in this phase after its gate failed: why, first (not the forward text)
    contract = dict(phase_definition(run, node).get("workflow_contract") or {})
    prompt = run_text("next_phase", phase=node.title, capability_class=contract.get("capability_class") or "read_only",
                      read_contract=read_contract(run))
    # The reason goes along, so an agent sent back in the shared session knows why.
    note = _change_plan_note(run, node)
    return f"{prompt} {note[:1].upper()}{note[1:]}." if note else prompt


__all__ = ["NEW_SESSION_KEYS", "RESUME_RUN", "next_phase_prompt", "phase_change", "shared_run_session", "shares"]
