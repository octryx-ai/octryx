"""Agent tools of the Memory lobe: thin — scope from the run, call the service, render."""

from __future__ import annotations

from typing import Any

from ...services.knowledge.memory.errors import MemoryRefusedError


def refused(error: MemoryRefusedError) -> dict[str, Any]:
    return {"error": error.message, "state": error.state, "reason": error.reason}
