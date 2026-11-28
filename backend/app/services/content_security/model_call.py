"""The one content-security enforcement point of every model call, whatever the provider driver."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from ..content_detection.examination import RequestBudget
from ..model_gateway.litellm.errors import LiteLLMGatewayError
from .enforcement_call import FINAL_POLICIES, enforce_call
from .handling import POINT_MODEL_CALL, POINT_MODEL_CALL_DIRECT
from .model_call_outcome import CallOutcome
from .model_call_record import STAGE_CEDAR


@dataclass(frozen=True, slots=True)
class GovernedContentRoute:
    admission: Any
    entry: Any
    admit: Callable[[str], Any]


def _point(route: Any) -> str:
    return POINT_MODEL_CALL if route is not None else POINT_MODEL_CALL_DIRECT


async def enforced_chat(provider: Any, chat: Callable[..., Awaitable[Any]], signature: inspect.Signature,
                        args: tuple, kwargs: dict[str, Any]) -> Any:
    budget = RequestBudget()  # the call's entry: its one budget starts here
    bound = signature.bind(provider, *args, **kwargs)
    model = str(bound.arguments.get("model") or "")
    route = provider.content_route(model)
    outcome = CallOutcome(_point(route), model)
    try:
        result, badge = await enforce_call(chat, bound, budget, route, model, outcome)
    except LiteLLMGatewayError as error:  # Cedar's refusal (or the governed driver's own failure)
        notice = error.content_notice
        if notice and outcome.refusal is None and outcome.sent is None:
            reason = str(error.denial_reason or "")
            policies = FINAL_POLICIES.get(reason) or tuple(notice.get("policies") or ())
            outcome.refuse(policies, outcome.target or model, reason, STAGE_CEDAR)  # unfinished: the fixed outcome
        if notice and outcome.refusal is not None:
            notice["decision_id"] = outcome.decision_id
        raise
    finally:
        outcome.write()
    if badge is not None:  # the governed conversation's badge: only a sent request, after its record
        await badge()
    return result


__all__ = ["GovernedContentRoute", "enforced_chat"]
