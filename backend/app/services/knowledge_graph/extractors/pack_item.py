"""Deterministic extractor for ``engineering_pack_item`` bronze records.

A published (human-reviewed) Engineering Knowledge Pack item becomes a
knowledge node whose description carries the reviewed summary, with the item
triggers as aliases (they are the retrieval keywords the pack author chose),
version claims from ``version_scope`` ("spring_boot 4.0: ..."), and — when an
exact alias match exists — a ``references`` edge to the technology node
(library/product) the item is about.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..store import replace_claims_of_type, resolve_node_by_alias, upsert_edge, upsert_node
from .common import slugify

_MAX_TRIGGER_ALIASES = 12
_DESCRIPTION_CONTENT_CHARS = 700


def _description(record: dict[str, Any], summary: str, trust_tier: str, source_uri: str) -> str:
    content_head = " ".join(str(record.get("content") or "").split())[:_DESCRIPTION_CONTENT_CHARS]
    description_parts = [part for part in (summary, content_head) if part]
    if source_uri:
        description_parts.append(f"Source ({trust_tier or 'unrated'}): {source_uri}")
    return ". ".join(description_parts)


def _version_claims(version_scope: dict[str, Any], title: str, summary: str, source_ref: str) -> list[dict[str, Any]]:
    return [
        {
            "statement": f"{technology} {version}: {title}" + (f" — {summary}" if summary else ""),
            "valid_from_label": str(version),
            "source_refs": [source_ref],
        }
        for technology, version in version_scope.items()
        if str(version).strip()
    ]


async def _link_technologies(
    db: AsyncSession, *, project_id: str | None, version_scope: dict[str, Any], node: Any, title: str,
    source_ref: str,
) -> None:
    # Deterministic technology linking: exact alias match only (e.g. the
    # version_scope key "spring_boot" resolving to a library/product node).
    for technology in version_scope:
        for candidate in {technology, technology.replace("_", "-"), technology.replace("_", " ")}:
            target = await resolve_node_by_alias(db, project_id=project_id, alias=candidate)
            if target is not None and target.id != node.id:
                await upsert_edge(
                    db,
                    project_id=project_id,
                    edge_type="references",
                    source_node_id=node.id,
                    target_node_id=target.id,
                    description=f"{title} documents {target.display_name}",
                    source_refs=[source_ref],
                )
                break


async def ingest_pack_item_record(
    db: AsyncSession, *, project_id: str | None, record: dict[str, Any]
) -> Any | None:
    # A published pack is org knowledge by definition: the graph node lives
    # in the INSTANCE-GLOBAL scope regardless of which project's bronze entry
    # triggered the ingestion — one node, visible to every project, never a
    # per-project duplicate.
    project_id = None
    title = str(record.get("title") or "").strip()
    pack_key = str(record.get("pack_key") or "").strip()
    item_key = str(record.get("item_key") or "").strip()
    if not title or not item_key:
        return None
    source_ref = f"ek-pack:{pack_key}:{item_key}" if pack_key else f"ek-pack:{item_key}"
    summary = str(record.get("summary") or "").strip()
    trust_tier = str(record.get("trust_tier") or "").strip()
    source_uri = str(record.get("source_uri") or "").strip()

    triggers = [str(t).strip() for t in (record.get("triggers") or []) if str(t).strip()]
    node = await upsert_node(
        db,
        project_id=project_id,
        node_type="knowledge_item",
        node_key=slugify(f"ekp-{pack_key}-{item_key}"),
        display_name=title,
        description=_description(record, summary, trust_tier, source_uri),
        aliases=[title, item_key, *triggers[:_MAX_TRIGGER_ALIASES]],
        properties={
            "pack_key": pack_key,
            "stack_key": record.get("stack_key"),
            "trust_tier": trust_tier,
            "source_uri": source_uri,
            "version_scope": dict(record.get("version_scope") or {}),
        },
        source_refs=[source_ref],
        # Pack items are identified by their pack-scoped key; triggers are
        # retrieval hooks, never identity.
        resolve_by_alias=False,
    )

    version_scope = record.get("version_scope") if isinstance(record.get("version_scope"), dict) else {}
    await replace_claims_of_type(
        db,
        project_id=project_id,
        subject_node_id=node.id,
        claim_type="pack_version_scope",
        claims=_version_claims(version_scope, title, summary, source_ref),
    )
    await _link_technologies(
        db, project_id=project_id, version_scope=version_scope, node=node, title=title, source_ref=source_ref
    )
    return node


__all__ = ["ingest_pack_item_record"]
