"""External agent session ingest: usage return and the session transcript.

External agent work (e.g. Claude Code) enters the platform through a shadow
`Session` row (`agent_type="external_agent"`) so every existing report and
budget mechanism applies unchanged. The redacted transcript digest becomes the
shadow session's messages and feeds the knowledge graph.

A session returns knowledge through the governed ``episode_summary`` and ``memory_remember`` tools.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Session, UsageEvent, User
from ..time_utils import utc_now
from .approval import ensure_approval_request
from .knowledge_graph.agent_sessions import AgentSessionRecord, process_agent_session_knowledge
from .mcp_external_session_records import (
    _link_work_item,
    _normalized_usage_records,
    _persist_session_messages,
    _record_usage_events,
)
from .project import get_user_project_ids

EXTERNAL_AGENT_TYPE = "external_agent"
EXTERNAL_PROVIDER = "claude_code"

# The real CLI client is the honest provider label (claude_code / codex /
# opencode), derived from the client_session_id prefix when not sent
# explicitly - a Codex session must not be tagged as claude_code.
_CLIENT_BY_PREFIX = {
    "claude-code-": "claude_code",
    "codex-": "codex",
    "opencode-": "opencode",
}


def _resolve_client(arguments: dict[str, Any], client_session_id: str) -> str:
    explicit = str(arguments.get("client") or "").strip().lower()
    if explicit:
        return explicit
    for prefix, name in _CLIENT_BY_PREFIX.items():
        if client_session_id.startswith(prefix):
            return name
    return EXTERNAL_AGENT_TYPE
MAX_SUMMARY_CHARS = 8000


async def _require_project_access(db: AsyncSession, user: User, project_id: str) -> str:
    value = str(project_id or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail="project_id is required")
    if value not in set(await get_user_project_ids(user.id, db)):
        raise HTTPException(status_code=403, detail="Grant is not allowed to access this project")
    return value


async def create_external_shadow_session(
    db: AsyncSession,
    *,
    user: User,
    project_id: str | None,
    grant_id: str | None,
    client: str = EXTERNAL_PROVIDER,
    source_metadata: dict[str, Any] | None = None,
) -> Session:
    session = Session(
        id=str(uuid.uuid4()),
        user_id=user.id,
        project_id=project_id,
        agent_type=EXTERNAL_AGENT_TYPE,
        status="completed",
        origin="mcp",
        ended_at=utc_now(),
        metadata_={
            "external_source": client,
            "oauth_grant_id": grant_id,
            **(source_metadata or {}),
        },
    )
    db.add(session)
    await db.flush()
    return session


_MAX_DIGEST_CHARS = 80_000


async def persist_session_knowledge(
    db: AsyncSession,
    *,
    user: User,
    project_id: str,
    platform_session_id: str,
    client_session_id: str,
    summary: str,
    digest: str,
    workspace_ref: str = "",
    models: list[str] | None = None,
    work_item_key: str = "",
) -> dict[str, Any]:
    """Work-item link and knowledge-graph processing for one ingested session.

    Shared by ``mcp_session_ingest`` and the agent gateway's finalize. Flushes only; it never touches
    the session's usage events, messages or tool calls. The transcript itself lives on the shadow
    session (its messages and the ``summary`` metadata).
    """
    work_item_link = await _link_work_item(
        db, user=user, client_session_id=client_session_id, work_item_key=work_item_key
    )
    graph_result: dict[str, Any] | None = None
    text = str(digest or "").strip()
    if text and client_session_id:
        # Graph-first: the session flows into the knowledge graph at ingest
        # (chunks + deterministic record + governed extraction) — it is
        # outside the connector sync pipeline and would otherwise never
        # reach the graph stage. Best effort: a failed graph step must not
        # lose the session or its usage records.
        graph_result = await process_agent_session_knowledge(
            db,
            project_id=project_id,
            record=AgentSessionRecord(
                session_id=platform_session_id,
                key=f"agent-session-{client_session_id}"[:220],
                title=f"Agent session {client_session_id}",
                summary=(summary or "")[:800],
                content=text[:_MAX_DIGEST_CHARS],
            ),
            user=user,
            workspace_ref=workspace_ref,
            models=models,
        )
    return {"knowledge_graph": graph_result, "work_item_link": work_item_link}


async def _find_reingest_session(db: AsyncSession, *, user: User, client_session_id: str) -> Session | None:
    """The shadow session an earlier ingest of the same client session created, if any."""
    return (
        await db.execute(
            select(Session)
            .where(
                Session.user_id == user.id,
                Session.agent_type == EXTERNAL_AGENT_TYPE,
                Session.metadata_["client_session_id"].as_string() == client_session_id,
            )
            .limit(1)
        )
    ).scalar_one_or_none()


async def _ingest_target_session(
    db: AsyncSession,
    *,
    existing: Session | None,
    user: User,
    project_id: str,
    grant_id: str | None,
    client: str,
    summary: str,
    workspace_ref: str | None,
    client_session_id: str,
) -> Session:
    """The shadow session this ingest writes to: the earlier one reset, or a new one."""
    if existing is not None:
        # Re-ingest of the same client session (resume/re-end): replace the
        # usage instead of piling up duplicate platform sessions.
        metadata = dict(existing.metadata_ or {})
        metadata["summary"] = summary
        metadata["external_source"] = client
        existing.metadata_ = metadata
        await db.execute(delete(UsageEvent).where(UsageEvent.session_id == existing.id))
        session = existing
    else:
        session = await create_external_shadow_session(
            db,
            user=user,
            project_id=project_id,
            grant_id=grant_id,
            client=client,
            source_metadata={
                "summary": summary,
                "workspace_ref": workspace_ref,
                "client_session_id": client_session_id or None,
            },
        )
    return session


async def mcp_session_ingest(
    db: AsyncSession,
    *,
    user: User,
    grant_id: str | None,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Ingest an external session: summary + per-model usage records."""
    project_id = await _require_project_access(db, user, str(arguments.get("project_id") or ""))
    summary = str(arguments.get("summary") or "").strip()[:MAX_SUMMARY_CHARS]
    usage_records = _normalized_usage_records(arguments.get("usage"))
    client_session_id = str(arguments.get("client_session_id") or "").strip()
    client = _resolve_client(arguments, client_session_id)
    existing = (
        await _find_reingest_session(db, user=user, client_session_id=client_session_id) if client_session_id else None
    )
    session = await _ingest_target_session(
        db,
        existing=existing,
        user=user,
        project_id=project_id,
        grant_id=grant_id,
        client=client,
        summary=summary,
        workspace_ref=str(arguments.get("workspace_ref") or "").strip() or None,
        client_session_id=client_session_id,
    )
    usage_event_ids = await _record_usage_events(
        db, session=session, user=user, client=client, usage_records=usage_records
    )
    digest = str(arguments.get("transcript_digest") or "")
    messages_persisted = await _persist_session_messages(
        db,
        session=session,
        digest=digest,
        model=(usage_records[0]["model"] if usage_records else ""),
        provider=client,
        is_reingest=existing is not None,
    )
    knowledge = await persist_session_knowledge(
        db,
        user=user,
        project_id=project_id,
        platform_session_id=session.id,
        client_session_id=client_session_id,
        summary=summary,
        digest=digest,
        workspace_ref=str(arguments.get("workspace_ref") or "").strip(),
        models=[record["model"] for record in usage_records],
        work_item_key=str(arguments.get("work_item_key") or "").strip(),
    )
    await db.commit()
    return {
        "external_session_id": session.id,
        "usage_events": len(usage_event_ids),
        "messages": messages_persisted,
        "knowledge_graph": knowledge["knowledge_graph"],
        "work_item_link": knowledge["work_item_link"],
        "status": "ingested",
    }


async def mcp_approval_request(
    db: AsyncSession,
    *,
    user: User,
    grant_id: str | None,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """File a formal approval request from an external agent session."""
    project_id = await _require_project_access(db, user, str(arguments.get("project_id") or ""))
    action = str(arguments.get("action") or "").strip()
    if not action:
        raise HTTPException(status_code=400, detail="action is required")
    reason = str(arguments.get("reason") or "").strip() or None
    session = await create_external_shadow_session(
        db,
        user=user,
        project_id=project_id,
        grant_id=grant_id,
        source_metadata={"purpose": "approval_request", "requested_action": action},
    )
    approval = await ensure_approval_request(
        db,
        requested_by=user.id,
        action=action,
        reason=reason,
        session_id=session.id,
    )
    await db.commit()
    return {
        "approval_id": approval.id,
        "status": approval.status,
        "external_session_id": session.id,
    }
