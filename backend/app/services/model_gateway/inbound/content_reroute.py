"""A gateway request whose content the Workspace sends to another alias: admitted there and planned once more."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from ...agent_gateway.contract import STATE_DENIED
from ...content_routing.gateway import DENIED_HINT
from ...content_routing.gateway_outcome import STAGE_CONTENT, GatewayOutcome
from ...content_security.enforcement_inbound import InboundPlan
from ...content_security.handling import REASON_ROUTE_UNAVAILABLE
from .refusals import InboundRefusal, refusal

Target = TypeVar("Target")


def route_unavailable(outcome: GatewayOutcome, alias: str) -> InboundRefusal:
    return outcome.refuse(refusal(
        STATE_DENIED, REASON_ROUTE_UNAVAILABLE, http_status=403,
        hint=f"The content of this request must go to the model {alias or '(none set)'}, which cannot take it on "
             f"this route. {DENIED_HINT}"), STAGE_CONTENT)


async def planned(plan_for: Callable[[Target], Awaitable[InboundPlan]],
                  admit: Callable[[str], Awaitable[Target | InboundRefusal]], target: Target,
                  outcome: GatewayOutcome) -> tuple[InboundPlan, Target]:
    plan = await plan_for(target)
    if plan.refusal is not None or not plan.reroute:
        return plan, target
    rerouted: Any = await admit(plan.reroute)
    if isinstance(rerouted, InboundRefusal):
        return InboundPlan(refusal=route_unavailable(outcome, plan.reroute)), target
    second = await plan_for(rerouted)
    if second.refusal is None and second.reroute:  # the target asks for yet another alias: never a chain
        return InboundPlan(refusal=route_unavailable(outcome, second.reroute)), rerouted
    return second, rerouted


__all__ = ["planned", "route_unavailable"]
