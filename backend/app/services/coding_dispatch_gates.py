"""The coding workflow gate that tool dispatch asks after approval."""

from __future__ import annotations

from typing import Any

from ..tools.results import annotate_tool_result_payload
from .coding_delivery_gate import enforce_coding_delivery_validation


async def enforce_coding_dispatch_gates(tool_name: str, params: dict[str, Any], context: Any) -> dict[str, Any] | None:
    del params
    delivery_block = await enforce_coding_delivery_validation(tool_name, context)
    if delivery_block is None:
        return None
    return annotate_tool_result_payload(
        tool_name, delivery_block, category="denied_by_policy", policy="coding_delivery_gate"
    )


__all__ = ["enforce_coding_dispatch_gates"]
