"""Fields of a connection unit as the connector preset declares them."""

from __future__ import annotations

from ...connector_auth.oidc_client_credentials import CLIENT_AUTH_METHODS
from ...tool_config.connection_fields import (
    auth_mode_fields,
    oidc_option_fields,
    principal_fields,
    secret_fields,
    target_fields,
)
from ..descriptor import Field

_PRODUCTS = {"jira": "Jira", "confluence": "Confluence", "servicenow": "ServiceNow"}
# A token of the product itself: Atlassian's API token (Cloud) or personal access token (Server/Data Center),
# ServiceNow's bearer token.
_TOKENS = {"servicenow": "Bearer token"}
_TOKEN = "API token or personal access token"

# By the key without its product prefix: (position in the form, label).
_PLAIN: dict[str, tuple[int, str]] = {
    "url": (0, "{product} URL"),
    "auth_mode": (1, "Authentication"),
    "email": (2, "Account email"),
    "username": (2, "Username"),
    "password": (3, "Password"),
    "token": (4, ""),
    "oidc_token_url": (5, "OpenID Connect token endpoint URL"),
    "token_url": (5, "Token endpoint URL"),
    "oidc_client_id": (6, "Client id"),
    "client_id": (6, "Client id"),
    "oidc_client_secret": (7, "Client secret"),
    "client_secret": (7, "Client secret"),
    "oidc_scope": (8, "Scope (optional)"),
    "oauth_scope": (8, "Scope (optional)"),
    "oidc_audience": (9, "Audience (optional)"),
    "oidc_client_auth": (10, "Client authentication (optional)"),
}
_LAST = 99


def _suffix(tool_name: str, name: str) -> str:
    prefix = f"{tool_name}_"
    return name[len(prefix):] if name.startswith(prefix) else name


def _label(tool_name: str, name: str) -> str:
    suffix = _suffix(tool_name, name)
    if suffix == "token":
        return _TOKENS.get(tool_name, _TOKEN)
    plain = _PLAIN.get(suffix)
    if plain is not None:
        return plain[1].format(product=_PRODUCTS.get(tool_name, tool_name.capitalize()))
    return suffix.replace("_", " ").strip().capitalize()


def _position(tool_name: str, field: Field) -> int:
    return _PLAIN.get(_suffix(tool_name, field.name), (_LAST, ""))[0]


def _field(tool_name: str, name: str, kind: str) -> Field:
    if _suffix(tool_name, name) == "oidc_client_auth":
        # A closed choice (connector_auth.oidc_client_credentials.CLIENT_AUTH_METHODS); empty means client_secret_post.
        return Field(name, _label(tool_name, name), kind="select", options=CLIENT_AUTH_METHODS)
    return Field(name, _label(tool_name, name), kind=kind)


def preset_unit(tool_name: str) -> tuple[Field, ...]:
    fields = [_field(tool_name, name, "url" if name.endswith("_url") else "text") for name in target_fields(tool_name)]
    fields += [_field(tool_name, name, "select") for name in auth_mode_fields(tool_name)]
    fields += [_field(tool_name, name, "text")
               for name in (*principal_fields(tool_name), *oidc_option_fields(tool_name))]
    fields += [_field(tool_name, name, "secret") for name in secret_fields(tool_name)]
    return tuple(sorted(fields, key=lambda field: _position(tool_name, field)))


__all__ = ["preset_unit"]
