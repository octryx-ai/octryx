"""``memory_recall``: what earlier sessions of this Workspace remember, never as source evidence.

Returns the user's own personal memories and the Workspace's memories, each with its state, author
class and session provenance. The answer is marked ``kind: memory`` and ``not_source_evidence``; it has
no ``source_url`` and no ``cite_as``, so a memory cannot be copied into an answer as a citation.
"""

from __future__ import annotations

from typing import Any

from ...services.knowledge.memory.errors import MemoryRefusedError
from ...services.knowledge.memory.presentation import MEMORY_KIND
from ...services.knowledge.memory.recall import parse_recall_request, recall
from ...services.prompt_catalog.out_of_turn import prompt_set_for
from ..context import ToolContext
from ..knowledge_evidence._scope import authorized_workspace
from . import refused


class MemoryRecallTool:
    name = "memory_recall"
    description = (
        "Recall memories from earlier sessions of this Workspace (personal and team decisions, conventions, "
        "learnings). Memory is not source evidence and is never cited as a source. Read-only."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        authorized = await authorized_workspace(params, context)
        if type(authorized) is dict:
            return authorized
        try:
            request = parse_recall_request(params.get("query"), params.get("classes"), params.get("limit"))
            items = await recall(context.db, authorized=authorized, user_id=str(context.user_id), request=request)
        except MemoryRefusedError as error:
            return refused(error)
        return {
            "state": "ok" if items else "no_match",
            "kind": MEMORY_KIND,
            "not_source_evidence": True,
            "notice": (await prompt_set_for(context.db, workspace_id=authorized.project_id)).render(
                "knowledge.memory.notice"
            ),
            "item_count": len(items),
            "items": items,
        }


__all__ = ["MemoryRecallTool"]
