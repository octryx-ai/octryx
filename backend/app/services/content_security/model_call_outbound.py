"""The provider drivers' final-bytes check (I-1): every driver's request, examined as sent.

The provider wrapper (``model_call.enforced_chat``) binds the call's ``final_check.FinalCheck``
(:func:`bound_final`) around the driver's ``chat``. Every driver produces its request body through :func:`final_body`
(an HTTP JSON body: exactly these bytes are sent) or :func:`final_arguments` (Bedrock Converse: the argument object
the SDK serializes, a faithful encoding of it). Each send site of every registered driver calls one of them right
before the send (``tests/content_security/test_final_check_drivers.py`` lists them).
A send without a bound check — a driver called outside the wrapper — is refused: there is no unchecked path. The one
send of constant platform text outside a model call (the LiteLLM qualification probe) binds :func:`bound_constant`:
no content kind may be in it.
"""

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
    """A platform call's final check: no prompt injection and no kind the plan keeps out (``refuse``, ``mask``,
    ``mask_reroute``); a rerouting kind only when ``model`` (the alias the call goes to) is the Workspace's governance
    alias (:attr:`HandlingPlan.governance_alias`); the reported kinds read to state whether the request carries them.
    The call's system texts as sent (``sent``, the provider copy of ``messages``), the administrator-authored ones
    marked; ``passed``: handed to the transport, with the examination of what it carries."""
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
    """The final-bytes check of a send of constant platform text (a qualification probe): every content kind out."""
    with bound_final(FinalCheck(frozenset(KIND_IDS), RequestBudget())):
        yield


def _check() -> FinalCheck:
    check = _FINAL.get()
    if check is None:
        raise FinalCheckRefused(REASON_UNBOUND)
    return check


def final_body(payload: Any) -> bytes:
    """The driver's request body, serialized exactly as it is sent, after the final check."""
    return examine_request(_check(), payload)


def final_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """An SDK's request arguments (serialized by the SDK itself), after the final check of that object."""
    examine_request(_check(), arguments)
    return arguments


__all__ = ["JSON_HEADERS", "REASON_UNBOUND", "bound_constant", "bound_final", "call_check", "final_arguments",
           "final_body"]
