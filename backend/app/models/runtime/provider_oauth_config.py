"""OAuth configuration and runtime state of an LLM provider, one row per provider."""

import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import relationship

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now


def uuid_pk():
    return str(uuid.uuid4())


class ProviderOAuthConfig(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"provider_id": "llm_providers"}
    __tablename__ = "provider_oauth_config"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    provider_id = Column(
        String(36),
        ForeignKey("llm_providers.id"),
        nullable=False,
        unique=True,
        index=True,
    )

    oauth_client_id = Column(String(500), nullable=True)
    oauth_identity_provider_id = Column(String(36), nullable=True)
    google_cloud_project = Column(String(200), nullable=True)

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
    # Never drops data: unmapped keys go to ``residual_json``.
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
    # A relationship that is not loaded counts as absent: a synchronous lazy load would raise ``MissingGreenlet`` under
    # async.
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
