"""Post-tool phase: a capability refusal in a read-only run asks the user, it never stalls.

When a tool call of this iteration was refused because the run is ``read_only`` and
``change`` would cover it, the turn ends in ``needs_clarification`` with the closed
``capability_escalation`` decision (``services/run_capability/escalation.py``). The
decision request rides on the clarification trace like every workflow decision, so the
chat renders its options as buttons and only the user's next request can answer it.
"""

from __future__ import annotations

from typing import Any

from ....services.run_capability.escalation import capability_escalation_request
from ._loop_post_tool_phases import _persist_synthesized_and_return, _PostToolEnv

CAPABILITY_ESCALATION_SOURCE = "run_capability_escalation"


async def _capability_escalation_outcome(env: _PostToolEnv) -> dict[str, Any] | None:
    request = capability_escalation_request(env.tool_results)
    if request is None:
        return None
    message, decision_request = request
    return await _persist_synthesized_and_return(
        env,
        synthesized_content=message,
        source=CAPABILITY_ESCALATION_SOURCE,
        workflow_decision_request=decision_request,
    )


__all__ = ["CAPABILITY_ESCALATION_SOURCE", "_capability_escalation_outcome"]
