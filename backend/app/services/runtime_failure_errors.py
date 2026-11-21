"""Typed flow-node failures that ``runtime_failure_taxonomy`` classifies explicitly.

Each type carries only closed facts (a code, a category, the tool result's own category and
``retryable`` flag); the message is never read when a failure is classified or stored.
"""

from __future__ import annotations

import re
from typing import Any

_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

FAILURE_SUMMARIES = {
    "budget_exceeded": "Runtime budget exceeded.",
    "validation_failed": "Validation failed.",
    "human_review_required": "Human review is required.",
    "policy_blocked": "Execution was blocked by policy.",
    "input_contract_error": "Workflow configuration or input contract is invalid.",
    "tool_error": "Tool execution failed.",
    "provider_or_runtime_unavailable": "Runtime provider or execution target is unavailable.",
    "runtime_exception": "Runtime execution failed.",
}


class ToolResultFailedError(ValueError):
    """A flow tool step whose tool returned an error result.

    ``tool_category`` and ``retryable`` come from the tool result's own ``tool_execution``
    metadata, never from the wording of its error text.
    """

    def __init__(self, message: str, *, tool_category: str | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.tool_category = tool_category if _SAFE_CODE.match(tool_category or "") else None
        self.retryable = bool(retryable)


class ToolPolicyDeniedError(ToolResultFailedError):
    """A tool step refused by governance, typed from the tool result's own category.

    The refusal is classified as ``policy_blocked`` from this type, not from the
    wording of the policy decision's message.
    """


class FlowInputContractError(ValueError):
    """The flow definition or a node's input breaks its contract (missing tool, non-object arguments)."""


class ClassifiedFlowError(RuntimeError):
    """A node failure whose category and closed code the raising service decides explicitly.

    The message stays out of every stored record (``error_facts``); ``code`` is a closed
    narrow-charset value and ``category`` one of ``FAILURE_SUMMARIES``.
    """

    def __init__(
        self, code: str, *, category: str, required_action: str = "inspect_trace", retryable: bool = False
    ) -> None:
        super().__init__(code)
        self.code = code
        self.category = category if category in FAILURE_SUMMARIES else "runtime_exception"
        self.required_action = required_action
        self.retryable = retryable


def flow_failure_code(exc: BaseException, default: str = "flow_node_failed") -> str:
    """The closed code a node failure is stored under."""
    return exc.code if isinstance(exc, ClassifiedFlowError) else default


def tool_result_failure_error(result_payload: dict[str, Any]) -> ToolResultFailedError:
    """The exception a failed tool result raises in a flow node."""
    message = str(result_payload.get("error") or "")
    execution = result_payload.get("tool_execution")
    execution = execution if isinstance(execution, dict) else {}
    category = str(execution.get("category") or "")
    retryable = execution.get("retryable") is True
    if category == "denied_by_policy":
        return ToolPolicyDeniedError(message, tool_category=category)
    return ToolResultFailedError(message, tool_category=category or None, retryable=retryable)


__all__ = [
    "FAILURE_SUMMARIES",
    "ClassifiedFlowError",
    "FlowInputContractError",
    "ToolPolicyDeniedError",
    "ToolResultFailedError",
    "flow_failure_code",
    "tool_result_failure_error",
]
