"""The product owner's answers a confirmation carries, kept for the next phase and noted in the run's thread."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun
from ...time_utils import utc_now
from .graph import SUBJECT_INTERVIEW, SUBJECT_READINESS
from .hitl_actions import MAX_ANSWER_NOTE_CHARS

# The subjects whose confirmation accepts the agent's proposed answers (the spec interview, the readiness check).
_ACCEPTED_PROPOSAL_SUBJECTS = frozenset({SUBJECT_INTERVIEW, SUBJECT_READINESS})
ACCEPTED_PREFIX = ("The product owner accepted every proposed answer below as written; each is a decision the "
                   "specification carries out and lists under Decisions:\n\n")


def accepted_proposals_answer(proposals: str) -> str:
    """The product owner's answer when they accept the agent's proposals as they stand; ``""`` without proposals."""
    text = proposals.strip()
    return f"{ACCEPTED_PREFIX}{text}" if text else ""


def _record_po_answer(run: WorkflowRun, text: str, *, user_id: str, replaces: Any = None) -> None:
    """The product owner's answer to the review: the next pass of the agent's phase reads every answer so far.
    ``replaces``: the numbers (1-based, oldest first) of earlier answers this one replaces; they stay on the run for
    the audit but no longer reach the agent or the reviewer (otherwise a weak reviewer keeps "PO answer
    2: drift" high after answer 3 replaced it)."""
    review = dict(dict(run.context or {}).get("review") or {})
    answers = [dict(item) if isinstance(item, dict) else item for item in dict(run.context or {}).get("po_answers")
               or []]
    for number in replaces if isinstance(replaces, list) else []:
        if isinstance(number, int) and 1 <= number <= len(answers) and isinstance(answers[number - 1], dict):
            answers[number - 1]["replaced_by"] = len(answers) + 1
    answers.append({"text": text, "by": user_id, "at": utc_now().isoformat(),
                    "review_attempt": review.get("attempt")})
    # Every answer stays: the epic answer must reach the last pass. A person's answer starts a new round of the
    # automatic revisions (otherwise after the product owner's answer the next changes
    # verdict comes straight back to them, because the automatic revisions are already used up).
    run.context = {**dict(run.context or {}), "po_answers": answers, "auto_revisions": {}}


async def _note_po_answer(db: AsyncSession, run: WorkflowRun, text: str, user: Any, subject: str) -> None:
    """The answer also lands on the platform Work item: whoever opens the ticket sees every decision
    the product owner made on it, after the run is gone. A Jira item keeps its tracker as the place for that."""
    from ...models.runtime.secure_work import WorkItem
    from ..secure_work.platform_items import add_work_item_note, is_platform_work_item

    item = await db.get(WorkItem, run.work_item_id) if run.work_item_id else None
    if item is None or not is_platform_work_item(item):
        return
    where = {"readiness": "open questions before building", "interview": "spec questions",
             "decisions": "review"}.get(subject, subject)
    await add_work_item_note(db, item=item, current_user=user, limit=MAX_ANSWER_NOTE_CHARS,
                             note=f"Product owner answer ({where}, workflow run {run.id}):\n{text}")
