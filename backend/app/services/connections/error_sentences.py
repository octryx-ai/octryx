"""One human sentence per error code a connection's uses record (the detail's ``recent_errors``, ``state_reason``)."""

from __future__ import annotations

SENTENCES: dict[str, str] = {
    # Knowledge sync and intake runs
    "source_unauthorized": "The source system refused the sign-in; test and update the access.",
    "source_not_found": "The source system does not know a configured item.",
    "source_rate_limited": "The source system limited the requests; the next run continues.",
    "source_unavailable": "The source system could not be reached.",
    "source_contract_violation": "The source system answered in an unexpected form.",
    "listing_stalled": "The listing of the source stopped making progress.",
    "scope_not_allowed": "The scope reaches outside what the connection may read.",
    "scope_spans_connections": "The scope is served by more than one connection; split it.",
    "connection_not_configured": "No connection with a target and a credential is configured.",
    "connection_not_configured_for_scope": "No connection serves the configured scope.",
    "own_connection_incomplete": "The Workspace's own connection lacks its URL or credential.",
    "connection_pin_mismatch": "An item resolves to another connection than the linked one.",
    "connection_pin_unknown": "The linked connection does not exist in this Workspace.",
    "connection_disabled": "The connection is disabled.",
    "connection_not_available": "The connection is not available in this Workspace.",
    "connection_use_disabled": "This use of the connection is switched off for the Workspace.",
    "connection_ambiguous": "Two connections serve the same scope; an admin must bind it to one.",
    "egress_refused": "The outbound connection to the source was refused by policy.",
    "parser_not_configured": "No document parser is configured for this source.",
    "connector_paused": "The Knowledge source is paused.",
    "workspace_inactive": "The Workspace is archived or deleted.",
    "jql_invalid": "Jira refused the intake's query (JQL).",
    "jira_sync_failed": "The Jira intake run failed.",
    "intake_connection_unavailable": "The intake's connection is no longer available.",
    "servicenow_connection_not_configured": "The ServiceNow connection lacks its URL or credential.",
    "servicenow_endpoint_not_configured": "No ServiceNow endpoint is configured for a table.",
    "servicenow_endpoint_unreachable": "ServiceNow could not be reached.",
    "servicenow_assignment_groups_not_allowed": "An assignment group lies outside the connection's limit.",
    # Connection checks (``connector_health_log.status``)
    "error": "The connection check failed.",
    "failed": "The connection check failed.",
    "degraded": "The connection check reported a degraded connection.",
    "warning": "The connection check reported a warning.",
    "needs_configuration": "The use needs configuration before it can run.",
}

RUNTIME_SENTENCES: dict[str, str] = {
    "agent_tools": "An agent tool call was refused as unauthenticated (HTTP 401); test and update the access.",
    "knowledge": "A Knowledge sync was refused as unauthenticated; test and update the access.",
    "tickets": "A ticket intake run was refused as unauthenticated (HTTP 401); test and update the access.",
}


def sentence(code: object, use: str) -> str:
    text = " ".join(str(code or "").split())[:80]
    return SENTENCES.get(text) or f"The {use} sync failed ({text or 'unknown'})."


__all__ = ["RUNTIME_SENTENCES", "SENTENCES", "sentence"]
