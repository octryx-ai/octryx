"""``knowledge_read``: a cited passage with the paragraphs around it (contract §7).

Takes an ``evidence_key`` from a ``knowledge_search`` result and returns that span with up
to ``window`` neighbouring spans of the same revision, from the ledger. Read-only; the Workspaces are
the run's own and the ones it is bound to read, never a parameter.
"""

from __future__ import annotations

from typing import Any

from ...services.knowledge.ledger.errors import EvidenceLedgerError
from ...services.knowledge.retrieval.scoped import scoped_read
from ..context import ToolContext
from ._scope import failure, knowledge_scope
from .source_links import read_source_url

DEFAULT_WINDOW = 1


class KnowledgeReadTool:
    name = "knowledge_read"
    description = (
        "Read a cited Knowledge passage together with the neighbouring paragraphs of the same source revision. "
        "With neighbours, every passage is labelled [evidence_key]; cite the key of the passage that states a fact. "
        "Read-only."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        scope = await knowledge_scope(params, context)
        if type(scope) is dict:
            return scope
        window = params.get("window", DEFAULT_WINDOW)
        try:
            workspace_id, read = await scoped_read(
                context.db, scope=scope, evidence_key=params.get("evidence_key"), window=window
            )
        except EvidenceLedgerError as error:
            return failure(error.state.value)
        # The source's own link, or this Workspace's original of the exact revision.
        source_url = await read_source_url(
            context.db,
            source_url=read.source_url,
            workspace_id=workspace_id,
            primary_workspace_id=scope.primary.project_id,
            evidence_key=read.evidence_key,
        )
        return {
            "state": "ok",
            "workspace": scope.name_of(workspace_id),
            "evidence_key": read.evidence_key,
            "text": labelled_text(read),
            "passage_keys": [key for key, _ in read.passages] or [read.evidence_key],
            "citation": read.citation,
            "revision": read.revision_ordinal,
            "spans": [read.first_span, read.last_span],
            "source_title": read.source_title,
            "source_url": source_url,
            # False: the source has a newer revision; say so when citing this one.
            "current": read.current,
        }


def labelled_text(read: Any) -> str:
    """One passage as is; a window labels each passage with its own evidence key, so a citation can be exact."""
    if len(read.passages) <= 1:
        return read.text
    return "\n\n".join(f"[{key}]\n{text}" for key, text in read.passages)


__all__ = ["KnowledgeReadTool", "labelled_text"]
