"""One agent session across a run's phases when its size class says ``session: "shared"`` (``size_classes``).

Without it, each phase of the bug flow started its own Claude Code session, each
re-reading the ticket, the contract and the code; with the loops that was 53 paid passes for one small bug against
one session with plain Claude Code. A run whose class shares the session resumes, at its next phase, the session its
last phase pass left on the same device, folder and profile, for Claude Code and Codex (``codex exec resume``) alike;
what the new phase may do still comes from its contract at every hook.

The team member who made the mistake fixes it, with their context: every size class shares the
session unless it says ``"per_phase"``, an escalation keeps it, and a class that shares it changes phases (and goes back
after a red gate) inside the running turn. A new session comes only for a reason the workflow's data gives: the next
phase is another role (``agent``) or names another model (``model``), or the device or folder changed.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from ..graph import PhasedNode

#: Why a pass resumes: the run's session of an earlier phase (``session: "shared"``).
RESUME_RUN = "run"
SHARED = "shared"
SAME_TURN = "same_turn"
#: The phase settings whose change starts a session of its own (a role, a model).
NEW_SESSION_KEYS = ("agent", "model")


def shares(run: WorkflowRun | None) -> bool:
    """The run's class shares one session: it says so, or it is a class that says nothing."""
    from ..size_class import class_config, size_of

    value = class_config(run).get("session")
    return value == SHARED or (value is None and bool(size_of(run)))


def phase_change(run: WorkflowRun | None) -> str:
    """How the class changes phases: as it says, else inside the running turn when it shares the session."""
    from ..size_class import class_config

    return str(class_config(run).get("phase_change") or (SAME_TURN if shares(run) else ""))


async def shared_run_session(db: AsyncSession, run: WorkflowRun, node: PhasedNode,
                             target: dict[str, Any]) -> tuple[str, str]:
    """``(session, why)`` the pass resumes when the class shares one; ``("", "")`` otherwise.

    ``why`` is ``RESUME_PHASE`` when that session was this phase's own (a loop back), else :data:`RESUME_RUN`."""
    from ..graph import graph_for_run
    from .phase_sessions import RESUME_PHASE, SESSION_KEY, _session_here

    if not shares(run):
        return "", ""
    last = dict(dict(run.context or {}).get(SESSION_KEY) or {})
    before = (await graph_for_run(db, run)).nodes.get(str(last.get("node_id") or ""))
    if before is not None and any(dict(before.config or {}).get(key) != dict(node.config or {}).get(key)
                                  for key in NEW_SESSION_KEYS):
        return "", ""  # another role or model: a head of its own
    session = await _session_here(db, last, target)
    if not session:
        return "", ""
    return session, RESUME_PHASE if last.get("node_id") == node.id else RESUME_RUN


def next_phase_prompt(run: WorkflowRun, node: PhasedNode) -> str:
    """The prompt of the next phase in the session that did the earlier ones (``run.next_phase``)."""
    from ..phase_contract import phase_definition
    from ..run_texts import run_text
    from .continuation_prompts import _change_plan_note, read_contract
    from .gate_failure import back_prompt

    if back := back_prompt(run, node, read_contract(run)):
        return back  # back in this phase after its gate failed: why, first (not the forward text)
    contract = dict(phase_definition(run, node).get("workflow_contract") or {})
    prompt = run_text("next_phase", phase=node.title, capability_class=contract.get("capability_class") or "read_only",
                      read_contract=read_contract(run))
    # Without the reason here, a refusals rule sent the run back to reproduce in the shared session, but this
    # prompt never said why; the agent kept the test that asserts the bug and the fix phase failed on it again.
    note = _change_plan_note(run, node)
    return f"{prompt} {note[:1].upper()}{note[1:]}." if note else prompt


__all__ = ["NEW_SESSION_KEYS", "RESUME_RUN", "next_phase_prompt", "phase_change", "shared_run_session", "shares"]
