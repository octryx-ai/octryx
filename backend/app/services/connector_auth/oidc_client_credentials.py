"""OpenID Connect client credentials of a connector: the admin-entered client, its token URL rule and the
closed error codes."""

from __future__ import annotations

import hashlib
import ipaddress
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

CLIENT_SECRET_POST = "client_secret_post"
CLIENT_SECRET_BASIC = "client_secret_basic"
CLIENT_AUTH_METHODS = (CLIENT_SECRET_POST, CLIENT_SECRET_BASIC)

CODE_TOKEN_ENDPOINT_UNREACHABLE = "oidc_token_endpoint_unreachable"
CODE_TOKEN_ENDPOINT_REDIRECT = "oidc_token_endpoint_redirect"
CODE_INVALID_CLIENT = "oidc_invalid_client"
CODE_UNAUTHORIZED_CLIENT = "oidc_unauthorized_client"
CODE_BAD_RESPONSE = "oidc_bad_response"
CODE_TOKEN_URL_INVALID = "oidc_token_url_invalid"
CODE_CONNECTOR_UNAUTHORIZED = "connector_unauthorized"

MESSAGES = {
    CODE_TOKEN_ENDPOINT_UNREACHABLE: "The token endpoint of the identity provider could not be reached.",
    CODE_TOKEN_ENDPOINT_REDIRECT: (
        "The token endpoint answered with a redirect; enter the final token endpoint URL. The client secret "
        "was not sent to the redirect target."
    ),
    CODE_INVALID_CLIENT: "The identity provider refused the client id or client secret (invalid_client).",
    CODE_UNAUTHORIZED_CLIENT: (
        "The identity provider does not allow this client the client credentials grant (unauthorized_client)."
    ),
    CODE_BAD_RESPONSE: "The identity provider answered without a usable access token.",
    CODE_TOKEN_URL_INVALID: "The token endpoint URL must be an https URL without credentials in it.",
    CODE_CONNECTOR_UNAUTHORIZED: (
        "The identity provider issued a token, but the target system refused it: the technical user may "
        "lack access in the target system."
    ),
}

TOKEN_TIMEOUT_SECONDS = 15.0
REFRESH_MARGIN_SECONDS = 60.0
DEFAULT_LIFETIME_SECONDS = 60.0
MAX_LIFETIME_SECONDS = 3600.0
MAX_TOKEN_CHARS = 16384
_LOOPBACK_NAMES = frozenset({"localhost"})


class OidcTokenError(Exception):
    # ``code`` is closed and the message fixed, never a value.

    def __init__(self, code: str, *, egress_refused: bool = False, http_status: int | None = None) -> None:
        super().__init__(f"{code}: {MESSAGES[code]}")
        self.code = code
        self.egress_refused = egress_refused
        self.http_status = http_status


@dataclass(frozen=True, slots=True)
class OidcFields:
    token_url: str
    client_id: str
    client_secret: str
    scope: str
    audience: str
    client_auth: str


def product_fields(product: str) -> OidcFields:
    prefix = f"{product}_oidc_"
    return OidcFields(*(f"{prefix}{name}" for name in (
        "token_url", "client_id", "client_secret", "scope", "audience", "client_auth")))


@dataclass(frozen=True, slots=True)
class OidcClientCredentials:
    connection: str
    token_url: str
    client_id: str
    client_secret: str = field(repr=False)
    scope: str | None = None
    audience: str | None = None
    client_auth: str = CLIENT_SECRET_POST

    def cache_key(self) -> tuple[str, ...]:
        # One token per client, whichever connector.
        digest = hashlib.sha256(self.client_secret.encode()).hexdigest()
        return (self.token_url, self.client_id, self.scope or "", self.audience or "", digest)


def _text(config: Mapping[str, Any], key: str) -> str:
    value = config.get(key)
    return value.strip() if isinstance(value, str) else ""


def _is_loopback(host: str) -> bool:
    if host in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def token_url_problem(value: object) -> str | None:
    # Imported here because the tool_config package imports the auth modules.
    from ..tool_config.url_userinfo import carries_userinfo

    text = value.strip() if isinstance(value, str) else ""
    if not text or carries_userinfo(text):
        return MESSAGES[CODE_TOKEN_URL_INVALID]
    try:
        parts = urlsplit(text)
        host = (parts.hostname or "").lower()
        parts.port  # noqa: B018 - raises on an invalid port
    except ValueError:
        return MESSAGES[CODE_TOKEN_URL_INVALID]
    scheme = parts.scheme.lower()
    if not host or any(ch.isspace() for ch in text):
        return MESSAGES[CODE_TOKEN_URL_INVALID]
    if scheme == "https" or (scheme == "http" and _is_loopback(host)):
        return None
    return MESSAGES[CODE_TOKEN_URL_INVALID]


def client_credentials(
    config: Mapping[str, Any], fields: OidcFields, *, connection: str
) -> OidcClientCredentials | None:
    client_id, secret = _text(config, fields.client_id), _text(config, fields.client_secret)
    token_url = _text(config, fields.token_url)
    client_auth = _text(config, fields.client_auth) or CLIENT_SECRET_POST
    if not client_id or not secret or token_url_problem(token_url) or client_auth not in CLIENT_AUTH_METHODS:
        return None
    return OidcClientCredentials(
        connection=connection,
        token_url=token_url,
        client_id=client_id,
        client_secret=secret,
        scope=_text(config, fields.scope) or None,
        audience=_text(config, fields.audience) or None,
        client_auth=client_auth,
    )


def config_problems(config: Mapping[str, Any], fields: OidcFields, *, present: Any) -> list[str]:
    # Field names and fixed text only.
    missing = [key for key in (fields.token_url, fields.client_id, fields.client_secret) if not present(key)]
    problems = [f"needs: {', '.join(missing)}"] if missing else []
    if _text(config, fields.token_url) and token_url_problem(config.get(fields.token_url)):
        problems.append(f"{fields.token_url}: {MESSAGES[CODE_TOKEN_URL_INVALID]}")
    client_auth = config.get(fields.client_auth)
    if client_auth not in (None, "") and client_auth not in CLIENT_AUTH_METHODS:
        problems.append(f"{fields.client_auth} must be one of: {', '.join(CLIENT_AUTH_METHODS)}")
    return problems


__all__ = [
    "CLIENT_AUTH_METHODS",
    "CLIENT_SECRET_BASIC",
    "CLIENT_SECRET_POST",
    "CODE_BAD_RESPONSE",
    "CODE_CONNECTOR_UNAUTHORIZED",
    "CODE_INVALID_CLIENT",
    "CODE_TOKEN_ENDPOINT_REDIRECT",
    "CODE_TOKEN_ENDPOINT_UNREACHABLE",
    "CODE_TOKEN_URL_INVALID",
    "CODE_UNAUTHORIZED_CLIENT",
    "DEFAULT_LIFETIME_SECONDS",
    "MAX_LIFETIME_SECONDS",
    "MESSAGES",
    "REFRESH_MARGIN_SECONDS",
    "OidcClientCredentials",
    "OidcFields",
    "OidcTokenError",
    "client_credentials",
    "config_problems",
    "product_fields",
    "token_url_problem",
]
