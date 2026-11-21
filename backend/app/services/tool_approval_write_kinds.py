"""Which tool calls write to an external system, from a device or from a run no person started."""

from __future__ import annotations

from ..tools.context import ToolContext
from ..tools.definitions import get_tool_definition_metadata
from .tool_approval_rules import ToolApprovalSubject

# Workers that run a call a device asked for over the Knowledge MCP (``run_capability.worker_profiles``).
_DEVICE_WORKERS = frozenset({"mcp_rest_call"})
# Run origins no person started: a schedule, an Action a webhook or a poll fired
# (``run_capability.declared.SOURCE_SCHEDULE_DEFINITION``).
_UNATTENDED_SOURCES = frozenset({"schedule_definition"})
# Reads that still reach an address the run chooses: a URL or a document source the ticket can name carries data out
# in its path or query (exfiltration), and the fetched page is new untrusted input. In an unattended run they are
# decided by a person like a write, unless the platform allows the tool for unattended runs.
_UNATTENDED_OUTBOUND_FETCH_TOOLS = frozenset({"web_fetch", "ingest_document_source", "fetch_and_save_knowledge"})


def _is_rest_write(tool_name: str) -> bool:
    metadata = get_tool_definition_metadata(str(tool_name or "").strip())
    return metadata.owner_type == "dynamic_rest" and metadata.risk == "write"


def _external_write(tool_name: str, subject: ToolApprovalSubject | None) -> bool:
    """A call that reaches an external system and may change it (or, unattended, carry data out through a URL).

    A custom REST write counts whatever run class its admin declared: ``change`` lets a change-class workflow call
    it, but the call still lands in another system."""
    if subject is not None:
        return str(subject.risk or "").strip().lower() in {"write", "admin", "unknown"}
    from ..tools.capability_requirements import CAPABILITY_DELIVER, tool_required_capability

    if str(tool_name or "").strip() in _UNATTENDED_OUTBOUND_FETCH_TOOLS or _is_rest_write(tool_name):
        return True
    return tool_required_capability(tool_name) == CAPABILITY_DELIVER


def _on_device(context: ToolContext) -> bool:
    """The call runs for a device (its MCP worker), not on the Octryx server: the card says where it runs."""
    state = getattr(context, "run_capability", None)
    return isinstance(state, dict) and str(state.get("worker") or "") in _DEVICE_WORKERS


def device_external_write(tool_name: str, context: ToolContext) -> bool:
    """Whether a device's MCP call (``rest_call``) writes: the person decides it in Octryx, per call.

    The device has its own model and no approval card; Octryx is the only place a person can see the request."""
    state = getattr(context, "run_capability", None)
    if not isinstance(state, dict) or state.get("enforced") is not True:
        return False
    return str(state.get("worker") or "") in _DEVICE_WORKERS and _is_rest_write(tool_name)


def unattended_external_write(tool_name: str, context: ToolContext, subject: ToolApprovalSubject | None) -> bool:
    """Whether this call writes to an external system from a run no person started.

    Event-triggered and scheduled runs act on content third parties wrote (a ticket, an alert) and have no person
    in the loop; the platform default policy is empty, so a ``deliver`` Action wrote externally with
    nobody deciding. Such a write is a proposal: the approval it creates is
    the person's decision. Reads and platform-internal writes stay automatic.
    """
    state = getattr(context, "run_capability", None)
    if not isinstance(state, dict) or state.get("enforced") is not True:
        return False
    if str(state.get("source") or "") not in _UNATTENDED_SOURCES:
        return False
    return _external_write(tool_name, subject)


def external_write(tool_name: str, subject: ToolApprovalSubject | None = None) -> bool:
    """A write that lands in another system: a connector, REST, MCP or database write, or a built-in deliver tool."""
    if subject is not None:
        return str(subject.risk or "").strip().lower() in {"write", "admin", "unknown"}
    from ..tools.capability_requirements import CAPABILITY_DELIVER, tool_required_capability

    metadata = get_tool_definition_metadata(str(tool_name or "").strip())
    if metadata.risk in {"write", "admin"} and metadata.owner_type in {"connector", "mcp", "dynamic_database",
                                                                       "dynamic_rest"}:
        return True
    return tool_required_capability(tool_name) == CAPABILITY_DELIVER
