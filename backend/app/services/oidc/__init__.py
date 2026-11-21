"""Package surface for OIDC service helpers."""

from .provider_http import (
    _discover_provider_configuration,
    _exchange_authorization_code,
    _fetch_userinfo_claims,
    _provider_client_secret,
)
from .providers import (
    DEFAULT_SCOPE,
    list_identity_providers,
    list_public_oidc_providers,
    upsert_identity_provider,
)
from .serialization import serialize_identity_provider
from .service import (
    _base64url_sha256,
    _normalize_target_path,
    _oauth_cookie_redirect,
    build_oidc_authorization_redirect,
    complete_oidc_callback,
    refresh_access_token,
)

__all__ = [
    "DEFAULT_SCOPE",
    "_base64url_sha256",
    "_discover_provider_configuration",
    "_exchange_authorization_code",
    "_fetch_userinfo_claims",
    "_normalize_target_path",
    "_oauth_cookie_redirect",
    "_provider_client_secret",
    "build_oidc_authorization_redirect",
    "complete_oidc_callback",
    "list_identity_providers",
    "list_public_oidc_providers",
    "refresh_access_token",
    "serialize_identity_provider",
    "upsert_identity_provider",
]
