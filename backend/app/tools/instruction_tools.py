"""``instruction_get``: read one published instruction by its exact key."""

from __future__ import annotations

from typing import Any

from ..services.instructions.resolve import instruction_get
from .context import ToolContext


class InstructionGetTool:
    name = "instruction_get"
    description = "Read one published instruction by its exact key (global or the active Workspace)."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if not context.db:
            return {"error": "No active database session"}
        key = str(params.get("key") or "").strip()
        if not key:
            return {"state": "needs_clarification", "reason": "instruction_key_required"}
        project_id = str((context.project_config or {}).get("project_id") or "").strip() or None
        found = await instruction_get(context.db, key=key, project_id=project_id)
        if found is None:
            return {"error": "No published instruction with this key here", "reason": "instruction_not_found",
                    "key": key}
        return found


__all__ = ["InstructionGetTool"]
