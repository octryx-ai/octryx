"""``knowledge_changes``: what changed in a product between two versions, as cited graph facts."""

from __future__ import annotations

from typing import Any

from ...services.knowledge.ledger.errors import EvidenceLedgerError
from ...services.knowledge.retrieval.locator import SourceRefs, citation_link, within_budget
from ...services.knowledge.runtime import get_evidence_runtime
from ...services.knowledge.temporal.change_types import CHANGE_EDGE_TYPES
from ...services.knowledge.temporal.errors import GraphStoreError
from ..context import ToolContext
from ._scope import failure, knowledge_scope


class KnowledgeChangesTool:
    name = "knowledge_changes"
    description = (
        "List what changed in a product between two versions of the current Workspace's knowledge, as cited facts "
        "extracted from release notes and migration guides. Read-only."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        scope = await knowledge_scope(params, context)
        if type(scope) is dict:
            return scope
        from ...services.knowledge.temporal.scoped_changes import scoped_changes

        try:
            workspace_id, result = await scoped_changes(
                context.db,
                runtime=get_evidence_runtime(),
                scope=scope,
                product=params.get("product"),
                to_version=params.get("to_version"),
                from_version=params.get("from_version"),
                query=params.get("query") or None,
                limit=params.get("limit"),
                # Typed change records only, unless the model asks for every extracted fact.
                kinds=None if params.get("changes_only") is False else frozenset(CHANGE_EDGE_TYPES),
            )
        except EvidenceLedgerError as error:
            return failure(error.state.value)
        except GraphStoreError:
            return failure("unavailable")
        # Each fact with its source's cite_as, then trimmed to the result budget; sources follow the kept facts.
        rows = within_budget(
            [
                {
                    "kind": item.relation,
                    "fact": item.fact,
                    "version": item.version,
                    "_cite": citation_link(item.citation),
                }
                for item in result.facts
            ],
            reserve=2500,
        )
        sources = SourceRefs()
        facts = [
            {**{key: value for key, value in row.items() if key != "_cite"}, "source": sources.ref_link(row["_cite"])}
            for row in rows
        ]
        return {
            "state": result.state,
            # The Workspace whose extracted facts answer: the session's own, or a bound library.
            "workspace": scope.name_of(workspace_id),
            "product": result.product,
            "from_version": result.from_version,
            "to_version": result.to_version,
            "versions": list(result.versions),
            # Totals per kind across the whole range; the facts below are one page of them.
            "kind_counts": result.kind_counts,
            "fact_count": len(facts),
            "facts_not_shown": len(result.facts) - len(facts),
            "facts": facts,
            # Cite a fact by copying the cite_as of its source.
            "sources": sources.listing(),
        }


__all__ = ["KnowledgeChangesTool"]
