"""Per-item access policy for mirrored MCP resources and prompts.

Three MCP gates exist, in this order:

1. ``services/mcp_access_policy.py`` — may this project talk to the *server* at all;
2. ``services/mcp_capability_policy.py`` — may it dispatch one mirrored *tool*;
3. this module — may it discover, read, or render one mirrored *resource* or *prompt*.

Resources and prompts are a narrower surface than tools: a single ``file://``,
``db://``, or internal ``https://`` resource can expose far more than a server's
tools do, and a prompt is model-visible instruction text. They therefore get
their own catalog kinds, ``CapabilityType(kind="mcp_resource")`` and
``CapabilityType(kind="mcp_prompt")``, each with a disabled-by-default
``WorkspaceCapabilityBinding``.

Decision rules, in order:

- no user id, no database session, or no resolvable workspace → ``unverifiable``
  → deny. A context with no user has no approver and no auditable identity, so an
  allow there would be an unaudited allow whatever the item's risk;
- no mirrored binding → deny (``not_mirrored``);
- a binding exists → allow only when nothing it carries is credential-bearing
  (neither its governed URI nor any provider-controlled metadata field), its
  capability type is still active, the server still advertises it, its contract
  is not waiting for a drift review and still matches the digest this workspace
  approved, the binding is visible and enabled, and its ``intent_scopes`` (when
  set) match the execution scope.

Like the tool path (``mcp_capability_policy``), absence denies: an unknown
resource must fail before transport, so this catalog is strictly
deny-by-default.
Discovery names the missing mirror explicitly instead of returning an empty
success.

Model-visible denial reasons are a closed, uniform family per kind. Unknown,
disabled, hidden, retired, drifted, and out-of-scope items all produce the same
payload and the same message, so an out-of-scope item is indistinguishable from
one that does not exist. The precise internal state reaches the audit record
only.

Risk and scope are metadata: ``policy_config["risk"]`` and ``intent_scopes`` on
the binding. Nothing is ever inferred from a URI, a name, or a description.
"""

from __future__ import annotations

from typing import Any

from .mcp_capability_policy import normalized_mcp_server_name
from .mcp_resource_contract import mcp_resource_contract_credential_finding
from .mcp_resource_credentials import mcp_resource_uri_credential_finding
from .mcp_resource_decision import McpResourceDecision
from .mcp_resource_identity import (
    DEFAULT_MCP_RESOURCE_RISK,
    HIDDEN_BINDING_STATUS,
    LIFECYCLE_MISSING,
    MCP_RESOURCE_BINDING_KINDS,
    MCP_RESOURCE_REVIEW_STATE_NEEDS_REVIEW,
    normalized_scope_tags,
)
from .mcp_resource_index import McpResourceIndex, MirroredMcpResourceEntry
from .mcp_resource_states import (
    STATE_ALLOWED,
    STATE_CONTRACT_DRIFT,
    STATE_CREDENTIAL_METADATA,
    STATE_CREDENTIAL_URI,
    STATE_DISABLED,
    STATE_HIDDEN,
    STATE_MISSING_IDENTITY,
    STATE_MISSING_WORKSPACE,
    STATE_NOT_MIRRORED,
    STATE_OUT_OF_SCOPE,
    STATE_RETIRED,
    STATE_UPSTREAM_MISSING,
    UNVERIFIABLE_STATES,
)


def _governed_identity(entry: MirroredMcpResourceEntry | None) -> str:
    """Return the identity this decision may carry, or ``""`` when it may not.

    A binding that still holds a credential-bearing URI or credential-bearing
    provider metadata always denies, so the decision drops that URI here. The
    decision object is then credential-free by construction, and neither the
    transport nor the audit record can be handed one by a consumer that forgot to
    check. The audit record never carries it in any case
    (``McpResourceDecision.audit_metadata``); only the transport does.
    """
    if entry is None or mcp_resource_uri_credential_finding(entry.governed_identity):
        return ""
    if mcp_resource_contract_credential_finding(entry.contract):
        return ""
    return entry.governed_identity


def _decision(
    *,
    kind: str,
    server_name: str,
    identity: str,
    allowed: bool,
    state: str,
    matched_rule: str,
    entry: MirroredMcpResourceEntry | None = None,
) -> McpResourceDecision:
    return McpResourceDecision(
        kind=str(kind or "").strip(),
        server_name=normalized_mcp_server_name(server_name),
        identity=str(identity or "").strip(),
        allowed=allowed,
        state=state,
        risk=entry.risk if entry is not None else DEFAULT_MCP_RESOURCE_RISK,
        matched_rule=matched_rule,
        governed_identity=_governed_identity(entry),
        scopes=entry.scopes if entry is not None else (),
        binding_key=entry.binding_key if entry is not None else "",
    )


def unverifiable_mcp_resource_decision(
    *,
    kind: str,
    server_name: str,
    identity: str = "",
    state: str = STATE_MISSING_WORKSPACE,
) -> McpResourceDecision:
    """Missing database or unresolvable workspace context denies."""
    return _decision(
        kind=kind,
        server_name=server_name,
        identity=identity,
        allowed=False,
        state=state if state in UNVERIFIABLE_STATES else STATE_MISSING_WORKSPACE,
        matched_rule="unverifiable_context",
    )


def denied_mcp_resource_decision(
    *,
    kind: str,
    server_name: str,
    identity: str,
    state: str,
    matched_rule: str,
) -> McpResourceDecision:
    """Deny for a reason the catalog index cannot express.

    Used for the server-identity states, which are decided against the configured
    MCP servers rather than against a workspace binding. The public reason is the
    same uniform one every other denial produces, so the caller learns nothing
    about *why*; only the audit row carries the state.
    """
    return _decision(
        kind=kind,
        server_name=server_name,
        identity=identity,
        allowed=False,
        state=state,
        matched_rule=matched_rule,
    )


def decide_mcp_resource(
    index: McpResourceIndex,
    *,
    kind: str,
    server_name: str,
    identity: str,
    scope_tags: frozenset[str] = frozenset(),
) -> McpResourceDecision:
    """Return the one decision every resource/prompt path evaluates."""
    normalized_kind = str(kind or "").strip()
    normalized_server = normalized_mcp_server_name(server_name)
    normalized_identity = str(identity or "").strip()
    if not normalized_server or not normalized_identity or normalized_kind not in MCP_RESOURCE_BINDING_KINDS:
        return _decision(
            kind=normalized_kind,
            server_name=normalized_server,
            identity=normalized_identity,
            allowed=False,
            state=STATE_MISSING_IDENTITY,
            matched_rule="invalid_request",
        )

    entry = index.get(normalized_kind, normalized_server, normalized_identity)
    if entry is None:
        # Absence denies: an unknown item must fail before transport, and that is also what makes
        # an unknown item indistinguishable from an out-of-scope one.
        return _decision(
            kind=normalized_kind,
            server_name=normalized_server,
            identity=normalized_identity,
            allowed=False,
            state=STATE_NOT_MIRRORED,
            matched_rule="workspace_catalog_absent",
        )

    denial = {
        "kind": normalized_kind,
        "server_name": normalized_server,
        "identity": normalized_identity,
        "entry": entry,
        "allowed": False,
    }
    denied = _entry_denial(entry, denial, scope_tags)
    if denied is not None:
        return denied
    return _decision(
        kind=normalized_kind,
        server_name=normalized_server,
        identity=normalized_identity,
        entry=entry,
        allowed=True,
        state=STATE_ALLOWED,
        matched_rule="workspace_resource_binding",
    )


def _entry_denial(
    entry: MirroredMcpResourceEntry, denial: dict[str, Any], scope_tags: frozenset[str]
) -> McpResourceDecision | None:
    """The first rule a mirrored binding fails, as a denial; ``None`` when it passes every rule."""
    if mcp_resource_uri_credential_finding(entry.governed_identity):
        # A credential-bearing identity must fail before transport rather than be
        # forwarded in a redacted form. The mirror refuses to write one; the stored identity is judged again by the
        # detector in force at use time.
        return _decision(**denial, state=STATE_CREDENTIAL_URI, matched_rule="credential_bearing_identity")
    if mcp_resource_contract_credential_finding(entry.contract):
        # Same rule for every other provider-controlled field. A name, a
        # description, a media type, or a prompt argument description that
        # carries a credential denies rather than being published to the model,
        # the admin catalog, or a mirror report.
        return _decision(**denial, state=STATE_CREDENTIAL_METADATA, matched_rule="credential_bearing_metadata")
    if not entry.capability_type_active:
        return _decision(**denial, state=STATE_RETIRED, matched_rule="capability_type_lifecycle")
    if entry.lifecycle_state == LIFECYCLE_MISSING:
        # The server stopped advertising this item. It stays in the catalog as
        # governance history, but it is not executable until it reappears and an
        # admin reviews the re-appearance.
        return _decision(**denial, state=STATE_UPSTREAM_MISSING, matched_rule="upstream_item_missing")
    if entry.review_state == MCP_RESOURCE_REVIEW_STATE_NEEDS_REVIEW:
        return _decision(**denial, state=STATE_CONTRACT_DRIFT, matched_rule="contract_drift_needs_review")
    if entry.approved_contract_digest != entry.catalog_contract_digest:
        # Workspace isolation for drift: the shared catalog contract moved away
        # from the one this workspace approved, so *this* workspace denies even
        # though the re-mirror that moved it ran somewhere else.
        return _decision(**denial, state=STATE_CONTRACT_DRIFT, matched_rule="contract_digest_mismatch")
    if entry.binding_status == HIDDEN_BINDING_STATUS:
        return _decision(**denial, state=STATE_HIDDEN, matched_rule="binding_status_hidden")
    if not entry.is_enabled:
        return _decision(**denial, state=STATE_DISABLED, matched_rule="binding_disabled")
    if entry.scopes and not (normalized_scope_tags(entry.scopes) & scope_tags):
        # Scope is metadata: an empty ``intent_scopes`` is unrestricted, a
        # non-empty one restricts the item to those execution scopes.
        return _decision(**denial, state=STATE_OUT_OF_SCOPE, matched_rule="intent_scope_mismatch")
    return None


__all__ = [
    "decide_mcp_resource",
    "denied_mcp_resource_decision",
    "unverifiable_mcp_resource_decision",
]
