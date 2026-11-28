"""The refusals of an external coding agent's request at the inbound gateway and what each tells the person."""

from __future__ import annotations

from ..agent_gateway.contract import STATE_DENIED
from ..content_detection.vocabulary import (
    DETECTOR_PROMPT_INJECTION,
    DETECTOR_SECRETS,
)
from ..content_security.format_request_body import GatewayScan
from ..content_security.handling import (
    ACTION_REFUSE,
    POLICY_PROMPT_INJECTION_REFUSED,
    POLICY_UNSCANNED_WITHHELD,
    REASON_GATEWAY_REFUSED,
    HandlingPlan,
)
from ..model_gateway.inbound.refusals import REASON_SECRET_DETECTED, InboundRefusal, refusal
from .decision import (
    REASON_CONTENT_POLICY_DENIED,
    REASON_CONTENT_POLICY_UNAVAILABLE,
    REASON_SCAN_UNFINISHED,
    ContentDecision,
)
from .gateway_outcome import STAGE_CEDAR, STAGE_CONTENT, STAGE_TOOL_RESULT_POLICY, GatewayOutcome
from .obligations import Obligation, workspace_obligation

#: What the person does next, for every coding agent (the refusal reaches Claude Code and Codex alike).
NEXT_STEP_HINT = ("Remove the affected message or start a new conversation (Claude Code: /rewind or /clear; Codex: "
                  "start a new session)")
DENIED_HINT = f"{NEXT_STEP_HINT}, or ask your Octryx administrator."
UNFINISHED_HINT = (f"This request is too large or dense to check in time, so it was not sent to the model. "
                   f"{NEXT_STEP_HINT}.")
UNAVAILABLE_HINT = ("The content policies cannot be evaluated right now, so a request with this data is not sent. "
                    "Try again later or ask your Octryx administrator.")


def fixed_refusal(scan: GatewayScan, outcome: GatewayOutcome, finished: bool) -> InboundRefusal | None:
    if not finished:
        outcome.content = {"scanned": True, "complete": False, "unfinished": True}
        return outcome.refuse(refusal(STATE_DENIED, REASON_SCAN_UNFINISHED, http_status=400, hint=UNFINISHED_HINT),
                              STAGE_CONTENT, policies=(POLICY_UNSCANNED_WITHHELD,), fixed="unfinished")
    if not scan.injection:
        return None
    outcome.content = {**outcome.content, DETECTOR_PROMPT_INJECTION: {"count": scan.injection}}
    return outcome.refuse(refusal(
        STATE_DENIED, REASON_CONTENT_POLICY_DENIED, http_status=403,
        hint=f"The newest turn or one of its tool results tries to override instructions "
             f"({POLICY_PROMPT_INJECTION_REFUSED}). {DENIED_HINT}"),
        STAGE_CONTENT, policies=(POLICY_PROMPT_INJECTION_REFUSED,), fixed="prompt_injection")


# A refuse kind refuses the newest turn; in older turns the client re-sends it is masked (the conversation goes on).
def handling_refusal(plan: HandlingPlan, outcome: GatewayOutcome, newest: frozenset[str]) -> InboundRefusal | None:
    refusing = sorted(kind for kind, action in outcome.requested.items() if action == ACTION_REFUSE and kind in newest)
    if not refusing:
        return None
    if DETECTOR_SECRETS in refusing:
        item = refusal(STATE_DENIED, REASON_SECRET_DETECTED, http_status=400,
                       hint=f"This request contains what looks like a secret; it was not sent to the model. "
                            f"{DENIED_HINT}")
    else:
        item = refusal(STATE_DENIED, REASON_CONTENT_POLICY_DENIED, http_status=403,
                       hint=f"Content handling {', '.join(plan.policies(refusing, ACTION_REFUSE))} refuses what was "
                            f"found. {DENIED_HINT}")
    return outcome.refuse(item, STAGE_CONTENT, policies=plan.policies(refusing, ACTION_REFUSE))


def tool_result_refusal(tool: str, reason: str, policies: tuple[str, ...], obligation: str,
                        outcome: GatewayOutcome) -> InboundRefusal:
    cedar = {"policies": list(policies), "obligation": obligation or "deny", "applied": ACTION_REFUSE, "tool": tool}
    if reason == REASON_CONTENT_POLICY_UNAVAILABLE:
        item = refusal(STATE_DENIED, reason, http_status=403, hint=UNAVAILABLE_HINT)
    else:
        item = refusal(STATE_DENIED, reason, http_status=403,
                       hint=f"Policy {', '.join(policies) or 'the content policy'} keeps results of the tool {tool} "
                            f"out of the model; on the gateway this request is refused. {DENIED_HINT}")
    return outcome.refuse(item, STAGE_TOOL_RESULT_POLICY, policies=policies, cedar=cedar)


def content_refusal(decision: ContentDecision, outcome: GatewayOutcome) -> InboundRefusal:
    obligation = ""
    if decision.refusal != REASON_CONTENT_POLICY_UNAVAILABLE and decision.policies:
        resolved = workspace_obligation(decision.policies)
        obligation = resolved.kind if isinstance(resolved, Obligation) else ""
    reason = decision.refusal if decision.refusal == REASON_CONTENT_POLICY_UNAVAILABLE else (
        REASON_GATEWAY_REFUSED if obligation else REASON_CONTENT_POLICY_DENIED)
    cedar = {"policies": list(decision.policies), "obligation": obligation or "deny", "applied": ACTION_REFUSE}
    if reason == REASON_CONTENT_POLICY_UNAVAILABLE:
        hint = UNAVAILABLE_HINT
    elif obligation:
        hint = f"{decision.message()} The policy's mask or reroute could not satisfy it. {DENIED_HINT}"
    else:
        hint = f"{decision.message()} {DENIED_HINT}"
    return outcome.refuse(refusal(STATE_DENIED, reason, http_status=403, hint=hint), STAGE_CEDAR,
                          policies=decision.policies, cedar=cedar)


__all__ = [
    "DENIED_HINT",
    "NEXT_STEP_HINT",
    "content_refusal",
    "fixed_refusal",
    "handling_refusal",
    "tool_result_refusal",
]
