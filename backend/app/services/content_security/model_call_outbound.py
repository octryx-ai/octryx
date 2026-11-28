"""The provider drivers' final-bytes check: every driver's request, examined as sent."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from ..content_detection.examination import Examination, RequestBudget
from ..content_detection.final_check import FinalCheck, FinalCheckRefused, examine_request
from .handling import ACTION_REFUSE, ACTION_REPORT, KIND_IDS, MASKING, REROUTING, HandlingPlan
from .message_trust import TRUST_AUTHORED, checked_trust

REASON_UNBOUND = "content_final_check_unbound"
JSON_HEADERS = {"content-type": "application/json"}

_FINAL: ContextVar[FinalCheck | None] = ContextVar("octryx_model_call_final_check", default=None)


def call_check(plan: HandlingPlan, budget: RequestBudget, messages: list[Any], sent: list[Any], model: str,
               passed: Callable[[Examination], None]) -> FinalCheck:
    system = [(item, copy["content"]) for item, copy in zip(messages, sent, strict=False)
              if isinstance(copy, dict) and copy.get("role") == "system" and isinstance(copy.get("content"), str)
              and copy["content"]]
    return FinalCheck(plan.kinds(ACTION_REFUSE, *MASKING), budget, route_kinds=plan.kinds(*REROUTING),
                      routed=bool(plan.governance_alias) and model == plan.governance_alias,
                      reported=plan.kinds(ACTION_REPORT),
                      authored=tuple(text for item, text in system if checked_trust(item) == TRUST_AUTHORED),
                      system=tuple(text for _item, text in system), passed=passed)


@contextmanager
def bound_final(check: FinalCheck) -> Iterator[None]:
    token = _FINAL.set(check)
    try:
        yield
    finally:
        _FINAL.reset(token)


@contextmanager
def bound_constant() -> Iterator[None]:
    # A send of constant platform text outside a model call (the qualification probe): every content kind is kept out.
    with bound_final(FinalCheck(frozenset(KIND_IDS), RequestBudget())):
        yield


def _check() -> FinalCheck:
    check = _FINAL.get()
    if check is None:  # a driver called outside the provider wrapper: there is no unchecked send
        raise FinalCheckRefused(REASON_UNBOUND)
    return check


def final_body(payload: Any) -> bytes:
    return examine_request(_check(), payload)


def final_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    examine_request(_check(), arguments)
    return arguments


__all__ = ["JSON_HEADERS", "REASON_UNBOUND", "bound_constant", "bound_final", "call_check", "final_arguments",
           "final_body"]
