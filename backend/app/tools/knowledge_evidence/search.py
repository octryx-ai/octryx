"""``knowledge_search``: hybrid, cited retrieval over the governed Workspace evidence."""

from __future__ import annotations

from typing import Any

from ...services.knowledge.ledger.errors import EvidenceLedgerError, InvalidEvidenceRequestError
from ...services.knowledge.retrieval.graph_expansion import GraphExpansion, expand_scoped_hits
from ...services.knowledge.retrieval.locator import evidence_locator, within_budget
from ...services.knowledge.retrieval.scoped import scoped_evidence
from ...services.knowledge.runtime import get_evidence_runtime
from ..context import ToolContext
from ..definitions.knowledge_evidence import MAX_TOOL_RESULT_LIMIT
from ._scope import failure, knowledge_scope
from .changes import KnowledgeChangesTool
from .source_links import presented_citation

DEFAULT_TOOL_RESULT_LIMIT = 8
CHANGES_LIMIT = 10
# The change-fact ranking accepts a bounded query; a longer search query lists the facts unranked.
MAX_CHANGES_QUERY_CHARS = 500
# The graph facts next to the passages stay small: a few cited sentences, never the passages' budget.
FACTS_BUDGET_BYTES = 3000


def _bounded_limit(raw: object) -> int:
    if raw is None:
        return DEFAULT_TOOL_RESULT_LIMIT
    # Exact ``int``: ``True`` is not a result count, and a numeric string is not an integer.
    if type(raw) is not int or not 1 <= raw <= MAX_TOOL_RESULT_LIMIT:
        raise InvalidEvidenceRequestError()
    return raw


class KnowledgeSearchTool:
    name = "knowledge_search"
    description = (
        "Search the current Workspace's governed Knowledge evidence (lexical and semantic), including the "
        "Workspaces it is bound to read (such as a shared library). Read-only; every passage carries a citation "
        "that resolves to one source revision and one evidence span, and names its Workspace."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        scope = await knowledge_scope(params, context)
        if type(scope) is dict:
            return scope
        raw_query = params.get("query")
        if type(raw_query) is not str or not (query_text := raw_query.strip()):
            return failure("invalid_request")
        try:
            # An unconfigured instance answers the closed needs_configuration state, never a raised error.
            runtime = get_evidence_runtime()
            result = await scoped_evidence(
                context.db,
                runtime=runtime,
                scope=scope,
                query_text=query_text,
                limit=_bounded_limit(params.get("limit")),
                products=params.get("products"),
                version=params.get("version"),
            )
        except EvidenceLedgerError as error:
            return failure(error.state.value)
        found = {
            "state": "ok",
            "workspace_id": scope.primary.project_id,
            "result_count": len(result.evidence),
            # Which retrieval modes answered, per Workspace in scope; anything but "ok" means partial.
            "mode_states": dict(result.workspace_states.get(scope.primary.project_id, {})),
            "bound_workspaces": {
                scope.name_of(workspace_id) or workspace_id: states
                for workspace_id, states in result.workspace_states.items()
                if workspace_id != scope.primary.project_id
            },
            "evidence": [
                {
                    # The Workspace this passage was found in: the session's own, or a bound one.
                    "workspace": scoped.workspace_name,
                    "evidence_key": hit.evidence.evidence_key,
                    "text": hit.evidence.text,
                    "citation": hit.evidence.citation,
                    "revision_id": hit.evidence.revision_id,
                    "revision": hit.evidence.revision_ordinal,
                    "span_ordinal": hit.evidence.span_ordinal,
                    "chars": [hit.evidence.char_start, hit.evidence.char_end],
                    "source_title": hit.evidence.source_title,
                    "products": list(hit.evidence.products),
                    "version": hit.evidence.version,
                    # Parsed documents: pages and the heading path the span sits under.
                    **evidence_locator(hit.evidence),
                    # Where a person can open the source: its own link, or this Workspace's original of the
                    # exact revision for an uploaded source; null when there is nothing to open.
                    **presented_citation(
                        hit.evidence, workspace_id=scoped.workspace_id, primary_workspace_id=scope.primary.project_id
                    ),
                    "found_by": list(hit.modes),
                    "similarity": None if hit.similarity is None else round(hit.similarity, 3),
                    # The reranker's relevance, when one ranked this answer.
                    "relevance": None if hit.relevance is None else round(hit.relevance, 3),
                }
                for scoped in result.evidence
                for hit in [scoped.hit]
            ],
        }
        expansion = await expand_scoped_hits(
            context.db,
            runtime=runtime,
            scope=scope,
            retrieval=result,
            products=params.get("products"),
            version=params.get("version"),
        )
        found["facts"] = _facts_section(expansion, scope)
        changes = await _changes_for_one_product(params, query_text, context)
        if changes is not None:
            found["changes"] = changes
        return found


def _facts_section(expansion: GraphExpansion, scope) -> dict[str, Any]:
    rows = within_budget(
        [
            {
                "workspace": scoped.workspace_name,
                "kind": scoped.item.fact.relation,
                "fact": scoped.item.fact.fact,
                "version": scoped.item.fact.version,
                # ``hit``: extracted from a passage above; ``related``: one hop away, ranked by the query.
                "via": scoped.item.via,
                "evidence_key": scoped.item.fact.citation.evidence_key,
                **presented_citation(
                    scoped.item.fact.citation,
                    workspace_id=scoped.workspace_id,
                    primary_workspace_id=scope.primary.project_id,
                ),
            }
            for scoped in expansion.facts
        ],
        reserve=0,
        budget=FACTS_BUDGET_BYTES,
    )
    return {
        "state": expansion.state,
        "fact_count": len(rows),
        "facts_not_shown": len(expansion.facts) - len(rows),
        "facts": rows,
        # Per Workspace whose hits were expanded: whether its graph answered.
        "workspace_states": {
            scope.name_of(workspace_id) or workspace_id: state
            for workspace_id, state in expansion.workspace_states.items()
        },
    }


async def _changes_for_one_product(params: dict, query_text: str, context: ToolContext) -> dict[str, Any] | None:
    products = params.get("products")
    version = params.get("version")
    if not (isinstance(products, list) and len(products) == 1 and isinstance(version, str) and version.strip()):
        return None
    return await KnowledgeChangesTool().execute(
        {
            "product": products[0],
            "to_version": version,
            "query": query_text if len(query_text) <= MAX_CHANGES_QUERY_CHARS else None,
            "limit": CHANGES_LIMIT,
        },
        context,
    )


__all__ = ["KnowledgeSearchTool"]
