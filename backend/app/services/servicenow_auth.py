"""Authentication of the ServiceNow connector: one explicit mode.

``servicenow_auth_mode`` is a closed, non-secret field:

``oidc_client_credentials``
    An OpenID Connect / OAuth client credentials grant (``services/oidc_client_credentials.py``) at the
    required ``servicenow_token_url`` with ``servicenow_client_id`` and the secret ``servicenow_client_secret``
    (optional ``servicenow_oauth_scope``, ``servicenow_oidc_audience``, ``servicenow_oidc_client_auth``).
    The token endpoint may be an external identity provider; it is admin-entered and https-only.
``bearer_token``
    ``Authorization: Bearer <servicenow_token>``.
``basic``
    Basic ``servicenow_username``/``servicenow_password``.
``oauth_password``
    ServiceNow's own OAuth with the password grant (``services/servicenow_password_grant.py``): the required
    ``servicenow_token_url``, ``servicenow_client_id`` and secret ``servicenow_client_secret``, plus
    ``servicenow_username`` and secret ``servicenow_password``, optional ``servicenow_oauth_scope``; the
    refresh token is used when present.

The endpoint style (``servicenow_api_style``: Table API or Scripted REST, ``services/servicenow_scripted.py``)
is validated with the same writers, for every mode.

Only the mode's own fields are read; there is never a cross-fallback. Without a mode no credential resolves (the
connection needs configuration), and a save that stores credentials without a mode is refused. A stored mode
outside the closed set resolves to no credential (fail closed).
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx

from .atlassian_auth_modes import AtlassianAuthConfigError
from .oidc_client_credentials import (
    CODE_TOKEN_URL_INVALID,
    MESSAGES,
    OidcClientCredentials,
    OidcFields,
    client_credentials,
    config_problems,
    token_url_problem,
)
from .oidc_token_cache import OidcBearerAuth
from .outbound_egress import CONNECTION_SERVICENOW
from .servicenow_password_grant import PasswordGrantBearerAuth, PasswordGrantCredentials
from .servicenow_scripted import config_problems as scripted_config_problems

MODE_FIELD = "servicenow_auth_mode"
MODE_OIDC_CLIENT_CREDENTIALS = "oidc_client_credentials"
MODE_BEARER_TOKEN = "bearer_token"
MODE_BASIC = "basic"
MODE_OAUTH_PASSWORD = "oauth_password"
AUTH_MODES = (MODE_OIDC_CLIENT_CREDENTIALS, MODE_BEARER_TOKEN, MODE_BASIC, MODE_OAUTH_PASSWORD)

SCHEME_OIDC = "oidc"
SCHEME_OAUTH_PASSWORD = "oauth_password"
SCHEME_BEARER = "bearer"
SCHEME_BASIC = "basic"

CODE_AUTH_INVALID = "servicenow_auth_invalid"
CODE_API_INVALID = "servicenow_api_invalid"
OIDC_FIELDS = OidcFields(
    token_url="servicenow_token_url",
    client_id="servicenow_client_id",
    client_secret="servicenow_client_secret",
    scope="servicenow_oauth_scope",
    audience="servicenow_oidc_audience",
    client_auth="servicenow_oidc_client_auth",
)
_MODE_SECRETS = {
    MODE_BEARER_TOKEN: ("servicenow_token",),
    MODE_BASIC: ("servicenow_username", "servicenow_password"),
    MODE_OAUTH_PASSWORD: (
        "servicenow_token_url", "servicenow_client_id", "servicenow_client_secret", "servicenow_username",
        "servicenow_password",
    ),
}

# Every principal or secret a mode reads; stored without a mode they are refused at save.
_CREDENTIAL_FIELDS = (
    "servicenow_token", "servicenow_username", "servicenow_password", OIDC_FIELDS.client_id,
    OIDC_FIELDS.client_secret,
)


@dataclass(frozen=True, slots=True)
class ServiceNowAuth:
    """The resolved credential of one ServiceNow connection and its explicit mode."""

    mode: str
    scheme: str
    principal: str = field(repr=False, default="")
    secret: str = field(repr=False, default="")
    oidc: OidcClientCredentials | None = None
    password_grant: PasswordGrantCredentials | None = None

    def headers(self) -> dict[str, str]:
        """The static ``Authorization`` header; none for ``oidc``/``oauth_password`` (see :meth:`http_auth`)."""
        if self.scheme == SCHEME_BEARER:
            return {"Authorization": f"Bearer {self.secret}"}
        if self.scheme == SCHEME_BASIC:
            token = base64.b64encode(f"{self.principal}:{self.secret}".encode()).decode()
            return {"Authorization": f"Basic {token}"}
        return {}

    def http_auth(self, transport: httpx.AsyncBaseTransport | None = None) -> httpx.Auth | None:
        if self.password_grant is not None:
            return PasswordGrantBearerAuth(self.password_grant, transport=transport)
        return OidcBearerAuth(self.oidc, transport=transport) if self.oidc is not None else None


def mode_credential_fields(mode: object) -> tuple[str, ...] | None:
    """The fields an explicit ``mode`` needs (OIDC: token URL, client id and secret); ``None`` for an unknown mode."""
    if mode == MODE_OIDC_CLIENT_CREDENTIALS:
        return (OIDC_FIELDS.token_url, OIDC_FIELDS.client_id, OIDC_FIELDS.client_secret)
    return _MODE_SECRETS.get(mode) if isinstance(mode, str) else None


def _text(config: Mapping[str, Any], key: str) -> str:
    value = config.get(key)
    return value.strip() if isinstance(value, str) else ""


def declared_mode(config: Mapping[str, Any]) -> object:
    raw = config.get(MODE_FIELD)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    return raw.strip() if isinstance(raw, str) else raw


def _oidc(config: Mapping[str, Any]) -> ServiceNowAuth | None:
    credentials = client_credentials(config, OIDC_FIELDS, connection=CONNECTION_SERVICENOW)
    if credentials is None:
        return None
    return ServiceNowAuth(
        MODE_OIDC_CLIENT_CREDENTIALS, SCHEME_OIDC, credentials.client_id, credentials.client_secret, credentials
    )


def _basic(config: Mapping[str, Any]) -> ServiceNowAuth | None:
    username, password = _text(config, "servicenow_username"), _text(config, "servicenow_password")
    return ServiceNowAuth(MODE_BASIC, SCHEME_BASIC, username, password) if username and password else None


def _oauth_password(config: Mapping[str, Any]) -> ServiceNowAuth | None:
    values = {key: _text(config, key) for key in _MODE_SECRETS[MODE_OAUTH_PASSWORD]}
    if not all(values.values()) or token_url_problem(values["servicenow_token_url"]):
        return None
    grant = PasswordGrantCredentials(
        token_url=values["servicenow_token_url"],
        client_id=values["servicenow_client_id"],
        client_secret=values["servicenow_client_secret"],
        username=values["servicenow_username"],
        password=values["servicenow_password"],
        scope=_text(config, "servicenow_oauth_scope") or None,
    )
    return ServiceNowAuth(MODE_OAUTH_PASSWORD, SCHEME_OAUTH_PASSWORD, grant.username, grant.password,
                          password_grant=grant)


def resolve_servicenow_auth(config: Mapping[str, Any]) -> ServiceNowAuth | None:
    """The credential a request uses, or ``None`` when incomplete or the stored mode is absent or unknown."""
    mode = declared_mode(config)
    if mode == MODE_OIDC_CLIENT_CREDENTIALS:
        return _oidc(config)
    if mode == MODE_BEARER_TOKEN:
        token = _text(config, "servicenow_token")
        return ServiceNowAuth(mode, SCHEME_BEARER, "", token) if token else None
    if mode == MODE_BASIC:
        return _basic(config)
    if mode == MODE_OAUTH_PASSWORD:
        return _oauth_password(config)
    return None


def _present(config: Mapping[str, Any], key: str) -> bool:
    return bool(_text(config, key) or _text(config, f"{key}_secret_ref"))


def validate_servicenow_auth_config(config: Mapping[str, Any]) -> None:
    """Refuse an unknown mode, a mode without its fields, or credentials without a mode; names, never values."""
    api_problems = scripted_config_problems(config)
    if api_problems:
        raise AtlassianAuthConfigError(f"ServiceNow API: {'; '.join(api_problems)}.", code=CODE_API_INVALID)
    mode = declared_mode(config)
    if mode is None:
        if any(_present(config, key) for key in _CREDENTIAL_FIELDS):
            raise AtlassianAuthConfigError(
                f"ServiceNow credentials need {MODE_FIELD}: one of {', '.join(AUTH_MODES)}.", code=CODE_AUTH_INVALID
            )
        return
    if not isinstance(mode, str) or mode not in AUTH_MODES:
        raise AtlassianAuthConfigError(f"{MODE_FIELD} must be one of: {', '.join(AUTH_MODES)}.", code=CODE_AUTH_INVALID)
    if mode == MODE_OIDC_CLIENT_CREDENTIALS:
        problems = config_problems(config, OIDC_FIELDS, present=lambda key: _present(config, key))
        code = CODE_TOKEN_URL_INVALID if any(MESSAGES[CODE_TOKEN_URL_INVALID] in item for item in problems) else None
    else:
        missing = [key for key in _MODE_SECRETS[mode] if not _present(config, key)]
        problems, code = ([f"needs: {', '.join(missing)}"] if missing else []), None
        token_url = _text(config, "servicenow_token_url")
        if mode == MODE_OAUTH_PASSWORD and token_url and token_url_problem(token_url):
            problems.append(f"servicenow_token_url: {MESSAGES[CODE_TOKEN_URL_INVALID]}")
            code = CODE_TOKEN_URL_INVALID
    if problems:
        text = "; ".join(problem.rstrip(".") for problem in problems)
        raise AtlassianAuthConfigError(f"ServiceNow {mode}: {text}.", code=code or CODE_AUTH_INVALID)


__all__ = [
    "AUTH_MODES",
    "CODE_AUTH_INVALID",
    "MODE_BASIC",
    "MODE_BEARER_TOKEN",
    "MODE_FIELD",
    "MODE_OAUTH_PASSWORD",
    "MODE_OIDC_CLIENT_CREDENTIALS",
    "OIDC_FIELDS",
    "mode_credential_fields",
    "SCHEME_BASIC",
    "SCHEME_BEARER",
    "SCHEME_OIDC",
    "ServiceNowAuth",
    "declared_mode",
    "resolve_servicenow_auth",
    "validate_servicenow_auth_config",
]
