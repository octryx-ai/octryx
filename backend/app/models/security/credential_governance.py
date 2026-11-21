"""Credential and Secret Governance models.

Adds two tables on top of the existing `stored_secrets` / `secret_rotation_log` foundation:

  secret_scope_bindings     — least-privilege scope: which entity (agent, flow,
                              connector, mcp_server, domain_pack) may access which
                              secret, and with what permissions.

  secret_access_audit_log   — immutable record of every secret access event:
                              read, bind, revoke, export_scrub, rotation.

Design principles:
  - Secrets are never exported or included in traces by default.
  - Every access is audited: who, what entity, what action, when.
  - Scope bindings are least-privilege: READ_ONLY unless explicitly granted EXECUTE.
  - Revocation is soft (is_active=False) to preserve audit trail.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from ...db import Base
from ...time_utils import utc_now


def _uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Entity type constants (which types may hold a scope binding)
# ---------------------------------------------------------------------------

SCOPE_ENTITY_AGENT = "agent"
SCOPE_ENTITY_FLOW = "flow"
SCOPE_ENTITY_CONNECTOR = "connector"
SCOPE_ENTITY_MCP_SERVER = "mcp_server"
SCOPE_ENTITY_DOMAIN_PACK = "domain_pack"

SCOPE_ENTITY_TYPES = {
    SCOPE_ENTITY_AGENT,
    SCOPE_ENTITY_FLOW,
    SCOPE_ENTITY_CONNECTOR,
    SCOPE_ENTITY_MCP_SERVER,
    SCOPE_ENTITY_DOMAIN_PACK,
}

# ---------------------------------------------------------------------------
# Permission level constants
# ---------------------------------------------------------------------------

SCOPE_PERM_READ_ONLY = "read_only"      # may read secret value at runtime
SCOPE_PERM_EXECUTE = "execute"           # read + may use secret to authenticate

SCOPE_PERMISSION_LEVELS = {SCOPE_PERM_READ_ONLY, SCOPE_PERM_EXECUTE}

# ---------------------------------------------------------------------------
# Audit action constants
# ---------------------------------------------------------------------------

AUDIT_ACTION_READ = "read"
AUDIT_ACTION_BIND = "bind"
AUDIT_ACTION_REVOKE = "revoke"
AUDIT_ACTION_EXPORT_SCRUB = "export_scrub"
AUDIT_ACTION_ROTATE = "rotate"
AUDIT_ACTION_DENIED = "denied"

AUDIT_ACTIONS = {
    AUDIT_ACTION_READ,
    AUDIT_ACTION_BIND,
    AUDIT_ACTION_REVOKE,
    AUDIT_ACTION_EXPORT_SCRUB,
    AUDIT_ACTION_ROTATE,
    AUDIT_ACTION_DENIED,
}


class SecretScopeBinding(Base):
    """Least-privilege binding: allows a specific entity to access a specific secret.

    One row per (secret_id, entity_type, entity_id) tuple. Deactivating a binding
    revokes access without deleting the audit trail.

    A secret with no active scope bindings is accessible only to admins
    (via direct DB queries in the admin panel).
    """

    __tablename__ = "secret_scope_bindings"
    __table_args__ = (
        UniqueConstraint(
            "secret_id", "entity_type", "entity_id",
            name="uq_secret_scope_binding",
        ),
        Index("ix_secret_scope_bindings_secret_entity", "secret_id", "entity_type"),
        Index("ix_secret_scope_bindings_active", "is_active"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    secret_id = Column(
        String(36),
        ForeignKey("stored_secrets.id"),
        nullable=False,
        index=True,
    )
    # Type of entity that holds the binding
    entity_type = Column(String(30), nullable=False, index=True)
    # Opaque entity ID (agent_definition.id, flow_definition.id, etc.)
    entity_id = Column(String(36), nullable=False, index=True)
    # Human-readable label for admin display
    entity_label = Column(String(200), nullable=False, default="")
    # Permission level: read_only | execute
    permission = Column(String(20), nullable=False, default=SCOPE_PERM_READ_ONLY)
    # Notes on why this binding was created
    reason = Column(Text, default="")
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)
    revoked_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    revoked_at = Column(DateTime, nullable=True)

    secret = relationship("StoredSecret")
    creator = relationship("User", foreign_keys=[created_by])
    revoker = relationship("User", foreign_keys=[revoked_by])


class SecretAccessAuditLog(Base):
    """Immutable record of every secret governance event.

    Never updated after insert. Provides compliance-grade audit trail for:
      - who accessed a secret at runtime (read)
      - binding creation (bind)
      - binding revocation (revoke)
      - secret was scrubbed from an export (export_scrub)
      - secret was rotated (rotate)
      - access was denied due to missing/inactive scope binding (denied)
    """

    __tablename__ = "secret_access_audit_log"
    __table_args__ = (
        Index("ix_secret_access_audit_log_secret_action", "secret_id", "action"),
        Index("ix_secret_access_audit_log_entity", "entity_type", "entity_id"),
        Index("ix_secret_access_audit_log_created", "created_at"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    secret_id = Column(
        String(36),
        ForeignKey("stored_secrets.id"),
        nullable=True,   # nullable: action may be about a deleted secret
        index=True,
    )
    action = Column(String(30), nullable=False, index=True)
    # Entity that triggered the action (may be None for admin actions)
    entity_type = Column(String(30), nullable=True)
    entity_id = Column(String(36), nullable=True)
    # User who triggered the action (may be None for system-initiated events)
    actor_user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    # Outcome: success | denied | scrubbed
    outcome = Column(String(20), nullable=False, default="success", index=True)
    # Optional structured context
    context_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)

    actor = relationship("User")
