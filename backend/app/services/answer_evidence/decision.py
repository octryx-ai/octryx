"""The answer evidence decision for one final reply, shared by every runtime path.

The native loop (``agent/loops/response/_loop_answer_evidence``) applies the decision at the boundary where the
final answer is accepted. Every chat turn runs the native loop.

- ``skip``: not a user-facing answering turn (a sub-agent, or a ``change`` / ``admin`` mode of work);
  nothing is recorded.
- ``accept``: delivered; the record says ``passed`` or ``unsourced``.
- ``remind``: an answer that links none of the turn's sources, or links one from memory, is suppressed once and the
  model gets the one reminder; the record says ``reminded``.
- ``mark``: delivered as ``content`` with its shortfalls marked (``check.mark_answer``); the record says ``marked``.
- ``refuse``: the final refusal. The decision never returns it (a whole answer is never withheld;
  withholding cost too many right answers); the runtimes keep the branch so a refusal
  stays a recorded runtime stop wherever one is decided.
- A turn that executed a write is accepted as it is: its answer confirms the action (eval T21).

A run phase turn is guarded like any chat turn: uncited claims are marked. Its phase result does not depend on the
visible reply — a turn this guard ends still records its checks (``_loop_workflow_checks``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .check import answer_evidence_record, check_answer_evidence, evidence_reminder, mark_answer
from .evidence import collect_turn_evidence
from .record import GUARD_MARKED, GUARD_PASSED, GUARD_REMINDED, GUARD_UNSOURCED

MAX_EVIDENCE_REMINDERS = 1
# The turn's mode of work is the explicit scope: a diagnosis or plan turn answers from evidence and
# must cite it. A change or admin turn's final answer reports its own actions; their evidence is the
# turn's tool calls, diff and delivery gates, not an external source to link.
ENFORCED_CAPABILITY_TYPES = frozenset({"diagnosis", "plan"})

ACTION_SKIP = "skip"
ACTION_ACCEPT = "accept"
ACTION_REMIND = "remind"
ACTION_REFUSE = "refuse"
ACTION_MARK = "mark"


@dataclass(frozen=True, slots=True)
class EvidenceDecision:
    action: str
    record: dict[str, Any] | None = None
    reminder: str = ""
    refusal: str = ""
    refusal_reason: str = ""
    content: str = ""


def decide_answer_evidence(
    *,
    content: str,
    turn_tool_history: list[dict[str, Any]] | None,
    user_message: str,
    reminders: int,
    capability_type: str,
    sub_agent_depth: int,
) -> EvidenceDecision:
    if sub_agent_depth or capability_type not in ENFORCED_CAPABILITY_TYPES:
        return EvidenceDecision(ACTION_SKIP)
    evidence = collect_turn_evidence(turn_tool_history)
    check = check_answer_evidence(content, evidence, user_message=user_message)
    if check.satisfied or check.reports_write:
        state = GUARD_PASSED if check.evidence_bearing else GUARD_UNSOURCED
        return EvidenceDecision(ACTION_ACCEPT, answer_evidence_record(state, check, reminder_count=reminders))
    if (check.invented_urls or not check.links_a_source) and reminders < MAX_EVIDENCE_REMINDERS:
        # Nothing linked, or a link from memory: one chance to cite; the draft comes back, never lost.
        record = answer_evidence_record(GUARD_REMINDED, check, reminder_count=reminders + 1)
        return EvidenceDecision(ACTION_REMIND, record, reminder=evidence_reminder(check))
    return EvidenceDecision(
        ACTION_MARK,
        answer_evidence_record(GUARD_MARKED, check, reminder_count=reminders),
        content=mark_answer(content, check, evidence),
    )


__all__ = [
    "ACTION_ACCEPT",
    "ACTION_MARK",
    "ACTION_REFUSE",
    "ACTION_REMIND",
    "ACTION_SKIP",
    "ENFORCED_CAPABILITY_TYPES",
    "MAX_EVIDENCE_REMINDERS",
    "EvidenceDecision",
    "decide_answer_evidence",
]
