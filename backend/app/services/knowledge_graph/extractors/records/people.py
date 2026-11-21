"""Person nodes from source records, merged across connectors via aliases."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...store import upsert_node
from ..common import slugify

# source_people role -> edge type for authorship-ish contributions.
_CONTRIBUTION_EDGE_BY_ROLE = {
    "creator": "authored",
    "author": "authored",
    "updated_by": "contributed_to",
    "editor": "contributed_to",
    "comment_author": "contributed_to",
    "publisher": "contributed_to",
}


async def ingest_person_identity(
    db: AsyncSession,
    *,
    project_id: str | None,
    display_name: str,
    usernames: list[str] | None = None,
    emails: list[str] | None = None,
    source_ref: str | None = None,
) -> Any:
    """Upsert a Person node, resolving all identifiers to one node via aliases."""
    aliases = [*(usernames or []), *(emails or [])]
    key_seed = display_name or (usernames or emails or ["unknown"])[0]
    node = await upsert_node(
        db,
        project_id=project_id,
        node_type="person",
        node_key=slugify(key_seed),
        display_name=display_name or key_seed,
        description=f"Person {display_name or key_seed}",
        aliases=aliases,
        source_refs=[source_ref] if source_ref else None,
    )
    # A merge can leave a username as the surviving display name ("alice");
    # when a source provides the human-readable full name, upgrade to it.
    display = str(display_name or "").strip()
    if display and " " in display and " " not in str(node.display_name or ""):
        node.display_name = display
    return node


async def ingest_person_from_source(
    db: AsyncSession,
    *,
    project_id: str | None,
    person: dict[str, Any],
    source_ref: str | None = None,
) -> Any | None:
    """Upsert a person node from a normalized ``source_people`` entry, feeding
    EVERY identifier (username, name, email) into the alias table so identities
    merge deterministically across connectors.

    When one source record's identifiers resolve to SEVERAL existing nodes
    (e.g. a 'Alice Example' node from Jira full names and an 'alice' node from
    Confluence usernames), that record is deterministic proof they are the same
    human — the nodes are consolidated before the upsert. This is not a fuzzy
    merge: the evidence is a single connector record naming both identifiers.
    """
    display = str(person.get("display_name") or person.get("name") or "").strip()
    username = str(person.get("username") or "").strip()
    email = str(person.get("email") or "").strip()
    name = str(person.get("name") or "").strip()
    if not (display or username or name):
        return None

    from ...identity import merge_nodes
    from ...store import resolve_node_by_alias

    identifiers = [value for value in {display, username, email, name} if value]
    matched: dict[str, Any] = {}
    for identifier in identifiers:
        node = await resolve_node_by_alias(db, project_id=project_id, alias=identifier)
        if node is not None and node.node_type == "person" and node.status == "active":
            matched[node.id] = node
    if len(matched) > 1:
        nodes = sorted(matched.values(), key=lambda item: ((item.created_at is None), item.created_at, item.id))
        keep = nodes[0]
        for merge in nodes[1:]:
            await merge_nodes(db, keep_node_id=keep.id, merge_node_id=merge.id)

    usernames = [value for value in {username, name} if value and value != display]
    return await ingest_person_identity(
        db,
        project_id=project_id,
        display_name=display or username or name,
        usernames=usernames,
        emails=[email] if email else [],
        source_ref=source_ref,
    )
