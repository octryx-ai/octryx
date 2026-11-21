"""Repository records as repository nodes with their commit authors."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...store import upsert_edge, upsert_node
from ..common import slugify
from .people import ingest_person_from_source

_SERVICE_ACCOUNT_MARKERS = ("jenkins", "pipeline", "bot", "svc-", "service account")


def _is_service_account(name: str) -> bool:
    normalized = str(name or "").lower()
    return any(marker in normalized for marker in _SERVICE_ACCOUNT_MARKERS) or normalized.endswith(" ci")


async def _link_commit_authors(
    db: AsyncSession, *, project_id: str | None, record: dict[str, Any], repository: Any, label: str, source_ref: str
) -> None:
    linked: set[str] = set()
    for person in record.get("source_people") or []:
        if not isinstance(person, dict) or person.get("role") != "commit_author":
            continue
        name = str(person.get("display_name") or person.get("name") or "")
        if _is_service_account(name):
            continue
        node = await ingest_person_from_source(db, project_id=project_id, person=person, source_ref=source_ref)
        if node is None or node.id in linked:
            continue
        linked.add(node.id)
        await upsert_edge(
            db,
            project_id=project_id,
            edge_type="contributed_to",
            source_node_id=node.id,
            target_node_id=repository.id,
            description=f"{node.display_name} commits to {label}",
            source_refs=[source_ref],
        )


async def ingest_repository_record(
    db: AsyncSession,
    *,
    project_id: str | None,
    record: dict[str, Any],
) -> Any | None:
    """Deterministically map a repository bronze record (snapshot/outline/etc.)
    into the graph: a repository node with branch/commit properties and
    commit authors as contributed_to edges (service accounts filtered)."""
    label = str(record.get("label") or record.get("repository") or "").strip()
    if not label:
        return None
    source_ref = f"repo:{label}"
    summary = str(record.get("summary") or "").strip()

    # Deterministic cross-type consolidation: a prose-extracted node (e.g. a
    # "product" named after the repo slug) holding one of our aliases IS this
    # repository — the structured record is authoritative. Merge it in so the
    # alias resolves to the repository node.
    from ...identity import merge_nodes
    from ...store import resolve_node_by_alias

    slug = label.split("/")[-1]
    colliders = []
    for alias in (label, slug):
        node = await resolve_node_by_alias(db, project_id=project_id, alias=alias)
        if node is not None and node.node_type not in ("repository", "person") and node.status == "active":
            colliders.append(node)
    repository = await upsert_node(
        db,
        project_id=project_id,
        node_type="repository",
        node_key=slugify(f"repo-{label}"),
        display_name=label,
        description=summary or f"Repository {label}",
        aliases=[label, label.split("/")[-1]],
        properties={
            "branch": record.get("branch_name"),
            "head_commit": record.get("current_head_commit"),
            "provider": "bitbucket",
        },
        source_refs=[source_ref],
    )
    for collider in colliders:
        if collider.id != repository.id:
            await merge_nodes(db, keep_node_id=repository.id, merge_node_id=collider.id)
    await _link_commit_authors(
        db, project_id=project_id, record=record, repository=repository, label=label, source_ref=source_ref
    )
    return repository
