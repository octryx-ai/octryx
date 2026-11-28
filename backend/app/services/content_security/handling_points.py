"""The enforcement points of sensitive-content handling: what each action and each fixed rule does at each point."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from .handling import (
    ACTION_DENY,
    ACTION_MASK,
    ACTION_MASK_REROUTE,
    ACTION_NONE,
    ACTION_REFUSE,
    ACTION_REROUTE,
    ACTION_REVIEW,
    ACTIONS,
    COMMAND_KINDS,
    KIND_IDS,
    MASKING,
    POINT_CODEX_SEAT,
    POINT_COMMANDS,
    POINT_GATEWAY_MESSAGES,
    POINT_GATEWAY_RESPONSES,
    POINT_MODEL_CALL,
    POINT_MODEL_CALL_DIRECT,
    POINT_MODEL_OUTPUT,
    POINT_TOOL_RESULTS,
    REASON_COMMAND_DENIED,
    REASON_COMMAND_REVIEW,
    REASON_OLDER_HISTORY_MASKED,
    REASON_ROUTE_UNAVAILABLE,
    REROUTING,
    SURFACE_COMMANDS,
    SURFACE_GATEWAY,
    SURFACE_PLATFORM,
)

FIXED_UNFINISHED = "unfinished"
FIXED_UNREADABLE = "unreadable"
FIXED_PROMPT_INJECTION = "prompt_injection"
FIXED_FINAL_BYTES = "final_bytes"
ACTION_WITHHOLD = "withhold"


@dataclass(frozen=True, slots=True)
class FixedOutcome:
    rule: str
    action: str
    label: str


_UNREADABLE_REFUSED = FixedOutcome(FIXED_UNREADABLE, ACTION_REFUSE, "Content of an unreadable shape refuses it")
#: ``content_security.enforcement_call``: unfinished withheld, injection in any field refused, final request verified.
_MODEL_CALL_FIXED = (
    FixedOutcome(FIXED_UNFINISHED, ACTION_WITHHOLD, "A part the detectors could not finish examining is withheld "
                                                    "from the request"),
    _UNREADABLE_REFUSED,
    FixedOutcome(FIXED_PROMPT_INJECTION, ACTION_REFUSE, "Prompt injection in any part of the request refuses it"),
    FixedOutcome(FIXED_FINAL_BYTES, ACTION_REFUSE, "The final request still carrying prompt injection or a refuse, "
                 "mask or mask_reroute kind, a reroute kind not sent to the governance alias, or with its budget "
                 "spent, is refused: nothing is sent"),
)
_MODEL_OUTPUT_FIXED = (
    FixedOutcome(FIXED_UNFINISHED, ACTION_WITHHOLD, "A reply part the detectors could not finish examining is "
                                                    "withheld"),
    FixedOutcome(FIXED_UNREADABLE, ACTION_REFUSE, "An answer or reasoning of a shape the platform cannot read is "
                                                  "refused"),
    FixedOutcome(FIXED_PROMPT_INJECTION, ACTION_NONE, "Not checked in a reply (it goes back to the user)"),
)
#: ``content_routing.tool_results``: unfinished parts are withheld, a result that finishes only part by part is
#: blocked; injection is the model entrance's (the result is checked where it next reaches a model).
_TOOL_RESULTS_FIXED = (
    FixedOutcome(FIXED_UNFINISHED, ACTION_WITHHOLD, "A part the detectors could not finish examining is withheld; a "
                                                    "result whose parts do not finish together is blocked"),
    FixedOutcome(FIXED_PROMPT_INJECTION, ACTION_NONE, "Checked where the result next reaches a model"),
)
#: ``model_gateway.inbound.service`` (the body) and ``content_routing.gateway.fixed_refusal``: the request is refused.
_GATEWAY_FIXED = (
    FixedOutcome(FIXED_UNFINISHED, ACTION_REFUSE, "A request too large or dense to check before its deadline is "
                                                  "refused"),
    FixedOutcome(FIXED_UNREADABLE, ACTION_REFUSE, "A body that is not valid JSON, or over the size limit, is refused"),
    FixedOutcome(FIXED_PROMPT_INJECTION, ACTION_REFUSE, "Prompt injection in the newest turn or a tool result refuses "
                                                        "the request"),
    FixedOutcome(FIXED_FINAL_BYTES, ACTION_REFUSE, "A masked request that still carries a mask kind is refused: "
                                                   "nothing is sent"),
)
#: ``security_analyzer.content_command``.
_COMMANDS_FIXED = (
    FixedOutcome(FIXED_UNFINISHED, ACTION_REVIEW, "A command the detectors could not finish examining is sent for "
                                                  "review"),
    FixedOutcome(FIXED_PROMPT_INJECTION, ACTION_NONE, "Not checked in a command (a model-input concern)"),
)


#: What ``reroute`` / ``mask_reroute`` does at a point: reroute, mask instead (the reply direction: the text goes
#: back to the user, not to another model), or nothing sensible applies (``content_route_unavailable``).
REROUTE_APPLIED = "reroute"
REROUTE_AS_MASK = "mask"
REROUTE_UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class PointCondition:
    where: str
    label: str
    kinds: frozenset[str]
    action: str
    reason: str
    when: frozenset[str] = frozenset(ACTIONS)


@dataclass(frozen=True, slots=True)
class EnforcementPoint:
    id: str
    label: str
    surface: str
    reroute: str
    kinds: frozenset[str] = KIND_IDS
    supported: frozenset[str] = frozenset(ACTIONS)
    deferred: frozenset[str] = frozenset()
    applied_as: Mapping[str, tuple[str, str]] = field(default_factory=dict)
    conditions: tuple[PointCondition, ...] = ()
    fixed: tuple[FixedOutcome, ...] = ()



#: ``content_security.enforcement_call``: a ``refuse`` kind refuses the call in the newest turn and the offered tool
#: definitions; in earlier turns the client re-sends it is masked instead (it never leaves, the conversation goes on).
OLDER_HISTORY_MASKED = PointCondition(
    "older_history", "Earlier turns and replayed tool-call arguments re-sent with the request", KIND_IDS,
    ACTION_MASK, REASON_OLDER_HISTORY_MASKED, frozenset({ACTION_REFUSE}))

POINTS: tuple[EnforcementPoint, ...] = (
    EnforcementPoint(POINT_MODEL_CALL, "Platform model calls on the governed gateway route", SURFACE_PLATFORM,
                     REROUTE_APPLIED, conditions=(OLDER_HISTORY_MASKED,), fixed=_MODEL_CALL_FIXED),
    EnforcementPoint(POINT_MODEL_CALL_DIRECT, "Platform model calls through a direct provider driver",
                     SURFACE_PLATFORM, REROUTE_UNAVAILABLE, conditions=(OLDER_HISTORY_MASKED,),
                     fixed=_MODEL_CALL_FIXED),
    EnforcementPoint(POINT_MODEL_OUTPUT, "Model replies (answer and reasoning)", SURFACE_PLATFORM, REROUTE_AS_MASK,
                     fixed=_MODEL_OUTPUT_FIXED),
    EnforcementPoint(POINT_TOOL_RESULTS, "Tool results (refused here; the rest where they reach a model)",
                     SURFACE_PLATFORM, REROUTE_APPLIED, deferred=MASKING | REROUTING, fixed=_TOOL_RESULTS_FIXED),
    # ``content_security.enforcement_inbound``: a Claude subscription seat reroutes to the company route.
    EnforcementPoint(POINT_GATEWAY_MESSAGES, "External coding agents on the Anthropic route (the whole request)",
                     SURFACE_GATEWAY, REROUTE_APPLIED, conditions=(OLDER_HISTORY_MASKED,), fixed=_GATEWAY_FIXED),
    EnforcementPoint(POINT_GATEWAY_RESPONSES, "Codex on the Responses route (the whole request)", SURFACE_GATEWAY,
                     REROUTE_APPLIED, conditions=(OLDER_HISTORY_MASKED,), fixed=_GATEWAY_FIXED),
    # The ChatGPT backend serves only the person's own login: there is no governed alias to send it to.
    EnforcementPoint(POINT_CODEX_SEAT, "Codex on a ChatGPT seat", SURFACE_GATEWAY, REROUTE_UNAVAILABLE,
                     conditions=(OLDER_HISTORY_MASKED,), fixed=_GATEWAY_FIXED),
    # ``security_analyzer.content_command``: a command cannot be masked or rerouted.
    EnforcementPoint(POINT_COMMANDS, "Commands (Command safety)", SURFACE_COMMANDS, REROUTE_UNAVAILABLE,
                     COMMAND_KINDS, fixed=_COMMANDS_FIXED, applied_as={
                         ACTION_MASK: (ACTION_REVIEW, REASON_COMMAND_REVIEW),
                         ACTION_REFUSE: (ACTION_DENY, REASON_COMMAND_DENIED),
                         ACTION_REROUTE: (ACTION_DENY, REASON_ROUTE_UNAVAILABLE),
                         ACTION_MASK_REROUTE: (ACTION_DENY, REASON_ROUTE_UNAVAILABLE)}),
)


__all__ = [
    "ACTION_WITHHOLD",
    "FIXED_FINAL_BYTES",
    "FIXED_PROMPT_INJECTION",
    "FIXED_UNFINISHED",
    "FIXED_UNREADABLE",
    "OLDER_HISTORY_MASKED",
    "POINTS",
    "REROUTE_APPLIED",
    "REROUTE_AS_MASK",
    "REROUTE_UNAVAILABLE",
    "EnforcementPoint",
    "FixedOutcome",
    "PointCondition",
]
