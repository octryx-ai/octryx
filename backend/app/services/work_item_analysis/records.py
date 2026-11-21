"""Where a finished analysis is recorded: the Work Item note and the board ``info`` message.

The note joins the item's ``platform_notes`` list (the list ``work_item_note`` and ``work_item_context`` use)
with ``kind: analysis``, ``author_type: agent`` and the analysis id; it changes nothing else on the item.
The board message is an ``info`` from the analysis run's agent identity, linked to the item.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AgentBoardMessage, User, WorkItem, WorkItemAnalysis
from ...time_utils import utc_now
from ..agent_board.messages import AUTHOR_AGENT, Author, post_message
from ..agent_gateway.presence import session_key_hash

NOTE_KIND = "analysis"
NOTE_AUTHOR_TYPE = "agent"
MAX_NOTES = 100  # the platform_notes bound of ``secure_work.platform_items``
MAX_BOARD_SUMMARY_CHARS = 400


def analysis_agent_hash(analysis: WorkItemAnalysis) -> str:
    return session_key_hash(f"work-item-analysis:{analysis.id}")


async def append_analysis_note(db: AsyncSession, *, item: WorkItem, analysis: WorkItemAnalysis, user: User,
                               text: str, summary: str) -> str:
    """Append the rendered analysis as an agent note; returns its timestamp.

    ``summary`` is the analysis summary alone: the ServiceNow work note sends only that field."""
    at = utc_now().isoformat()
    fields = dict(item.source_fields_json or {})
    notes = [entry for entry in fields.get("platform_notes") or [] if isinstance(entry, dict)]
    notes.append({"at": at, "author": user.username, "note": text, "kind": NOTE_KIND,
                  "author_type": NOTE_AUTHOR_TYPE, "analysis_id": analysis.id, "summary": summary})
    fields["platform_notes"] = notes[-MAX_NOTES:]
    item.source_fields_json = fields
    await db.flush()
    return at


async def post_analysis_info(db: AsyncSession, *, item: WorkItem, analysis: WorkItemAnalysis, user: User,
                             summary: str) -> AgentBoardMessage:
    short = summary if len(summary) <= MAX_BOARD_SUMMARY_CHARS else summary[: MAX_BOARD_SUMMARY_CHARS - 3] + "..."
    body = (f"Analysis of {item.source_key} is ready (analysis {analysis.id}). {short} "
            "The full analysis with its sources is the newest analysis note on the work item.")
    author = Author(type=AUTHOR_AGENT, user_id=user.id, agent_hash=analysis_agent_hash(analysis))
    return await post_message(db, project_id=item.project_id, author=author,
                              arguments={"kind": "info", "body": body, "work_item_id": item.id})


__all__ = ["NOTE_AUTHOR_TYPE", "NOTE_KIND", "analysis_agent_hash", "append_analysis_note", "post_analysis_info"]
