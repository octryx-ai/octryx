import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import relationship

from ...db import Base
from ...time_utils import utc_now


def uuid_pk() -> str:
    return str(uuid.uuid4())


class IdentityProvider(Base):
    __tablename__ = "identity_providers"
    __table_args__ = (
        Index("ix_identity_providers_is_active", "is_active"),
        Index("ix_identity_providers_provider_type", "provider_type"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    name = Column(String(120), nullable=False)
    provider_type = Column(String(30), nullable=False, default="oidc")
    issuer_url = Column(String(500), nullable=True)
    discovery_url = Column(String(500), nullable=True)
    authorization_endpoint = Column(String(500), nullable=True)
    token_endpoint = Column(String(500), nullable=True)
    userinfo_endpoint = Column(String(500), nullable=True)
    jwks_uri = Column(String(500), nullable=True)
    client_id = Column(String(300), nullable=True)
    client_secret_secret_ref = Column(String(36), ForeignKey("stored_secrets.id"), nullable=True)
    scopes_json = Column(JSON, default=list)
    claim_mappings_json = Column(JSON, default=dict)
    group_role_mappings_json = Column(JSON, default=dict)
    group_group_mappings_json = Column(JSON, default=dict)
    default_roles_json = Column(JSON, default=list)
    default_group_ids_json = Column(JSON, default=list)
    auto_provision_users = Column(Boolean, default=True, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    client_secret = relationship("StoredSecret")


class UserIdentity(Base):
    __tablename__ = "user_identities"
    __table_args__ = (Index("ix_user_identities_provider_subject", "provider_id", "subject", unique=True),)

    id = Column(String(36), primary_key=True, default=uuid_pk)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    provider_id = Column(String(36), ForeignKey("identity_providers.id"), nullable=False, index=True)
    subject = Column(String(255), nullable=False)
    external_email = Column(String(255), nullable=True)
    external_username = Column(String(255), nullable=True)
    external_groups_json = Column(JSON, default=list)
    # The provider's groups claim and roles claim of the last sign-in, apart (for work-role assignments).
    sso_groups_json = Column(JSON, default=list)
    sso_roles_json = Column(JSON, default=list)
    encrypted_access_token = Column(Text, nullable=True)
    encrypted_id_token = Column(Text, nullable=True)
    profile_json = Column(JSON, default=dict)
    last_login_at = Column(DateTime, default=utc_now, index=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    user = relationship("User")
    provider = relationship("IdentityProvider")


class OAuthSession(Base):
    __tablename__ = "oauth_sessions"
    __table_args__ = (Index("ix_oauth_sessions_state", "state", unique=True),)

    id = Column(String(36), primary_key=True, default=uuid_pk)
    provider_id = Column(String(36), ForeignKey("identity_providers.id"), nullable=False, index=True)
    state = Column(String(255), nullable=False)
    code_verifier = Column(Text, nullable=False)
    nonce = Column(String(255), nullable=False)
    redirect_path = Column(String(500), nullable=False, default="/chat")
    requested_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    consumed_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=utc_now, index=True)

    provider = relationship("IdentityProvider")
    requested_by = relationship("User")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (Index("ix_refresh_tokens_token_hash", "token_hash", unique=True),)

    id = Column(String(36), primary_key=True, default=uuid_pk)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    provider_id = Column(String(36), ForeignKey("identity_providers.id"), nullable=True, index=True)
    user_identity_id = Column(String(36), ForeignKey("user_identities.id"), nullable=True, index=True)
    token_hash = Column(String(128), nullable=False)
    encrypted_external_refresh_token = Column(Text, nullable=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    revoked_at = Column(DateTime, nullable=True, index=True)
    rotated_from_id = Column(String(36), ForeignKey("refresh_tokens.id"), nullable=True)
    last_used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now, index=True)

    user = relationship("User")
    provider = relationship("IdentityProvider")
    user_identity = relationship("UserIdentity")
