"""The coding workflow gate that tool dispatch asks after approval.

Registry dispatch asks this module once; the gate returns an already annotated ``denied_by_policy``
result, so the trace names the gate that refused the call: ``coding_delivery_gate``
(:mod:`.coding_delivery_gate`) allows no delivery before the approved verification contract is
proven in this session.
"""

from __future__ import annotations

from typing import Any

from ..tools.results import annotate_tool_result_payload
from .coding_delivery_gate import enforce_coding_delivery_validation


async def enforce_coding_dispatch_gates(tool_name: str, params: dict[str, Any], context: Any) -> dict[str, Any] | None:
    """The coding gate's annotated result, or ``None`` when it allows the call."""
    del params
    delivery_block = await enforce_coding_delivery_validation(tool_name, context)
    if delivery_block is None:
        return None
    return annotate_tool_result_payload(
        tool_name, delivery_block, category="denied_by_policy", policy="coding_delivery_gate"
    )


__all__ = ["enforce_coding_dispatch_gates"]
