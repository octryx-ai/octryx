"""The ``ToolCall.parameters`` and ``ToolCall.result`` shapes stored on a gateway session."""

from typing import Any, Literal, NotRequired, TypedDict

GatewaySource = Literal["model_gateway"]
HookSource = Literal["client_hook"]
ExecutionOutcome = Literal["succeeded", "failed"]


class ExecutionEvidence(TypedDict):
    outcome: ExecutionOutcome
    source: HookSource


class ShellRead(TypedDict):
    read_tool: str
    in_root: bool
    path: str


class ShellReadTarget(ShellRead):
    tool: Literal["Bash"]


class NativeReadTarget(TypedDict):
    tool: Literal["Read", "Grep", "Glob", "LS"]
    in_root: bool
    path: str


class StoredTestReport(TypedDict):
    format: Literal["junit"]
    path: str
    junit_xml: str
    files: NotRequired[list[str]]


class ExecCallRecord(TypedDict):
    tool: str
    input: Any
    cwd: str


# The execution hook may create the row before the model gateway does, with only its own keys.
class GatewayToolCallParameters(TypedDict):
    source: GatewaySource
    tool_use_id: str
    block_index: NotRequired[int]
    input: NotRequired[Any]
    command: NotRequired[str]
    executed: NotRequired[ExecutionEvidence]
    agent_id: NotRequired[str]
    read_target: NotRequired[NativeReadTarget | ShellReadTarget]
    test_report: NotRequired[StoredTestReport]
    exec_call: NotRequired[ExecCallRecord]


class GatewayToolCallResult(TypedDict):
    is_error: bool
    excerpt: str


class HostedSearchParameters(TypedDict):
    source: GatewaySource
    hosted: Literal[True]
    item_id: str
    action: str
    target: str


class HostedSearchResult(TypedDict):
    is_error: bool
    status: str


class HookDenialParameters(TypedDict):
    source: HookSource
    tool_use_id: str | None
    rule_id: str | None
    reason: str
    input: dict[str, str]
    command: NotRequired[str]


class HookDenialResult(TypedDict):
    decision: str
    state: str
    reason: str
    remedy: NotRequired[dict[str, Any]]


class ConfirmationTicketParameters(TypedDict):
    source: HookSource
    approval_id: str
    tool_use_id: str
    nonce: str
    ticket_sha256: str
    expires_at: str


class DecisionTicketParameters(TypedDict):
    source: HookSource
    run_id: str
    action: str
    payload_hash: str
    arguments_digest: str
    tool_use_id: str
    nonce: str
    ticket_sha256: str
    expires_at: str


class TicketAskResult(TypedDict):
    decision: Literal["ask"]
    message: NotRequired[str]


__all__ = [
    "ConfirmationTicketParameters", "DecisionTicketParameters", "ExecCallRecord", "ExecutionEvidence",
    "ExecutionOutcome", "GatewaySource", "GatewayToolCallParameters", "GatewayToolCallResult", "HookDenialParameters",
    "HookDenialResult", "HookSource", "HostedSearchParameters", "HostedSearchResult", "NativeReadTarget",
    "ShellRead", "ShellReadTarget", "StoredTestReport", "TicketAskResult",
]
