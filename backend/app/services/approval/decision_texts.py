"""Decision records (Observability -> Decisions) in plain words: their rule codes and subjects."""

from __future__ import annotations

import re

from .tool_texts import (
    _APPROVAL_ACTION,
    RULE_CHAT_CONNECTOR_WRITE,
    RULE_CHAT_PLATFORM_WRITE,
    RULE_DEVICE_EXTERNAL_WRITE,
    RULE_OUTBOUND_MESSAGE,
    RULE_REQUIRE_FOR_RISKS,
    RULE_REQUIRE_FOR_TOOLS,
    RULE_UNATTENDED_EXTERNAL_WRITE,
    rule_text,
    tool_title,
)

# Decision records (Observability -> Decisions) store the gate's codes as their rule; these are the same codes in words.
# A turn gate's rule is "<gate>: <status>" (``decisions.gates``), a dispatch refusal's the refusing policy
# (``decisions.tool_dispatch``). Rules already written in words ("approval rule: ...", "guardrail rule: ...") stay.
_TURN_GATES = {"execution_gate": "The execution check", "runtime_readiness": "The runtime readiness check"}
_TURN_STATUSES = {
    "needs_configuration": "stopped the turn because something it needs is not set up",
    "needs_clarification": "stopped the turn until the request is clarified",
    "needs_approval": "held the turn until a person approves it",
    "needs_confirmation": "held the turn until a person confirms it",
    "denied": "did not allow the turn",
}
_POLICY_TEXTS = {
    "project_tool_policy": "The Workspace's tool policy does not allow this tool",
    "project_tool_policy_explicit_allow": "The Workspace allows only the tools it lists, and this one is not listed",
    "project_read_only_tools": "The Workspace allows only tools that read",
    "default_platform_policy": "The platform's default tool policy does not allow this tool",
    "tool_governance_metadata": "The tool has no governance description, so it is blocked until an admin describes it",
    "tool_name": "The tool name is not valid",
    "mcp_access_policy": "The MCP access policy does not allow this server or tool",
    "mcp_capability_policy": "This MCP capability is not granted",
    "connector_activation": "The connector is not activated in this Workspace",
    "rest_api_grants": "The REST API's grants do not allow this call",
    "connection_routing": "No connection serves the scope of this call",
    "workflow_capability_context": "What this run may do does not include this call",
    # The gate has one rule (coding_dispatch_gates): no delivery before the approved verification contract is proven.
    "coding_delivery_gate": ("The coding delivery rules require a step before this call: the approved verification "
                             "checks must pass in this session first"),
    "circuit_breaker": "Paused after repeated failures of this system",
    "chat_write_plan": "A write from the chat needs a confirmed write plan first",
    "tool_approval_gate": "This call needs approval",
    "denied_by_policy": "A policy does not allow this call",
    "denied_by_tool_surface": "The run's fixed tool set does not include this tool",
}
_RESOURCE_TOOL = re.compile(r"^Tool (?P<name>\S+)$")


def decision_rule_text(rule: str) -> str:
    """A decision record's rule in words; a rule that is not a known code is returned as stored."""
    code = str(rule or "").strip()
    gate, _, status = code.partition(": ")
    if gate in _TURN_GATES and (not status or status in _TURN_STATUSES):
        return f"{_TURN_GATES[gate]} {_TURN_STATUSES.get(status, 'stopped the turn')}"
    if code in _POLICY_TEXTS:
        return _POLICY_TEXTS[code]
    if code in {RULE_REQUIRE_FOR_TOOLS, RULE_REQUIRE_FOR_RISKS, RULE_UNATTENDED_EXTERNAL_WRITE,
                RULE_DEVICE_EXTERNAL_WRITE, RULE_CHAT_CONNECTOR_WRITE, RULE_CHAT_PLATFORM_WRITE, RULE_OUTBOUND_MESSAGE}:
        return rule_text(code)
    return code


def decision_what(resource: str) -> str:
    """A decision record's subject in words: "Approve tool execution for x" and "Tool x" read as the tool's title."""
    text = str(resource or "").strip()
    named = _APPROVAL_ACTION.match(text) or _RESOURCE_TOOL.match(text)
    return tool_title(named.group("name")) if named else text

__all__ = ["decision_rule_text", "decision_what"]
