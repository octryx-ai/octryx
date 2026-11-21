"""Canonical auth service package surface."""

from ..security_permissions import user_has_permission
from .credentials import (
    authenticate_user,
    create_refresh_token,
    resolve_bearer_principal_user_id,
    revoke_refresh_token,
    rotate_refresh_token,
)
from .service import decode_token, get_current_user, require_api_key_scope, require_role, security
from .tokens import (
    JWT_ALGORITHM,
    SESSION_STREAM_TOKEN_SCOPE,
    _hash_refresh_token,
    create_access_token,
    create_session_stream_token,
    decode_session_stream_token,
    hash_password,
    verify_password,
)

__all__ = [
    "JWT_ALGORITHM",
    "SESSION_STREAM_TOKEN_SCOPE",
    "_hash_refresh_token",
    "authenticate_user",
    "create_access_token",
    "create_refresh_token",
    "create_session_stream_token",
    "decode_session_stream_token",
    "decode_token",
    "get_current_user",
    "hash_password",
    "require_api_key_scope",
    "require_role",
    "resolve_bearer_principal_user_id",
    "revoke_refresh_token",
    "rotate_refresh_token",
    "security",
    "user_has_permission",
    "verify_password",
]
