"""``memory_remember``: record what the user explicitly asked to be remembered, as ``human_stated``."""

from __future__ import annotations

from typing import Any

from ...services.knowledge.memory.capture import MemoryProvenance, remember
from ...services.knowledge.memory.errors import MemoryRefusedError
from ...services.knowledge.memory.presentation import present_as
from ..context import ToolContext
from ..knowledge_evidence._scope import authorized_workspace
from . import refused


class MemoryRememberTool:
    name = "memory_remember"
    description = (
        "Remember a statement the user explicitly asked to be remembered, in their own words, as memory "
        "(not as Knowledge evidence)."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if context.sub_agent_depth:
            return refused(MemoryRefusedError("human_turn_required"))
        authorized = await authorized_workspace(params, context)
        if type(authorized) is dict:
            return authorized
        try:
            result = await remember(
                context.db,
                authorized=authorized,
                provenance=MemoryProvenance(
                    user_id=str(context.user_id), session_id=context.session_id, turn_ref=context.request_id
                ),
                text=params.get("text"),
                scope=params.get("scope"),
                item_class=params.get("class"),
                product=params.get("product"),
                expires_in_days=params.get("expires_in_days"),
            )
        except MemoryRefusedError as error:
            return refused(error)
        await context.db.commit()
        item = result.item
        return {
            "state": result.outcome,
            "kind": "memory",
            "not_source_evidence": True,
            "memory_id": item.id,
            "scope": "personal" if item.scope == "user" else "workspace",
            "class": item.item_class,
            "author_class": item.author_class,
            "memory_state": item.state,
            "present_as": present_as(item),
        }


__all__ = ["MemoryRememberTool"]
