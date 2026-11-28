"""The ``obligation`` and ``content`` JSON of a content-security decision record: a model call's, a gateway
request's and a tool result's."""

from typing import Any, Literal, NotRequired, TypedDict

from ..content_detection.stored_types import ScanSummary

Action = Literal["refuse", "mask", "reroute", "mask_reroute", "report", "none", "review"]
HandlingSurface = Literal["platform", "gateway", "commands"]
CallSurface = Literal["messages", "message_extras", "replay_arguments", "offered_tools", "request"]
CallPoint = Literal["model_call", "model_call_direct"]
CallStage = Literal["input", "reroute", "cedar", "final_bytes"]
GatewayOutcomeName = Literal["forwarded", "refused", "not_sent"]
GatewayStage = Literal["body", "content", "tool_result_policy", "cedar", "budget", "upstream", "dispatch"]
Released = Literal["unchanged", "masked", "blocked", "kept_by_client"]


class HandlingRecord(TypedDict):
    kind: Literal["content_handling"]
    surface: HandlingSurface
    applied: dict[str, Action]
    informational: list[str]  # the kinds applied as ``report``
    workspace_setting: list[str]  # the kinds a Workspace setting decided, not a shipped default


class AppliedEntry(TypedDict):
    surface: CallSurface
    kind: str
    requested: Action
    applied: Action
    reason: NotRequired[str]


class CallTarget(TypedDict):
    requested: str
    handling: str  # the governance alias a rerouting kind sent the call to
    final: str
    admitted: NotRequired[Literal[False]]


class ModelCallObligation(HandlingRecord):
    point: CallPoint
    requested: dict[str, Action]
    surfaces: list[AppliedEntry]
    outcome: Literal["forwarded", "refused"]
    reason: NotRequired[str]
    stage: NotRequired[CallStage]
    withheld: NotRequired[dict[CallSurface, int]]
    target: NotRequired[CallTarget]
    reported_before: NotRequired[dict[str, str]]  # kind -> the earlier record that reported it
    reply_refused: NotRequired[Literal[True]]
    cedar: NotRequired[dict[str, Any]]


class GatewayObligation(TypedDict):
    kind: Literal["content_handling"]
    surface: Literal["gateway"]
    applied: dict[str, Action]
    informational: list[str]
    workspace_setting: NotRequired[list[str]]  # absent when the request was refused before its plan was read
    requested: dict[str, Action]
    outcome: GatewayOutcomeName
    target: str
    reason: NotRequired[str]
    stage: NotRequired[GatewayStage]
    fixed: NotRequired[Literal["unfinished", "unreadable", "prompt_injection"]]
    cedar: NotRequired[dict[str, Any]]
    upstream_status: NotRequired[str]


class ToolResultObligation(TypedDict):
    point: Literal["tool_result"]
    released: Released
    reason: NotRequired[str]
    cedar: NotRequired[dict[str, Any]]
    withheld: NotRequired[int]
    # The plan's part, absent when the plan acted on no kind found or the examination did not finish.
    kind: NotRequired[Literal["content_handling"]]
    surface: NotRequired[Literal["platform"]]
    applied: NotRequired[dict[str, Action]]
    informational: NotRequired[list[str]]
    workspace_setting: NotRequired[list[str]]
    requested: NotRequired[dict[str, Action]]
    applies_at: NotRequired[dict[str, Literal["model_entrance"]]]


class EmptyContent(TypedDict):
    pass


class UnfinishedContent(TypedDict):
    scanned: Literal[True]
    complete: Literal[False]
    unfinished: Literal[True]


class InjectionCount(TypedDict):
    count: int


class GatewayContent(ScanSummary):
    prompt_injection: NotRequired[InjectionCount]
    masked: NotRequired[int]  # values masked in the sent body
    withheld: NotRequired[int]  # texts withheld because their examination did not finish


# An unfinished examination records only its fixed disposition: no finding-derived count.
GatewayRecordContent = GatewayContent | UnfinishedContent | EmptyContent


class ToolResultContent(TypedDict):
    found: dict[str, int]  # detector -> count


__all__ = [
    "Action",
    "AppliedEntry",
    "CallPoint",
    "CallStage",
    "CallSurface",
    "CallTarget",
    "EmptyContent",
    "GatewayContent",
    "GatewayObligation",
    "GatewayOutcomeName",
    "GatewayRecordContent",
    "GatewayStage",
    "HandlingRecord",
    "HandlingSurface",
    "InjectionCount",
    "ModelCallObligation",
    "Released",
    "ToolResultContent",
    "ToolResultObligation",
    "UnfinishedContent",
]
