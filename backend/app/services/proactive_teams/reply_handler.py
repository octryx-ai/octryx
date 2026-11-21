"""Handler for inbound replies to proactive Teams conversations.

When a reporter replies to a proactive question from the agent, this module:
1. Looks up the ProactiveConversation record by conversation_id
2. Stores the answer
3. Resumes the waiting agent session with the new information
4. Comments the answer on the Jira ticket only when the Workspace opted in
   (``teams_reply_to_jira``, default false; ``jira_reply_policy``)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..content_security.untrusted_fence import untrusted_section
from ..model_gateway.inbound.secret_scan import contains_secret
from ..run_capability.declared import resumed_run_capability_metadata

logger = logging.getLogger(__name__)


async def check_proactive_reply(
    db: AsyncSession,
    conversation_id: str,
    content: str,
    sender_id: str,
) -> dict[str, Any] | None:
    """Check if an inbound message is a reply to a proactive conversation.

    Returns a dict with routing info if matched, or None if this is a normal message.
    """
    from ...models.integration.proactive_conversation import ProactiveConversation

    result = await db.execute(
        select(ProactiveConversation).where(
            ProactiveConversation.conversation_id == conversation_id,
            ProactiveConversation.status == "pending",
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        return None

    # Check expiry
    if conv.expires_at and datetime.now(UTC) > conv.expires_at:
        conv.status = "expired"
        await db.commit()
        return None

    # Store the answer
    conv.answer = content
    conv.status = "answered"
    conv.answered_at = datetime.now(UTC)
    await db.commit()

    logger.info(
        "Proactive reply received for ticket %s from %s (session=%s)",
        conv.ticket_id,
        conv.reporter_email,
        conv.session_id,
    )

    return {
        "matched": True,
        "ticket_id": conv.ticket_id,
        "session_id": conv.session_id,
        "question": conv.question,
        "answer": content,
        "reporter_email": conv.reporter_email,
        "project_id": conv.project_id,
    }


async def process_proactive_reply(
    db: AsyncSession,
    match: dict[str, Any],
) -> str | None:
    """Process a matched proactive reply — resume agent session and update Jira.

    Returns a confirmation message to send back to the reporter.
    """
    ticket_id = match["ticket_id"]
    session_id = match["session_id"]
    answer = match["answer"]
    project_id = match["project_id"]

    # An emergency stop holds machine work in its scope: no Jira comment and no resumed agent run until an admin
    # lifts it (the resume runs as a fire-and-forget task outside the scheduler's gate).
    from ..operations.emergency_stop import new_starts_held

    if await new_starts_held(db, project_id or None):
        logger.info("Proactive reply for ticket %s not processed: emergency stop", ticket_id)
        return (f"⏸️ Thanks! Automation is paused right now, so your answer for ticket **{ticket_id}** was not "
                "processed. Please answer again once it is running.")

    # 1. The reporter's answer as a Jira comment: an external write, only under the Workspace opt-in.
    commented = await _comment_on_ticket(
        db, ticket_id=ticket_id, session_id=session_id, project_id=project_id, answer=answer
    )

    # 2. Resume the agent session by injecting the answer as a user message
    if session_id:
        try:
            await _resume_agent_session(db, session_id, ticket_id, answer)
        except Exception:
            logger.exception("Failed to resume agent session %s", session_id)

    if commented:
        return (
            f"✅ Thanks! Your answer was added to ticket **{ticket_id}** "
            f"and is being processed now."
        )
    return f"✅ Thanks! Your answer for ticket **{ticket_id}** was received and is being processed now."


async def _comment_on_ticket(
    db: AsyncSession, *, ticket_id: str, session_id: str | None, project_id: str, answer: str
) -> bool:
    """Post the answer as a Jira comment when the Workspace allows it; True only when it was posted."""
    try:
        from ...tools.registry import TOOL_REGISTRY
        from ..project import get_project_config
        from .jira_reply_policy import JIRA_COMMENT_TOOL, teams_reply_to_jira_decision

        jira_comment_tool = TOOL_REGISTRY.get(JIRA_COMMENT_TOOL)
        if not jira_comment_tool or not session_id:
            return False
        project_config = {**await get_project_config(project_id, db), "project_id": project_id}
        decision = teams_reply_to_jira_decision(project_config)
        if not decision.allowed:
            logger.info("Proactive reply not commented on ticket %s: %s", ticket_id, decision.reason)
            return False

        from ...tools.context import ToolContext
        from ..named_connections.tool_routing import routed_execute
        from ..run_capability.direct_dispatch import execute_with_capability_check
        from ..run_capability.worker_profiles import worker_tool_context_state

        # The Workspace's merged connector config and the session: the comment runs on the connection
        # of the ticket's project, exactly as a chat call would, never on a borrowed one.
        # No admin role: this posts one reporter answer under the Workspace's own opt-in; the worker profile and the
        # connection's allowlist bound it, never a platform role.
        ctx = ToolContext(
            user_id="system",
            project_ids=[project_id],
            roles=[],
            session_id=session_id,
            project_config=project_config,
            db=db,
            run_capability=worker_tool_context_state("proactive_teams_reply"),
        )
        if contains_secret(answer):
            logger.info("Proactive reply not commented on ticket %s: secret_detected", ticket_id)
            return False
        comment_text = (
            f"*Reporter's answer (via Teams):*\n\n"
            f"{answer}\n\n"
            f"_(Recorded automatically from a proactive question)_"
        )
        result = await routed_execute(
            jira_comment_tool.name,
            {"ticket_id": ticket_id, "body": comment_text},
            ctx,
            lambda params, context: execute_with_capability_check(jira_comment_tool, params, context),
        )
    except Exception:
        logger.exception("Failed to comment proactive reply on ticket %s", ticket_id)
        return False
    if isinstance(result, dict) and result.get("error"):
        logger.warning("Proactive reply not commented on ticket %s: %s", ticket_id, result.get("code") or "refused")
        return False
    logger.info("Proactive reply commented on ticket %s", ticket_id)
    return True


async def _resume_agent_session(
    db: AsyncSession,
    session_id: str,
    ticket_id: str,
    answer: str,
) -> None:
    """Inject the reporter's answer into the agent session and re-trigger the agent loop."""
    import uuid

    from ...models.session.session import Message, Session

    session = await db.get(Session, session_id)
    if not session:
        logger.warning("Cannot resume session %s — not found", session_id)
        return

    # Inject the answer as a user message into the session
    # The reply is the reporter's own text: an untrusted block, never the session owner's instruction.
    inject_content = (
        "[Proactive follow-up answered] The reporter answered the question about the ticket.\n"
        f"{untrusted_section('reporter reply', {'ticket_id': ticket_id, 'answer': answer}, source='the reporter')}\n"
        "Please continue working on the ticket."
    )
    msg = Message(
        id=str(uuid.uuid4()),
        session_id=session_id,
        role="user",
        content=inject_content,
    )
    db.add(msg)

    # Mark session as active for continuation
    metadata = dict(session.metadata_ or {})
    metadata["proactive_reply_received"] = True
    metadata["proactive_reply_ticket"] = ticket_id
    # The continuation resumes under the class the session's own run recorded.
    metadata.update(resumed_run_capability_metadata(metadata))
    session.metadata_ = metadata
    session.status = "active"
    await db.commit()

    # Re-trigger the agent loop asynchronously
    import asyncio

    asyncio.create_task(_run_agent_continuation(session_id, session, inject_content, db))

    logger.info("Agent session %s resumed with proactive reply for ticket %s", session_id, ticket_id)


async def _run_agent_continuation(session_id: str, session, user_message: str, db: AsyncSession) -> None:
    """Run the agent loop continuation in the background."""
    try:
        from ...agent.engine import run_agent

        async for event in run_agent(
            session_id=session_id,
            user_message=user_message,
            user_id=session.user_id,
            project_id=session.project_id,
            agent_type=session.agent_type or "chat",
            db=db,
        ):
            pass  # Agent runs to completion; results stored in session messages

        logger.info("Agent continuation completed for session %s", session_id)
    except Exception:
        logger.exception("Agent continuation failed for session %s", session_id)

