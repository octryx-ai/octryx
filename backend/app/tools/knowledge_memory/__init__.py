"""Agent tools of the Memory lobe: thin — scope from the run, call the service, render.

The Workspace comes from ``ToolContext`` exactly as for the Knowledge evidence tools; no schema has a
``project_id`` or user parameter. Every failure is a fixed state with a fixed message.
"""

from __future__ import annotations

from typing import Any

from ...services.knowledge.memory.errors import MemoryRefusedError


def refused(error: MemoryRefusedError) -> dict[str, Any]:
    return {"error": error.message, "state": error.state, "reason": error.reason}
