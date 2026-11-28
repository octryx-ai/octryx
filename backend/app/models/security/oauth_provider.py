"""OAuth 2.1 authorization-server models (the platform as token issuer)."""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import relationship

from ...db import Base
from ...time_utils import utc_now

GRANT_TYPE_AUTHORIZATION_CODE = "authorization_code"
GRANT_TYPE_REFRESH_TOKEN = "refresh_token"
ALLOWED_GRANT_TYPES = {GRANT_TYPE_AUTHORIZATION_CODE, GRANT_TYPE_REFRESH_TOKEN}

TOKEN_AUTH_NONE = "none"
TOKEN_AUTH_CLIENT_SECRET_POST = "client_secret_post"
TOKEN_AUTH_CLIENT_SECRET_BASIC = "client_secret_basic"
ALLOWED_TOKEN_AUTH_METHODS = {
    TOKEN_AUTH_NONE,
    TOKEN_AUTH_CLIENT_SECRET_POST,
    TOKEN_AUTH_CLIENT_SECRET_BASIC,
}


def uuid_pk() -> str:
    return str(uuid.uuid4())


class OAuthClient(Base):
    """A registered OAuth client (RFC 7591 dynamic registration or admin-created)."""

    __tablename__ = "oauth_clients"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    client_id = Column(String(64), nullable=False, unique=True, index=True)
    # Null for public clients (PKCE-only, token_endpoint_auth_method="none").
    client_secret_hash = Column(String(128), nullable=True)
    client_name = Column(String(255), nullable=False)
    redirect_uris = Column(JSON, nullable=False, default=list)
    grant_types = Column(JSON, nullable=False, default=list)
    scopes = Column(JSON, nullable=False, default=list)
    token_endpoint_auth_method = Column(String(40), nullable=False, default=TOKEN_AUTH_NONE)
    registration_source = Column(String(20), nullable=False, default="dynamic")
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=utc_now, index=True)


class OAuthGrant(Base):
    """User consent for a client, bound to the platform login session."""

    __tablename__ = "oauth_grants"
    __table_args__ = (Index("ix_oauth_grants_user_client", "user_id", "client_id"),)

    id = Column(String(36), primary_key=True, default=uuid_pk)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    client_id = Column(String(64), nullable=False, index=True)
    scopes = Column(JSON, nullable=False, default=list)
    # Null means "all projects the user can access at call time".
    project_ids = Column(JSON, nullable=True)
    # Root of the platform refresh-token rotation chain captured at consent
    # time; liveness of the chain gates every OAuth refresh.
    platform_refresh_token_id = Column(String(36), ForeignKey("refresh_tokens.id"), nullable=True)
    # A device grant: bound to a registered device instead of the web login session; its own
    # lifetime rules apply (``services/devices/credential``).
    device_id = Column(String(40), nullable=True, index=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    revoked_at = Column(DateTime, nullable=True, index=True)

    user = relationship("User")


class OAuthAuthorizationCode(Base):
    """Single-use authorization code (PKCE S256 mandatory)."""

    __tablename__ = "oauth_authorization_codes"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    code_hash = Column(String(128), nullable=False, unique=True, index=True)
    client_id = Column(String(64), nullable=False, index=True)
    grant_id = Column(String(36), ForeignKey("oauth_grants.id"), nullable=False)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    redirect_uri = Column(Text, nullable=False)
    scopes = Column(JSON, nullable=False, default=list)
    code_challenge = Column(String(128), nullable=False)
    code_challenge_method = Column(String(10), nullable=False, default="S256")
    resource = Column(Text, nullable=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    consumed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now)


class OAuthRefreshToken(Base):
    """Rotating refresh token issued to an OAuth client for a grant."""

    __tablename__ = "oauth_refresh_tokens"
    __table_args__ = (Index("ix_oauth_refresh_tokens_token_hash", "token_hash", unique=True),)

    id = Column(String(36), primary_key=True, default=uuid_pk)
    token_hash = Column(String(128), nullable=False)
    grant_id = Column(String(36), ForeignKey("oauth_grants.id"), nullable=False, index=True)
    client_id = Column(String(64), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    scopes = Column(JSON, nullable=False, default=list)
    expires_at = Column(DateTime, nullable=False, index=True)
    revoked_at = Column(DateTime, nullable=True, index=True)
    rotated_from_id = Column(String(36), ForeignKey("oauth_refresh_tokens.id"), nullable=True)
    created_at = Column(DateTime, default=utc_now, index=True)

    grant = relationship("OAuthGrant")
