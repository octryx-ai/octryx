"""Normalized OAuth configuration + runtime state for LLM providers.

This 1:1 table (keyed by ``provider_id``) is the sole store of provider OAuth
configuration + runtime state. Stable admin-set configuration keys (``oauth_client_id``,
``oauth_identity_provider_id``, ``google_cloud_project``) and the runtime state
written by the six OAuth flows (login/name/host/source, Copilot token expiry,
Google Personal subscription tier, the Bedrock static credential flag) each get
a typed column. Any genuinely unexpected or volatile key that does not map to a
column is preserved verbatim in ``residual_json`` so no data is ever silently
dropped.

Reads come in two flavours:

* async callers holding an :class:`AsyncSession` use the bridge in
  ``services.provider.oauth_config_bridge`` (explicit ``select``);
* sync callers (serializers, readiness, audit snapshots) use
  :func:`oauth_metadata_from_provider`, which reads the eager-loaded
  ``provider.oauth_config`` relationship. Those call sites eager-load the
  relationship at their query so ``provider.oauth_config`` is populated without
  triggering a lazy load (which would raise ``MissingGreenlet`` under async).
"""

import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import relationship

from ...db import Base
from ...time_utils import utc_now


def uuid_pk():
    return str(uuid.uuid4())


class ProviderOAuthConfig(Base):
    __tablename__ = "provider_oauth_config"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    provider_id = Column(
        String(36),
        ForeignKey("llm_providers.id"),
        nullable=False,
        unique=True,
        index=True,
    )

    # --- Stable configuration (admin-set) ---
    oauth_client_id = Column(String(500), nullable=True)
    oauth_identity_provider_id = Column(String(36), nullable=True)
    google_cloud_project = Column(String(200), nullable=True)

    # --- Runtime state (OAuth-flow-set) ---
    login = Column(String(320), nullable=True)
    name = Column(String(320), nullable=True)
    host = Column(String(500), nullable=True)
    source = Column(String(100), nullable=True)
    token_type = Column(String(40), nullable=True)
    access_token_expires_at = Column(String(64), nullable=True)
    refresh_token_expires_at = Column(String(64), nullable=True)
    subscription_tier = Column(String(100), nullable=True)
    subscription_tier_name = Column(String(200), nullable=True)
    has_paid_tier = Column(Boolean, nullable=True)
    cloudai_project = Column(String(200), nullable=True)
    aws_static_credentials_configured = Column(Boolean, nullable=True)
    last_error = Column(Text, nullable=True)

    # --- Residual open/volatile keys that do not map to a typed column ---
    residual_json = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    provider = relationship("LLMProvider", back_populates="oauth_config")


# Keys that own a dedicated typed column above. Anything outside this set is
# preserved in residual_json by the mapping helpers below.
OAUTH_CONFIG_TYPED_KEYS: frozenset[str] = frozenset(
    {
        "oauth_client_id",
        "oauth_identity_provider_id",
        "google_cloud_project",
        "login",
        "name",
        "host",
        "source",
        "token_type",
        "access_token_expires_at",
        "refresh_token_expires_at",
        "subscription_tier",
        "subscription_tier_name",
        "has_paid_tier",
        "cloudai_project",
        "aws_static_credentials_configured",
        "last_error",
    }
)

_BOOL_KEYS: frozenset[str] = frozenset({"has_paid_tier", "aws_static_credentials_configured"})


def oauth_config_columns_from_metadata(meta: dict) -> dict:
    """Split an ``auth_metadata_json`` mapping into typed column values.

    Returns a dict of ``{column_name: value}`` suitable for populating a
    :class:`ProviderOAuthConfig` row, with any unmapped keys collected under
    ``residual_json``. Never drops data.
    """

    columns: dict = {}
    residual: dict = {}
    for key, value in (meta or {}).items():
        if key in OAUTH_CONFIG_TYPED_KEYS:
            columns[key] = bool(value) if key in _BOOL_KEYS else value
        else:
            residual[key] = value
    columns["residual_json"] = residual or None
    return columns


def oauth_config_to_metadata(config: "ProviderOAuthConfig") -> dict:
    """Reconstruct an ``auth_metadata_json``-shaped dict from a config row.

    Only non-empty typed values are emitted (mirroring how the OAuth flows only
    set keys they have values for), then residual keys are merged back in. This
    is what dual-read consumers use when the config row is present.
    """

    meta: dict = {}
    for key in OAUTH_CONFIG_TYPED_KEYS:
        value = getattr(config, key, None)
        if value is None:
            continue
        meta[key] = value
    if isinstance(config.residual_json, dict):
        for key, value in config.residual_json.items():
            meta.setdefault(key, value)
    return meta


def oauth_metadata_from_provider(provider) -> dict:
    """Resolve OAuth metadata from a provider's eager-loaded config row.

    Sync equivalent of ``oauth_config_bridge.read_oauth_metadata`` for call
    sites that do not hold an ``AsyncSession`` (serializers, readiness checks,
    audit snapshots). Reads the ``provider.oauth_config`` relationship, which
    those call sites eager-load at their query so no lazy load is triggered.
    Returns an empty dict when the provider has no config row.

    If the relationship is not loaded (a caller forgot to eager-load and the
    instance is attached to an async session), the value is treated as absent
    rather than triggering a synchronous lazy load, which would raise
    ``MissingGreenlet`` under async. The eager-load points documented on the
    query sites keep this from masking real data.
    """

    from sqlalchemy import inspect as sa_inspect

    state = sa_inspect(provider, raiseerr=False)
    if state is not None and "oauth_config" in state.unloaded:
        # Relationship not eager-loaded on an attached instance; treat as absent
        # instead of triggering a lazy load (async-unsafe).
        return {}
    config = getattr(provider, "oauth_config", None)
    if config is None:
        return {}
    return oauth_config_to_metadata(config)
