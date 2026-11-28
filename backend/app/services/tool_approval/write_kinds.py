"""Which tool calls write to an external system, from a device or from a run no person started."""

from __future__ import annotations

from ...tools.context import ToolContext
from ...tools.definitions import get_tool_definition_metadata
from .rules import ToolApprovalSubject

_DEVICE_WORKERS = frozenset({"mcp_rest_call", "mcp_session"})
# Session MCP writes whose handler confirms them itself (permission prompt ticket, phase class, write scope).
_HANDLER_CONFIRMED_SESSION_WRITES = frozenset({"workflow_select", "workflow_decide", "workflow_action_request",
                                               "knowledge_feedback"})
# Run origins no person started: a schedule, or an Action a webhook or a poll fired.
_UNATTENDED_SOURCES = frozenset({"schedule_definition"})
# Reads that still reach an address the run chooses: a URL or a document source the ticket can name carries data out
# in its path or query (exfiltration), and the fetched page is new untrusted input. In an unattended run they are
# decided by a person like a write, unless the platform allows the tool for unattended runs.
_UNATTENDED_OUTBOUND_FETCH_TOOLS = frozenset({"web_fetch", "ingest_document_source", "fetch_and_save_knowledge"})


def _is_rest_write(tool_name: str) -> bool:
    metadata = get_tool_definition_metadata(str(tool_name or "").strip())
    return metadata.owner_type == "dynamic_rest" and metadata.risk == "write"


def _external_write(tool_name: str, subject: ToolApprovalSubject | None) -> bool:
    # A REST write counts whatever run class its admin declared: the call still lands in another system.
    if subject is not None:
        return str(subject.risk or "").strip().lower() in {"write", "admin", "unknown"}
    from ...tools.capability_requirements import CAPABILITY_DELIVER, tool_required_capability

    if str(tool_name or "").strip() in _UNATTENDED_OUTBOUND_FETCH_TOOLS or _is_rest_write(tool_name):
        return True
    return tool_required_capability(tool_name) == CAPABILITY_DELIVER


def _on_device(context: ToolContext) -> bool:
    state = getattr(context, "run_capability", None)
    return isinstance(state, dict) and str(state.get("worker") or "") in _DEVICE_WORKERS


def device_external_write(tool_name: str, context: ToolContext) -> bool:
    # The device has no approval card: Octryx is the only place a person can see the request.
    state = getattr(context, "run_capability", None)
    if not isinstance(state, dict) or state.get("enforced") is not True:
        return False
    worker = str(state.get("worker") or "")
    if worker == "mcp_session" and str(tool_name or "").strip() not in _HANDLER_CONFIRMED_SESSION_WRITES:
        return get_tool_definition_metadata(str(tool_name or "").strip()).risk in {"write", "admin", "unknown"}
    return worker in _DEVICE_WORKERS and _is_rest_write(tool_name)


def unattended_external_write(tool_name: str, context: ToolContext, subject: ToolApprovalSubject | None) -> bool:
    # No person is in the loop of event-triggered or scheduled runs, so their external writes become proposals.
    state = getattr(context, "run_capability", None)
    if not isinstance(state, dict) or state.get("enforced") is not True:
        return False
    if str(state.get("source") or "") not in _UNATTENDED_SOURCES:
        return False
    return _external_write(tool_name, subject)


def external_write(tool_name: str, subject: ToolApprovalSubject | None = None) -> bool:
    if subject is not None:
        return str(subject.risk or "").strip().lower() in {"write", "admin", "unknown"}
    from ...tools.capability_requirements import CAPABILITY_DELIVER, tool_required_capability

    metadata = get_tool_definition_metadata(str(tool_name or "").strip())
    if metadata.risk in {"write", "admin"} and metadata.owner_type in {"connector", "mcp", "dynamic_database",
                                                                       "dynamic_rest"}:
        return True
    return tool_required_capability(tool_name) == CAPABILITY_DELIVER
