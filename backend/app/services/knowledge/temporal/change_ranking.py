"""Which change facts a page shows first: document structure, not keyword guessing.

A version range has hundreds of typed change facts, and one page shows about twenty. Without a topic,
the page must show what an upgrade hinges on: the new baselines, removed and replaced components,
the major dependency moves. Where those are is a property of the *documents*, not of the words in a
fact:

1. **Kind tier.** Blocking changes (requires, removed, renamed, replaced, moved), then changes to
   revisit (deprecated, default changed), then new capabilities.
2. **Document role.** Within a tier, migration guides and release notes come first (read in turns),
   then specifications and references, then a configuration changelog. The role is the one
   the knowledge package gave the document (``KnowledgePackageDocument.role``), or else the one its
   Source Sync connector gave it (a Jira release: ``release_notes``); a source without either ranks
   with references.
3. **Document order.** Within a document, earlier sections first: a migration guide opens with its
   system requirements and the moves everything else depends on.
4. **Breadth.** Within a document, sections are taken in turns, so one long section does not fill
   the page.
5. **Product level.** Within a tier, facts whose subject is the product itself ("Spring Boot 4.0
   requires Java 17", "... updates Jackson to 3.0") take turns with all other facts. They are the
   baselines an upgrade starts from, and a guide states several of them in one section, so section
   turns alone would show one per section. The subject is the fact's graph entity, compared with
   the product key; no word of the fact is read.

Facts that say the same thing (same kind, same text ignoring case and spacing) are shown once.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_packages import KnowledgePackageDocument
from ..sources.sync.items import connector_source_roles

ROLE_RANK = {
    "migration_guide": 0,
    "release_notes": 1,
    "specification": 2,
    "reference": 2,
    "configuration_changelog": 3,
}
UNKNOWN_ROLE_RANK = 2


class _Citation(Protocol):
    revision_id: str
    source_id: str
    span_ordinal: int
    section_path: tuple[str, ...]


class _Fact(Protocol):
    relation: str
    fact: str
    citation: _Citation


class _ProductFact(_Fact, Protocol):
    source_entity: str


async def source_roles(db: AsyncSession, project_id: str, source_ids: Iterable[str]) -> dict[str, str]:
    """The explicit role of each source: its knowledge package's, else the Source Sync connector's."""
    ids = sorted({source_id for source_id in source_ids if source_id})
    if not ids:
        return {}
    rows = await db.execute(
        select(KnowledgePackageDocument.source_id, KnowledgePackageDocument.role).where(
            KnowledgePackageDocument.project_id == project_id, KnowledgePackageDocument.source_id.in_(ids)
        )
    )
    package_roles = {str(source_id): str(role) for source_id, role in rows.all()}
    return {**await connector_source_roles(db, project_id, ids), **package_roles}


def _normalized(text: str) -> str:
    # The same statement extracted twice differs only in case, spacing or a closing period.
    return " ".join(text.lower().split()).rstrip(".;:! ")


def distinct(facts: Iterable[_Fact]) -> list[_Fact]:
    seen: set[tuple[str, str]] = set()
    kept: list[_Fact] = []
    for item in facts:
        key = (item.relation, _normalized(item.fact))
        if key not in seen:
            seen.add(key)
            kept.append(item)
    return kept


def _breadth_within_document(facts: list[_Fact], kind_order: Callable[[str], int]) -> list[_Fact]:
    sections: dict[tuple[str, ...], list[_Fact]] = {}
    for item in sorted(facts, key=lambda fact: fact.citation.span_ordinal):
        # The leaf section: "Before You Start > Review System Requirements" is its own turn.
        sections.setdefault(tuple(item.citation.section_path), []).append(item)
    queues = [
        sorted(group, key=lambda f: (kind_order(f.relation), f.citation.span_ordinal, _text_order(f)))
        for group in sections.values()
    ]
    ordered: list[_Fact] = []
    while queues:
        ordered.extend(queue.pop(0) for queue in queues)
        queues = [queue for queue in queues if queue]
    return ordered


# Guides and release notes share the first band and are read in turns: one names the moves, the other
# the new baselines and dependency versions. Specifications and references follow, the configuration
# changelog (hundreds of single properties) last.
_BANDS = ((0, 1), (2,), (3,))


def _interleaved(sequences: list[list[_Fact]]) -> list[_Fact]:
    ordered: list[_Fact] = []
    queues = [list(sequence) for sequence in sequences if sequence]
    while queues:
        ordered.extend(queue.pop(0) for queue in queues)
        queues = [queue for queue in queues if queue]
    return ordered


def _slug(text: str) -> str:
    return "-".join("".join(char if char.isalnum() else " " for char in text.lower()).split())


def is_product_level(product: str) -> Callable[[_ProductFact], bool]:
    """Whether a fact's subject entity is the product itself (``Spring Boot 4.0`` for ``spring-boot``)."""
    key = _slug(product)

    def check(item: _ProductFact) -> bool:
        subject = _slug(item.source_entity)
        return bool(key) and (subject == key or subject.startswith(f"{key}-"))

    return check


def rank_tier(
    facts: list[_Fact],
    roles: dict[str, str],
    kind_order: Callable[[str], int],
    product_level: Callable[[_Fact], bool] | None = None,
) -> list[_Fact]:
    """One kind tier: product-level facts and the others take turns, each ranked by document structure."""
    if product_level is None:
        return _rank_documents(facts, roles, kind_order)
    level = [item for item in facts if product_level(item)]
    rest = [item for item in facts if not product_level(item)]
    # A document states its baselines together (one requirements section), so they are read in
    # document order; the other changes are read breadth-first by section.
    return _interleaved(
        [
            _rank_documents(level, roles, kind_order, breadth=False),
            _rank_documents(rest, roles, kind_order),
        ]
    )


def _text_order(item: _Fact) -> str:
    """Within one span, the order the facts were extracted in, which follows the text."""
    return str(getattr(item, "extracted_at", "") or "")


def _in_document_order(facts: list[_Fact], kind_order: Callable[[str], int]) -> list[_Fact]:
    return sorted(facts, key=lambda item: (item.citation.span_ordinal, _text_order(item), kind_order(item.relation)))


def _rank_documents(
    facts: list[_Fact], roles: dict[str, str], kind_order: Callable[[str], int], *, breadth: bool = True
) -> list[_Fact]:
    """Documents banded by role, in position order, each read breadth-first by section (or in order)."""
    documents: dict[str, list[_Fact]] = {}
    for item in facts:
        documents.setdefault(item.citation.revision_id, []).append(item)

    def first(revision_id: str) -> _Fact:
        return min(documents[revision_id], key=lambda fact: fact.citation.span_ordinal)

    def rank(revision_id: str) -> int:
        return ROLE_RANK.get(roles.get(first(revision_id).citation.source_id, ""), UNKNOWN_ROLE_RANK)

    ordered: list[_Fact] = []
    for band in _BANDS:
        members = sorted(
            (revision_id for revision_id in documents if rank(revision_id) in band),
            key=lambda revision_id: (rank(revision_id), first(revision_id).citation.span_ordinal, revision_id),
        )
        read = _breadth_within_document if breadth else _in_document_order
        ordered.extend(_interleaved([read(documents[m], kind_order) for m in members]))
    return ordered


__all__ = ["ROLE_RANK", "UNKNOWN_ROLE_RANK", "distinct", "is_product_level", "rank_tier", "source_roles"]
