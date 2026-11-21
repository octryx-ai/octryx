"""Identity rules for governed MCP resources and prompts.

Everything here is pure: catalog kinds, catalog and approval keys, the governed
URI form, and the metadata normalizers (the closed state vocabulary lives in
``mcp_resource_states``). No database, no MCP client, no connection
configuration.

``mcp_resource_policy`` owns the index and the decision, ``mcp_resource_contract``
owns the persisted public contract, ``mcp_resource_catalog`` owns the writes, and
``mcp_resource_gate`` owns enforcement. They all agree on identity because they
all get it from here.

Identity never carries a raw URI. A resource is addressed by its *governed* URI —
``redact_secret_text`` applied to the URI the server advertised — and keyed by
``sha256(server \\x00 governed_uri)[:40]``. A URI that embeds a credential is
therefore redacted in the catalog, in discovery, in approvals, and in audit
records; it no longer matches what the remote server serves, so the model cannot
address it at all. That is the intended fail-closed outcome, not an accident.

Server identity comes from ``mcp_capability_policy.normalized_mcp_server_name``,
so all three MCP gates agree on what "the same server" means.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from .mcp_capability_policy import normalized_mcp_server_name
from .mcp_resource_states import STATE_AMBIGUOUS_SERVER, STATE_UNKNOWN_SERVER
from .redaction_policy import redact_secret_text

MCP_RESOURCE_KIND = "mcp_resource"
MCP_PROMPT_KIND = "mcp_prompt"
MCP_RESOURCE_BINDING_KINDS = frozenset({MCP_RESOURCE_KIND, MCP_PROMPT_KIND})
MCP_RESOURCE_POLICY_NAME = "mcp_resource_policy"

MCP_RESOURCE_SOURCE_ENTITY_TYPE = "mcp_server_resource"
MCP_PROMPT_SOURCE_ENTITY_TYPE = "mcp_server_prompt"
MCP_RESOURCE_MIRROR_SOURCE_ENTITY_TYPE = "mcp_server_resource_mirror"
MCP_RESOURCE_MIRROR_SCOPE = "server"

# The four governed bridge tools, named here so the argument, gate, and
# sanitization owners agree on the surface without importing each other.
MCP_RESOURCE_LIST_TOOL = "list_mcp_server_resources"
MCP_RESOURCE_READ_TOOL = "read_mcp_server_resource"
MCP_PROMPT_LIST_TOOL = "list_mcp_server_prompts"
MCP_PROMPT_GET_TOOL = "get_mcp_server_prompt"
MCP_RESOURCE_BRIDGE_TOOLS = frozenset(
    {MCP_RESOURCE_LIST_TOOL, MCP_RESOURCE_READ_TOOL, MCP_PROMPT_LIST_TOOL, MCP_PROMPT_GET_TOOL}
)

MCP_RESOURCE_RISKS = ("read", "write", "admin", "unknown")
DEFAULT_MCP_RESOURCE_RISK = "unknown"
MCP_RESOURCE_REVIEW_STATE_NEEDS_REVIEW = "needs_review"
HIDDEN_BINDING_STATUS = "hidden"

# Upstream lifecycle of one mirrored item, owned by the mirror run. An item the
# server stopped advertising is retired to ``missing`` and stays non-executable;
# a later re-appearance is parked for review rather than silently reactivated.
LIFECYCLE_ACTIVE = "active"
LIFECYCLE_MISSING = "missing"
MCP_RESOURCE_LIFECYCLE_STATES = (LIFECYCLE_ACTIVE, LIFECYCLE_MISSING)

_IDENTITY_DIGEST_CHARS = 40
_IDENTITY_PATTERN = re.compile(r"[0-9a-f]{8,64}")

# A prompt name is model-supplied on the way in and provider-supplied on the way
# into the catalog, and it is the only identity on this surface that is not a
# digest. Both ends are bounded by the persisted identifier columns
# (``capability_types.key`` and ``workspace_capability_bindings.binding_key`` are
# ``String(200)``), so a longer name can never name a mirrored item: refusing it
# denies exactly what looking it up would have denied, and no unbounded string
# reaches a decision, an approval subject, or an audit row.
MAX_MCP_PROMPT_IDENTITY_CHARS = 200
# ``AuditLog.resource_id`` is ``String(200)``. PostgreSQL enforces that width and
# fails the *statement* when it is exceeded, which would abort the transaction
# the caller is still using, so every reference written there is bounded here.
MAX_AUDIT_RESOURCE_ID_CHARS = 200
_AUDIT_UNKNOWN_SERVER_CHARS = 100


def mcp_resource_kind_label(kind: str) -> str:
    """Return the public noun of one catalog kind (``resource`` or ``prompt``)."""
    return "prompt" if str(kind or "").strip() == MCP_PROMPT_KIND else "resource"


def governed_mcp_resource_uri(uri: Any) -> str:
    """Return the only URI form this platform stores, shows, or audits.

    Secret redaction runs first and without truncation: a truncated URI would not
    be addressable, and a credential-bearing URI must stay non-addressable.
    """
    return redact_secret_text(uri)


def mcp_resource_identity_digest(server_name: str, governed_uri: str) -> str:
    """Return the bounded, collision-free identity of one governed resource URI.

    URIs are unbounded while ``capability_types.key`` is ``String(200)``, so the
    variable part of a resource key is a digest. The server is folded into the
    digest input, so the same URI on two servers stays two identities.
    """
    canonical = f"{normalized_mcp_server_name(server_name)}\x00{str(governed_uri or '')}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:_IDENTITY_DIGEST_CHARS]


def mcp_resource_binding_key(server_name: str, identity_digest: str) -> str:
    """Return the catalog key of one mirrored MCP resource."""
    return f"mcp-resource:{normalized_mcp_server_name(server_name)}:{str(identity_digest or '').strip()}"


def mcp_prompt_binding_key(server_name: str, prompt_name: str) -> str:
    """Return the catalog key of one mirrored MCP prompt."""
    return f"mcp-prompt:{normalized_mcp_server_name(server_name)}:{str(prompt_name or '').strip()}"


def mcp_resource_server_marker_key(kind: str, server_name: str) -> str:
    """Return the per-workspace, per-kind mirror-history marker key for a server."""
    return f"mcp-{mcp_resource_kind_label(kind)}-server:{normalized_mcp_server_name(server_name)}"


def mcp_resource_subject_key(kind: str, server_name: str, identity: str) -> str:
    """Return the approval identity shared by dispatch and discovery."""
    noun = mcp_resource_kind_label(kind)
    return f"mcp_{noun}__{normalized_mcp_server_name(server_name)}__{str(identity or '').strip()}"


def normalized_mcp_resource_identity(value: Any) -> str:
    """Return the opaque catalog identity a read request may address, or ``""``.

    The model addresses a resource by the digest discovery published, never by a
    URI, so this accepts exactly that shape. Anything else is not an identity and
    resolves to the empty string, which the decision maps onto the same uniform
    denial an unknown item gets — a malformed value is never echoed or persisted.
    """
    candidate = str(value or "").strip().lower()
    return candidate if _IDENTITY_PATTERN.fullmatch(candidate) else ""


def normalized_mcp_prompt_identity(value: Any) -> str:
    """Return the prompt identity a request may address, or ``""``.

    A prompt is addressed by name, so unlike a resource identity this is not a
    digest and the provider chooses its shape. It is bounded to what the catalog
    can actually key, because a longer name is not a name this platform can ever
    have mirrored. Refusing it here is what keeps an unbounded model-supplied
    string out of the decision, the approval subject, and the audit row; the
    denial is the same uniform one an unknown prompt gets.
    """
    candidate = str(value or "").strip()
    return candidate if 0 < len(candidate) <= MAX_MCP_PROMPT_IDENTITY_CHARS else ""


def audit_resource_reference(*, kind: str, server_name: str, binding_key: str, identity: str) -> str:
    """Return the bounded reference one governed request is audited under.

    A mirrored item is named by its catalog binding key, which the mirror already
    bounded to the catalog columns. Anything else is model-supplied — an unknown
    prompt name, an identity that resolved to nothing — and is projected onto a
    stable opaque digest instead of being written through: ``AuditLog.resource_id``
    is ``String(200)``, and on PostgreSQL an over-width value fails the insert,
    aborts the surrounding transaction, and loses the governance outcome with it.
    The digest is the same one the resource catalog keys on, so two audits of the
    same unknown item still line up.
    """
    catalog_key = str(binding_key or "").strip()
    if catalog_key and len(catalog_key) <= MAX_AUDIT_RESOURCE_ID_CHARS:
        return catalog_key
    noun = mcp_resource_kind_label(kind)
    server = normalized_mcp_server_name(server_name)[:_AUDIT_UNKNOWN_SERVER_CHARS]
    digest = mcp_resource_identity_digest(server_name, str(identity or "").strip())
    return f"mcp-{noun}-unknown:{server}:{digest}"[:MAX_AUDIT_RESOURCE_ID_CHARS]


def canonical_mcp_server_identity(configured_names: Any, server_name: Any) -> tuple[str, str]:
    """Map a canonical server identity onto the one configured name that owns it.

    Governance is keyed by ``normalized_mcp_server_name`` (casefolded), while the
    MCP transport is keyed by the exact configured name. If two configured
    servers casefold to the same identity — ``demo`` and ``DEMO`` — one opaque
    catalog identity would describe two different remote servers, so the request
    must deny rather than pick one. Returns ``(configured_name, "")`` on success
    and ``("", state)`` otherwise.
    """
    canonical = normalized_mcp_server_name(server_name)
    if not canonical:
        return "", STATE_UNKNOWN_SERVER
    matches = sorted(
        {
            str(name or "").strip()
            for name in (configured_names or [])
            if normalized_mcp_server_name(name) == canonical
        }
    )
    if not matches:
        return "", STATE_UNKNOWN_SERVER
    if len(matches) > 1:
        return "", STATE_AMBIGUOUS_SERVER
    return matches[0], ""


def normalized_mcp_resource_risk(value: Any) -> str:
    """Return an explicit, allow-listed risk; unknown metadata stays ``unknown``."""
    risk = str(value or "").strip().lower()
    return risk if risk in MCP_RESOURCE_RISKS else DEFAULT_MCP_RESOURCE_RISK


def normalized_scope_tags(values: Any) -> frozenset[str]:
    """Return the casefolded scope tag set used on both sides of a scope check."""
    if isinstance(values, (list, tuple, set, frozenset)):
        return frozenset({str(value).strip().casefold() for value in values if str(value or "").strip()})
    single = str(values or "").strip().casefold()
    return frozenset({single}) if single else frozenset()


__all__ = [
    "DEFAULT_MCP_RESOURCE_RISK",
    "MAX_AUDIT_RESOURCE_ID_CHARS",
    "MAX_MCP_PROMPT_IDENTITY_CHARS",
    "LIFECYCLE_ACTIVE",
    "LIFECYCLE_MISSING",
    "HIDDEN_BINDING_STATUS",
    "MCP_PROMPT_GET_TOOL",
    "MCP_PROMPT_KIND",
    "MCP_PROMPT_LIST_TOOL",
    "MCP_PROMPT_SOURCE_ENTITY_TYPE",
    "MCP_RESOURCE_BINDING_KINDS",
    "MCP_RESOURCE_BRIDGE_TOOLS",
    "MCP_RESOURCE_KIND",
    "MCP_RESOURCE_LIFECYCLE_STATES",
    "MCP_RESOURCE_LIST_TOOL",
    "MCP_RESOURCE_MIRROR_SCOPE",
    "MCP_RESOURCE_MIRROR_SOURCE_ENTITY_TYPE",
    "MCP_RESOURCE_POLICY_NAME",
    "MCP_RESOURCE_READ_TOOL",
    "MCP_RESOURCE_REVIEW_STATE_NEEDS_REVIEW",
    "MCP_RESOURCE_RISKS",
    "MCP_RESOURCE_SOURCE_ENTITY_TYPE",
    "audit_resource_reference",
    "canonical_mcp_server_identity",
    "governed_mcp_resource_uri",
    "mcp_prompt_binding_key",
    "mcp_resource_binding_key",
    "mcp_resource_identity_digest",
    "mcp_resource_kind_label",
    "mcp_resource_server_marker_key",
    "mcp_resource_subject_key",
    "normalized_mcp_prompt_identity",
    "normalized_mcp_resource_identity",
    "normalized_mcp_resource_risk",
    "normalized_scope_tags",
]
