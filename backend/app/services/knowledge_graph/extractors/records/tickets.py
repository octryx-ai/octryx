"""Ticket records as ticket nodes linked to their people and components."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...store import upsert_edge, upsert_node
from ..common import slugify
from .people import ingest_person_identity


async def _link_people(
    db: AsyncSession, *, project_id: str | None, ticket: dict[str, Any], ticket_node: Any, key: str,
    source_ref: str | None,
) -> None:
    person_roles = [
        ("assignee", "assigned_to", ticket.get("assignee_name"), ticket.get("assignee_username"),
         ticket.get("assignee_email")),
        ("reporter", "authored", ticket.get("reporter_name"), ticket.get("reporter_username"),
         ticket.get("reporter_email")),
        ("creator", "authored", ticket.get("creator_name"), ticket.get("creator_username"),
         ticket.get("creator_email")),
    ]
    linked_person_edges: set[tuple[str, str]] = set()
    for role, edge_type, name, username, email in person_roles:
        name = str(name or "").strip()
        username = str(username or "").strip()
        if not (name or username):
            continue
        person = await ingest_person_identity(
            db,
            project_id=project_id,
            display_name=name or username,
            usernames=[username] if username else [],
            emails=[email] if email else [],
            source_ref=source_ref,
        )
        if (edge_type, person.id) in linked_person_edges:
            continue
        linked_person_edges.add((edge_type, person.id))
        await upsert_edge(
            db,
            project_id=project_id,
            edge_type=edge_type,
            source_node_id=ticket_node.id if edge_type == "assigned_to" else person.id,
            target_node_id=person.id if edge_type == "assigned_to" else ticket_node.id,
            description=f"{key} {role} {person.display_name}",
            source_refs=[source_ref] if source_ref else None,
        )


async def _link_components(
    db: AsyncSession, *, project_id: str | None, ticket: dict[str, Any], ticket_node: Any, key: str,
    source_ref: str | None,
) -> None:
    for component in ticket.get("components") or []:
        component = str(component).strip()
        if not component:
            continue
        component_node = await upsert_node(
            db,
            project_id=project_id,
            node_type="component",
            node_key=slugify(component),
            display_name=component,
            description=f"Component {component}",
        )
        await upsert_edge(
            db,
            project_id=project_id,
            edge_type="affects",
            source_node_id=ticket_node.id,
            target_node_id=component_node.id,
            description=f"{key} affects {component}",
            source_refs=[source_ref] if source_ref else None,
        )


async def ingest_ticket_record(
    db: AsyncSession,
    *,
    project_id: str | None,
    ticket: dict[str, Any],
) -> Any:
    """Turn a ticket record into a ticket node linked to its assignee and components."""
    key = str(ticket.get("key") or "").strip()
    title = str(ticket.get("title") or "").strip()
    source_ref = f"ticket:{key}" if key else None
    ticket_node = await upsert_node(
        db,
        project_id=project_id,
        node_type="ticket",
        node_key=slugify(key or title),
        display_name=f"{key}: {title}".strip(": ").strip(),
        description=title,
        properties={"status": ticket.get("status"), "priority": ticket.get("priority")},
        source_refs=[source_ref] if source_ref else None,
    )
    await _link_people(
        db, project_id=project_id, ticket=ticket, ticket_node=ticket_node, key=key, source_ref=source_ref
    )
    await _link_components(
        db, project_id=project_id, ticket=ticket, ticket_node=ticket_node, key=key, source_ref=source_ref
    )
    return ticket_node
