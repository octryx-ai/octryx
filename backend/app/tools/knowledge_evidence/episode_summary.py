"""``knowledge_episode_summary``: the agent saves this platform session's episode summary on request."""

from __future__ import annotations

from typing import Any

from ...models import Session
from ...services.knowledge.episodes.writer import EpisodeProvenance, record_episode_summary, refusal
from ..context import ToolContext
from ._scope import authorized_workspace

PLATFORM_CLIENT = "platform"
SUB_AGENT_REFUSAL = {
    "state": "denied",
    "reason": "user_session_required",
    "error": "Only the user-facing session can save its episode summary, not a sub-agent.",
}


class KnowledgeEpisodeSummaryTool:
    name = "knowledge_episode_summary"
    description = (
        "Save a summary of what this session established as the session's episode in the Workspace "
        "Knowledge, cited with a link to the session."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if context.sub_agent_depth:
            return dict(SUB_AGENT_REFUSAL)
        authorized = await authorized_workspace(params, context)
        if type(authorized) is dict:
            return authorized
        session = await context.db.get(Session, context.session_id) if context.session_id else None
        if (
            session is None
            or str(session.user_id) != str(context.user_id)
            or session.project_id != authorized.project_id
            or session.parent_session_id
        ):
            return refusal("invalid_session")
        result = await record_episode_summary(
            context.db,
            authorized=authorized,
            provenance=EpisodeProvenance(
                session_id=str(session.id),
                client=PLATFORM_CLIENT,
                recorded_by=str(context.user_id),
                session_date=session.started_at.date().isoformat() if session.started_at else "",
            ),
            summary=params.get("summary"),
            title=params.get("title"),
            products=params.get("products"),
            version=params.get("version"),
        )
        if result.get("state") == "recorded":
            await context.db.commit()
        return {**result, "kind": "session_episode"}


__all__ = ["KnowledgeEpisodeSummaryTool"]
