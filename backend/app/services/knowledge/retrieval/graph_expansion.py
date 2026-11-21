"""Graph expansion of a scoped hybrid search: the cited facts behind the hits (open point K3).

After ``scoped_evidence`` found its spans, each Workspace that contributed hits is asked for the
graph facts behind *its own* hits (``temporal/fact_expansion.py``), in its own database, with its
own authorized view. So the rules of the span search hold unchanged:

- **Bindings.** Only Workspaces of the resolved scope are read: the reader's own and its active,
  non-transitive bindings, whose classification ``resolve_scope`` re-checked for this read. A bound
  source is read with the binding's product bound, the same filter its span search used, so a
  fact of a product outside the binding is never shown; every fact's citation is re-checked.
- **ACL.** Citations resolve with the reader's principal keys; a fact without a citation its
  reader may open is dropped.

The Workspaces' facts are fused by rank (RRF, scope order breaking ties), the same fact stated in
two Workspaces is kept once, and the answer is cut to ``limit``. Every Workspace shares one time
budget (:data:`EXPANSION_BUDGET_SECONDS`), so a slow graph costs its facts, never the search.

Each Workspace's deterministic structured facts (``structured/expansion.py``) follow its extracted
facts; a Workspace whose extracted graph is absent answers ``ok`` when it has structured facts.
They are read inside the same deadline and inside a savepoint: a spent budget or any error of the
structured read is logged and yields no structured facts, never a failed ``knowledge_search``.

The overall state is ``ok`` when any Workspace's graph answered, even with no fact; otherwise the
reader's own state when its hits were expanded, else the first Workspace's; ``no_hits`` when the
search found nothing to expand. The per-Workspace states are reported next to it.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from ..access.authorization import AuthorizedWorkspace
from ..access.bindings import KnowledgeScope
from ..runtime import EvidenceRuntime
from ..sources.scope import normalize_products, normalize_version
from ..structured.expansion import structured_hit_facts
from ..temporal.change_ranking import distinct
from ..temporal.fact_expansion import STATE_OK, ExpandedFact, expand_workspace_facts
from .hybrid import RRF_K
from .scoped import ScopedRetrieval

logger = logging.getLogger(__name__)

DEFAULT_EXPANSION_FACTS = 8
MAX_EXPANSION_FACTS = 20
# Bolt reads and one query embedding per Workspace; well inside the tool call's own budget.
EXPANSION_BUDGET_SECONDS = 8.0
STATE_NO_HITS = "no_hits"


@dataclass(frozen=True, slots=True)
class ScopedFact:
    workspace_id: str
    workspace_name: str
    item: ExpandedFact


@dataclass(frozen=True, slots=True)
class GraphExpansion:
    state: str
    facts: tuple[ScopedFact, ...] = ()
    workspace_states: dict[str, str] = field(default_factory=dict)


def _targets(
    scope: KnowledgeScope, requested: tuple[str, ...]
) -> list[tuple[AuthorizedWorkspace, tuple[str, ...] | None]]:
    """Each Workspace in scope order with the product bound its span search used (``None``: unbounded)."""
    targets: list[tuple[AuthorizedWorkspace, tuple[str, ...] | None]] = [(scope.primary, requested or None)]
    for source in scope.sources:
        narrowed = source.products_for(requested)
        if narrowed is not None:
            targets.append((source.authorized, tuple(narrowed) or None))
    return targets


async def expand_scoped_hits(
    db: AsyncSession,
    *,
    runtime: EvidenceRuntime,
    scope: KnowledgeScope,
    retrieval: ScopedRetrieval,
    products: object = None,
    version: object = None,
    limit: int = DEFAULT_EXPANSION_FACTS,
) -> GraphExpansion:
    """The cited graph facts behind ``retrieval``'s hits, bounded, with an explicit state."""
    if type(limit) is not int or not 1 <= limit <= MAX_EXPANSION_FACTS:
        raise ValueError("graph expansion limit out of bounds")
    if not retrieval.evidence:
        return GraphExpansion(STATE_NO_HITS)
    targets = _targets(scope, tuple(normalize_products(products)) if products else ())
    hits: dict[str, list[tuple[str, int]]] = {}
    for scoped in retrieval.evidence:
        span = (scoped.hit.evidence.revision_id, scoped.hit.evidence.span_ordinal)
        hits.setdefault(scoped.workspace_id, []).append(span)
    subject_version = normalize_version(version)
    deadline = asyncio.get_running_loop().time() + EXPANSION_BUDGET_SECONDS
    states: dict[str, str] = {}
    answered: list[tuple[str, tuple[ExpandedFact, ...]]] = []
    for authorized, bound in targets:
        project_id = authorized.project_id
        if project_id not in hits:
            continue
        result = await expand_workspace_facts(
            db,
            runtime=runtime,
            authorized=authorized,
            query=retrieval.query_text,
            hits=hits[project_id],
            products=bound,
            version=subject_version,
            deadline=deadline,
            limit=limit,
        )
        states[project_id] = result.state
        # Deterministic structured facts follow the extracted ones and never reorder them.
        structured = await _structured_facts(
            db, authorized=authorized, hits=hits[project_id], products=bound, version=subject_version,
            query=retrieval.query_text, deadline=deadline, limit=limit,
        )
        if result.state == STATE_OK:
            answered.append((project_id, result.facts + structured))
        elif structured:
            states[project_id] = STATE_OK
            answered.append((project_id, structured))
    if answered:
        state = STATE_OK
    else:
        state = states.get(scope.primary.project_id) or next(iter(states.values()))
    return GraphExpansion(state, _fused(scope, answered)[:limit], states)


async def _structured_facts(
    db: AsyncSession,
    *,
    authorized: AuthorizedWorkspace,
    hits: list[tuple[str, int]],
    products: tuple[str, ...] | None,
    version: str | None,
    query: str,
    deadline: float,
    limit: int,
) -> tuple[ExpandedFact, ...]:
    """The Workspace's structured facts inside the shared deadline; ``()`` on a spent budget or any error."""
    if asyncio.get_running_loop().time() >= deadline:
        return ()
    try:
        async with asyncio.timeout_at(deadline):
            async with db.begin_nested():
                return await structured_hit_facts(
                    db, authorized=authorized, hits=hits, products=products, version=version, query=query,
                    limit=limit,
                )
    except TimeoutError:
        logger.warning("Structured graph expansion skipped: budget spent workspace=%s", authorized.project_id)
    except Exception as error:  # noqa: BLE001 - structured facts are optional; the search must answer.
        logger.warning(
            "Structured graph expansion failed: workspace=%s error=%s", authorized.project_id, type(error).__name__
        )
    return ()


def _fused(scope: KnowledgeScope, answered: list[tuple[str, tuple[ExpandedFact, ...]]]) -> list[ScopedFact]:
    scored: list[tuple[float, int, ScopedFact]] = []
    for order, (project_id, facts) in enumerate(answered):
        for rank, item in enumerate(facts, start=1):
            scored.append((1.0 / (RRF_K + rank), order, ScopedFact(project_id, scope.name_of(project_id), item)))
    ranked = [entry[2] for entry in sorted(scored, key=lambda entry: (-entry[0], entry[1]))]
    unique = {id(fact) for fact in distinct(entry.item.fact for entry in ranked)}
    kept: list[ScopedFact] = []
    seen_statements: set[tuple[str, str, str]] = set()
    for entry in ranked:
        if id(entry.item.fact) not in unique:
            continue
        # Two bound Workspaces extract the same statement in their own words: the same relation
        # between the same two graph entities is one fact, the best-ranked one is kept.
        statement = _statement(entry.item.fact)
        if statement is not None and statement in seen_statements:
            continue
        if statement is not None:
            seen_statements.add(statement)
        kept.append(entry)
    return kept


def _statement(fact: object) -> tuple[str, str, str] | None:
    relation = str(getattr(fact, "relation", "") or "")
    source = " ".join(str(getattr(fact, "source_entity", "") or "").lower().split())
    target = " ".join(str(getattr(fact, "target_entity", "") or "").lower().split())
    return (relation, source, target) if relation and source and target else None


__all__ = [
    "DEFAULT_EXPANSION_FACTS",
    "EXPANSION_BUDGET_SECONDS",
    "MAX_EXPANSION_FACTS",
    "STATE_NO_HITS",
    "GraphExpansion",
    "ScopedFact",
    "expand_scoped_hits",
]
