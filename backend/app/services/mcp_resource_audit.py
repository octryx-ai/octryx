"""Redaction-safe audit evidence for governed MCP resource and prompt access.

Every governed request gets exactly one ``AuditLog`` row carrying its **final**
outcome, so an operator can answer "who reached which resource, under which
workspace, and what actually happened" without reading the tool trace.

Final is the load-bearing word, and it means *after the fact*, not *after
policy*. An item the binding admits may still be held by the approval gate, and a
request the approval gate admits may still never reach the remote server — the
transport can be unreachable, ``auto_connect`` can fail, or the pre-transport
re-check can deny on a policy change that landed in between. None of those is an
execution. So no writer on this surface records ``executed_allowed`` before the
remote call has actually been attempted: the governed tool records the outcome it
observed, and every other path records the denial or the hold it produced.
Discovery is audited too, including a successful or empty listing, because "this
workspace saw nothing" is a governance fact and an unaudited empty success cannot
be distinguished later from discovery that never ran.

What a row may carry is deliberately narrow:

- the catalog kind, the canonical server name, and the opaque catalog identity (a
  URI digest for resources, the prompt name for prompts) plus the binding key it
  belongs to;
- the closed decision state, the public denial reason, the risk, and the scopes;
- the workspace, session, and dispatch path.

What it must never carry: a resource URI in *any* form — raw or redacted, since a
redacted URI still names an internal host, a bucket, or a database — prompt or
tool arguments, resource or prompt content, MCP connection configuration, or
provider exception text. The
decision object cannot produce any of those (``McpResourceDecision.audit_metadata``
is the only source), which is what keeps this safe by construction rather than by
review.

``AuditLog.user_id`` is ``nullable=False``, so a context without a user id is not
auditable here; such a context also cannot pass the approval gate, and its denial
is still recorded in the tool trace by ``annotate_tool_result_payload``.

Two rules make a failed write survivable, because this writer runs inside the
caller's transaction and the caller still has work to finish:

- **the insert is isolated in a SAVEPOINT.** ``AuditLog.resource_id`` is
  ``String(200)``, and on PostgreSQL an over-width value — or any other statement
  error — aborts the *whole* transaction, so a swallowed exception would take the
  turn's own writes down with it. A nested transaction confines the failure to the
  audit row; the caller's transaction stays usable. ``resource_id`` is bounded by
  ``audit_resource_reference`` as well, so the width case does not arise in the
  first place;
- **a failure is never silent.** The writer answers ``False``, logs the closed
  state and outcome at error level, and the governed paths surface
  ``governance_audit: "unavailable"`` on the result, so a request whose evidence
  was lost cannot be read back as one that was audited.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AuditLog
from .mcp_resource_decision import McpResourceDecision
from .mcp_resource_identity import MAX_AUDIT_RESOURCE_ID_CHARS, audit_resource_reference

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
    """Add one governance row; never raise, and never carry free error text.

    The insert runs in its own SAVEPOINT so a statement error cannot abort the
    caller's transaction, and a failure is reported rather than swallowed.
    """
    normalized_user_id = str(user_id or "").strip()
    if db is None or not normalized_user_id:
        return False
    try:
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
    """Write the one final-outcome row for one governed read or get.

    ``outcome`` is passed in rather than derived, because only the caller knows
    what actually happened: the policy answer alone cannot tell an execution from
    a hold or from a transport failure. It must come from
    ``MCP_RESOURCE_AUDIT_OUTCOMES``; anything else is recorded as ``denied``,
    which is the fail-closed reading of an outcome this module does not know.

    Never raises: an audit failure must not turn a denial into an exception, and
    must not turn an allow into a failure either. The bounded reason is logged
    from the closed state vocabulary, never from a raw error text.
    """
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
    """Write the one final-outcome row for one governed discovery call.

    A successful listing is audited exactly like an empty one: both are decisions
    this workspace's catalog made, and only the counts differ. No item identity,
    URI, or argument is recorded — the catalog already holds what was visible.
    """
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
