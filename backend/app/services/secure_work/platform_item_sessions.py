"""Links between platform work items and the client sessions that worked on them (item, session, graph)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session, User, WorkItem
from ...time_utils import utc_now

logger = logging.getLogger(__name__)

_MAX_LINKED_SESSIONS = 50


def _linked_sessions(item: WorkItem) -> list[dict[str, Any]]:
    fields = item.source_fields_json if isinstance(item.source_fields_json, dict) else {}
    links = fields.get("linked_sessions")
    return [link for link in links or [] if isinstance(link, dict)]


async def link_session_to_work_item(
    db: AsyncSession,
    *,
    item: WorkItem,
    client_session_id: str,
    current_user: User,
) -> dict[str, Any]:
    normalized = str(client_session_id or "").strip()
    if not normalized:
        raise HTTPException(status_code=422, detail="client_session_id is required")
    session = (
        await db.execute(
            select(Session)
            .where(
                Session.agent_type == "external_agent",
                Session.metadata_["client_session_id"].as_string() == normalized,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return await _record_session_link(
        db,
        item=item,
        client_session_id=normalized,
        session=session,
        current_user=current_user,
        graph_scoped=False,
    )


async def resolve_linkable_session(
    db: AsyncSession,
    *,
    item: WorkItem,
    client_session_id: str,
    current_user: User,
) -> Session:
    normalized = str(client_session_id or "").strip()
    if not normalized:
        raise HTTPException(status_code=422, detail="client_session_id is required")
    # Unknown, foreign-owner and other-Workspace sessions answer alike: the link discloses nothing
    not_found = HTTPException(status_code=404, detail=f"Session not found: {normalized}")
    if not item.project_id:
        raise not_found
    matches = (
        await db.execute(
            select(Session)
            .where(
                Session.agent_type == "external_agent",
                Session.user_id == current_user.id,
                Session.project_id == item.project_id,
                Session.metadata_["client_session_id"].as_string() == normalized,
            )
            .limit(2)
        )
    ).scalars().all()
    if not matches:
        raise not_found
    if len(matches) > 1:
        raise HTTPException(status_code=409, detail=f"Session reference is ambiguous: {normalized}")
    return matches[0]


async def link_validated_session_to_work_item(
    db: AsyncSession,
    *,
    item: WorkItem,
    session: Session,
    current_user: User,
) -> dict[str, Any]:
    if not item.project_id or session.project_id != item.project_id or session.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    client_session_id = str((session.metadata_ or {}).get("client_session_id") or "").strip()
    return await _record_session_link(
        db,
        item=item,
        client_session_id=client_session_id,
        session=session,
        current_user=current_user,
        graph_scoped=True,
    )


async def _record_session_link(
    db: AsyncSession,
    *,
    item: WorkItem,
    client_session_id: str,
    session: Session | None,
    current_user: User,
    graph_scoped: bool,
) -> dict[str, Any]:
    links = _linked_sessions(item)
    if not any(link.get("client_session_id") == client_session_id for link in links):
        links.append(
            {
                "client_session_id": client_session_id,
                "platform_session_id": session.id if session else None,
                "linked_at": utc_now().isoformat(),
                "linked_by": current_user.username,
            }
        )
        fields = dict(item.source_fields_json or {})
        fields["linked_sessions"] = links[-_MAX_LINKED_SESSIONS:]
        item.source_fields_json = fields

    if session is not None:
        metadata = dict(session.metadata_ or {})
        keys = [str(key) for key in metadata.get("work_item_keys") or []]
        if item.source_key not in keys:
            metadata["work_item_keys"] = [*keys, item.source_key]
            session.metadata_ = metadata
    await _link_session_in_graph(db, item=item, client_session_id=client_session_id, scoped=graph_scoped)
    await db.flush()
    return {
        "work_item": item.source_key,
        "client_session_id": client_session_id,
        "platform_session_found": session is not None,
        "linked_sessions": len(_linked_sessions(item)),
    }


async def _link_session_in_graph(
    db: AsyncSession, *, item: WorkItem, client_session_id: str, scoped: bool = False
) -> None:
    # The session node must belong to the item's own Workspace.
    try:
        from ...models import KnowledgeGraphNode
        from ..knowledge_graph import resolve_node_by_alias, upsert_edge

        node_query = select(KnowledgeGraphNode).where(
            KnowledgeGraphNode.node_type == "agent_session",
            KnowledgeGraphNode.node_key == f"agent-session-{client_session_id}",
        )
        if scoped:
            node_query = node_query.where(KnowledgeGraphNode.project_id == item.project_id)
        session_node = (await db.execute(node_query)).scalars().first()
        ticket_node = await resolve_node_by_alias(db, project_id=item.project_id, alias=item.source_key)
        if session_node is None or ticket_node is None:
            return
        await upsert_edge(
            db,
            project_id=item.project_id,
            edge_type="contributed_to",
            source_node_id=session_node.id,
            target_node_id=ticket_node.id,
            description=f"Agent session worked on {item.source_key}",
            source_refs=[f"session:{client_session_id}"],
        )
    except Exception:  # noqa: BLE001
        logger.exception("platform_item.graph_link_failed", extra={"work_item_id": item.id})
