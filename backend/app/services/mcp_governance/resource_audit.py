"""Audit evidence of governed MCP resource and prompt access: one row per request with its final outcome."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog
from .resource_decision import McpResourceDecision
from .resource_identity import MAX_AUDIT_RESOURCE_ID_CHARS, audit_resource_reference

log = logging.getLogger(__name__)

MCP_RESOURCE_AUDIT_ACTION = "mcp_resource_governance"

# Surfaced on a governed result whose evidence could not be written, so a request
# with no audit row is never indistinguishable from one that was audited.
GOVERNANCE_AUDIT_KEY = "governance_audit"
GOVERNANCE_AUDIT_UNAVAILABLE = "unavailable"

DISPATCH_TOOL = "tool_dispatch"
DISPATCH_OUT_OF_BAND = "out_of_band_dispatch"
DISPATCH_DISCOVERY = "discovery"

# Closed outcome vocabulary: what this request finally did, not what policy alone
# would have permitted.
OUTCOME_EXECUTED = "executed_allowed"
OUTCOME_AWAITING_APPROVAL = "allowed_awaiting_approval"
OUTCOME_DENIED = "denied"
# Governance admitted the request and it still did not execute. Kept apart from
# ``denied`` so an operator can tell a policy refusal from a transport problem,
# and apart from ``executed_allowed`` so neither is ever recorded as the other.
OUTCOME_TRANSPORT_UNAVAILABLE = "failed_transport_unavailable"
OUTCOME_TRANSPORT_FAILED = "failed_transport_error"
MCP_RESOURCE_AUDIT_OUTCOMES = (
    OUTCOME_EXECUTED,
    OUTCOME_AWAITING_APPROVAL,
    OUTCOME_DENIED,
    OUTCOME_TRANSPORT_UNAVAILABLE,
    OUTCOME_TRANSPORT_FAILED,
)


async def _write(
    db: AsyncSession | None,
    *,
    user_id: str,
    session_id: str,
    resource_type: str,
    resource_id: str,
    kind_label: str,
    state: str,
    server_name: str,
    details: dict[str, Any],
) -> bool:
    normalized_user_id = str(user_id or "").strip()
    if db is None or not normalized_user_id:
        return False
    try:
        # A SAVEPOINT: on PostgreSQL a failed insert would otherwise abort the caller's transaction.
        async with db.begin_nested():
            db.add(
                AuditLog(
                    user_id=normalized_user_id,
                    session_id=str(session_id or "").strip() or None,
                    action=MCP_RESOURCE_AUDIT_ACTION,
                    resource_id=resource_id[:MAX_AUDIT_RESOURCE_ID_CHARS],
                    resource_type=resource_type,
                    details=details,
                )
            )
    except Exception:
        # Closed facts only: the state and the outcome come from this module's own
        # vocabularies, never from the database error text.
        log.error(
            "Could not record MCP %s governance evidence (state=%s, server=%s, outcome=%s)",
            kind_label,
            state,
            server_name,
            details.get("outcome"),
        )
        return False
    return True


async def record_mcp_resource_decision(
    db: AsyncSession | None,
    *,
    decision: McpResourceDecision,
    workspace_id: str,
    user_id: str,
    session_id: str,
    dispatch: str,
    tool_name: str,
    outcome: str,
) -> bool:
    # An unknown outcome is recorded as ``denied`` (fail closed). Never raises: an audit failure must not turn a denial
    # or an allow into something else.
    normalized_outcome = str(outcome or "").strip()
    if normalized_outcome not in MCP_RESOURCE_AUDIT_OUTCOMES:
        normalized_outcome = OUTCOME_DENIED
    return await _write(
        db,
        user_id=user_id,
        session_id=session_id,
        resource_type=decision.kind,
        # Bounded and stable: the catalog binding key when the item is mirrored,
        # an opaque digest of the model-supplied identity when it is not.
        resource_id=audit_resource_reference(
            kind=decision.kind,
            server_name=decision.server_name,
            binding_key=decision.binding_key,
            identity=decision.identity,
        ),
        kind_label=decision.kind_label,
        state=decision.state,
        server_name=decision.server_name,
        details={
            **decision.audit_metadata(),
            "workspace_id": str(workspace_id or "").strip(),
            "dispatch": str(dispatch or "").strip(),
            "tool_name": str(tool_name or "").strip(),
            "outcome": normalized_outcome,
        },
    )


async def record_mcp_resource_discovery(
    db: AsyncSession | None,
    *,
    kind: str,
    server_name: str,
    workspace_id: str,
    user_id: str,
    session_id: str,
    tool_name: str,
    discovery_state: str,
    visible: int,
    catalog_entries: int,
) -> bool:
    # No item identity, URI or argument is recorded.
    return await _write(
        db,
        user_id=user_id,
        session_id=session_id,
        resource_type=str(kind or "").strip(),
        resource_id=str(server_name or "").strip()[:MAX_AUDIT_RESOURCE_ID_CHARS],
        kind_label=str(kind or "").strip(),
        state=str(discovery_state or "").strip(),
        server_name=str(server_name or "").strip(),
        details={
            "kind": str(kind or "").strip(),
            "server_name": str(server_name or "").strip(),
            "workspace_id": str(workspace_id or "").strip(),
            "dispatch": DISPATCH_DISCOVERY,
            "tool_name": str(tool_name or "").strip(),
            "discovery_state": str(discovery_state or "").strip(),
            "visible": int(visible),
            "catalog_entries": int(catalog_entries),
            "outcome": OUTCOME_EXECUTED,
        },
    )


__all__ = [
    "DISPATCH_DISCOVERY",
    "GOVERNANCE_AUDIT_KEY",
    "GOVERNANCE_AUDIT_UNAVAILABLE",
    "DISPATCH_OUT_OF_BAND",
    "DISPATCH_TOOL",
    "MCP_RESOURCE_AUDIT_ACTION",
    "MCP_RESOURCE_AUDIT_OUTCOMES",
    "OUTCOME_AWAITING_APPROVAL",
    "OUTCOME_DENIED",
    "OUTCOME_EXECUTED",
    "OUTCOME_TRANSPORT_FAILED",
    "OUTCOME_TRANSPORT_UNAVAILABLE",
    "record_mcp_resource_decision",
    "record_mcp_resource_discovery",
]
