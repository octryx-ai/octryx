"""The impact of a version change on a codebase, cited and commit-pinned.

``code_impact`` joins the product's change facts for a version range (``knowledge_changes`` over the
reader's Knowledge scope, so a bound library Workspace can supply them) with the code elements of
one resolved codebase (``codebase.resolve_codebase``):

- a **checkout** on disk inside the session workspace, scanned in place (``scan.scan_checkout``);
- a Workspace **repository source** at its ``head_commit``: the elements its sync recorded in the
  repository file index (``repository_index.load_repository_index``), derived from the same text
  the revisions store;
- or (``code_impact_for_elements``) the elements of files an MCP client sent explicitly.

Either way the result names the commit the elements come from. This module only reads.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from ..access.bindings import KnowledgeScope
from ..runtime import EvidenceRuntime
from ..temporal.change_types import ACTION_REQUIRED_TYPES
from ..temporal.changes import MAX_IMPACT_FACTS, STATE_OK
from ..temporal.scoped_changes import scoped_changes
from .codebase import Codebase
from .impact import ImpactItem, join_impact
from .repository_reads import load_repository_index
from .scan import CodeElement, scan_checkout


@dataclass(frozen=True, slots=True)
class CodeImpact:
    state: str
    product: str
    from_version: str | None
    to_version: str
    versions: tuple[str, ...]
    commit: str | None
    elements_scanned: int
    facts_considered: int
    items: tuple[ImpactItem, ...]
    # The Workspace whose change facts were joined: the reader's own, or a bound library.
    facts_workspace_id: str = ""


async def code_impact(
    db: AsyncSession,
    *,
    runtime: EvidenceRuntime,
    scope: KnowledgeScope,
    codebase: Codebase,
    product: object,
    to_version: object,
    from_version: object = None,
) -> CodeImpact:
    async def elements() -> tuple[CodeElement, ...]:
        if codebase.repository is not None and codebase.commit is not None:
            index = await load_repository_index(
                db, connector_id=codebase.repository.connector_id, head_commit=codebase.commit
            )
            return index.elements
        return await asyncio.to_thread(scan_checkout, codebase.root)

    return await _impact(db, runtime=runtime, scope=scope, commit=codebase.commit, elements=elements,
                         product=product, to_version=to_version, from_version=from_version)


async def code_impact_for_elements(
    db: AsyncSession,
    *,
    runtime: EvidenceRuntime,
    scope: KnowledgeScope,
    elements: tuple[CodeElement, ...],
    commit: str | None,
    product: object,
    to_version: object,
    from_version: object = None,
) -> CodeImpact:
    """The impact on elements a caller already holds: the files an MCP client sent explicitly."""

    async def given() -> tuple[CodeElement, ...]:
        return elements

    return await _impact(db, runtime=runtime, scope=scope, commit=commit, elements=given,
                         product=product, to_version=to_version, from_version=from_version)


async def _impact(db, *, runtime, scope, commit, elements, product, to_version, from_version) -> CodeImpact:
    facts_workspace_id, changes = await scoped_changes(
        db,
        runtime=runtime,
        scope=scope,
        product=product,
        to_version=to_version,
        from_version=from_version,
        limit=MAX_IMPACT_FACTS,
        kinds=ACTION_REQUIRED_TYPES,
        max_facts=MAX_IMPACT_FACTS,
    )
    if changes.state != STATE_OK:
        return CodeImpact(changes.state, changes.product, changes.from_version, changes.to_version,
                          changes.versions, commit, 0, 0, (), facts_workspace_id)
    # Only changes that can require an edit (the graph read filters by kind; this is the second check).
    actionable = tuple(fact for fact in changes.facts if fact.relation in ACTION_REQUIRED_TYPES)
    found = await elements()
    items = join_impact(actionable, found)
    return CodeImpact(STATE_OK, changes.product, changes.from_version, changes.to_version, changes.versions,
                      commit, len(found), len(actionable), items, facts_workspace_id)


__all__ = ["CodeImpact", "code_impact", "code_impact_for_elements"]
