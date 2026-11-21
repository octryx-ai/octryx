"""Which sign-in kind each access field belongs to, and which fields a kind requires.

Per connection type, from the auth modules that read the fields (never a second rule):

- **Jira / Confluence / Bitbucket** (``atlassian_auth``): each mode needs its principal and secret
  (``mode_credential_fields``); ``oidc_client_credentials`` also its token URL, with scope, audience and client auth
  optional. A Bitbucket Cloud connection has one sign-in and names no mode (its descriptor's ``complete`` check);
- **ServiceNow** (``servicenow_auth``): each mode needs its fields (``mode_credential_fields``); OIDC's scope,
  audience and client auth are optional;
- every other type has one sign-in kind (``token``, or ``none`` without a secret), so every field belongs to it;
  a type that can read public repositories anonymously (:data:`PUBLIC_TYPES`, GitHub) also has ``none``: its
  non-secret fields (URL, owner) belong to both, its secrets to ``token`` only. A connection without a credential
  serves agent tools at most at level ``read`` (``agent_tools_level_requires_credentials``).

A field no mode names (URL, auth mode, options) belongs to every kind. ``required`` of a field means required for
the kinds it belongs to: the descriptor's own flag, the target and the auth mode of a type with sign-in kinds, and a
mode's credential fields. :func:`missing_required` is the save-time check for the chosen kind
(``connection_field_invalid`` with ``field: access.<key>``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.services.atlassian_auth_modes import AUTH_MODES as ATLASSIAN_AUTH_MODES
from app.services.atlassian_auth_modes import MODE_OIDC_CLIENT_CREDENTIALS as ATLASSIAN_OIDC
from app.services.atlassian_auth_validation import mode_credential_fields as atlassian_mode_fields

from ..named_connections.descriptor import ConnectorDescriptor
from ..named_connections.grants import has_credentials
from ..oidc_client_credentials import product_fields
from ..secret import secret_ref_field_name
from ..servicenow_auth import AUTH_MODES as SERVICENOW_AUTH_MODES
from ..servicenow_auth import MODE_OIDC_CLIENT_CREDENTIALS as SERVICENOW_OIDC
from ..servicenow_auth import OIDC_FIELDS as SERVICENOW_OIDC_FIELDS
from ..servicenow_auth import mode_credential_fields as servicenow_mode_fields

KindFields = dict[str, tuple[frozenset[str], frozenset[str]]]  # kind -> (required, optional)
KIND_TOKEN = "token"
KIND_NONE = "none"
PUBLIC_TYPES = frozenset({"github"})
CODE_LEVEL_REQUIRES_CREDENTIALS = "agent_tools_level_requires_credentials"


def _atlassian(connector: str) -> KindFields:
    table: KindFields = {}
    for mode in ATLASSIAN_AUTH_MODES:
        required, optional = set(atlassian_mode_fields(connector, mode) or ()), set()
        if mode == ATLASSIAN_OIDC:
            oidc = product_fields(connector)
            required.add(oidc.token_url)
            optional |= {oidc.scope, oidc.audience, oidc.client_auth}
        table[mode] = (frozenset(required), frozenset(optional))
    return table


def _servicenow() -> KindFields:
    oidc = SERVICENOW_OIDC_FIELDS
    return {mode: (frozenset(servicenow_mode_fields(mode) or ()),
                   frozenset({oidc.scope, oidc.audience, oidc.client_auth}) if mode == SERVICENOW_OIDC else frozenset())
            for mode in SERVICENOW_AUTH_MODES}


def kind_fields(connector: str) -> KindFields | None:
    """``{kind: (required, optional)}`` of a type whose fields depend on the sign-in kind; ``None`` otherwise."""
    if connector in ("jira", "confluence", "bitbucket"):
        return _atlassian(connector)
    if connector == "servicenow":
        return _servicenow()
    return None


def _mode_specific(table: KindFields) -> frozenset[str]:
    return frozenset(name for required, optional in table.values() for name in (*required, *optional))


def field_kinds(descriptor: ConnectorDescriptor, kinds: list[str], mode_field: str | None) -> dict[str, dict]:
    """``{field: {"auth_kinds": [...], "required": bool}}`` for the connection-types listing."""
    table = kind_fields(descriptor.connector)
    specific = _mode_specific(table) if table else frozenset()
    result = {}
    for item in descriptor.fields:
        if item.name in specific:
            applies = [kind for kind in kinds if item.name in (*table[kind][0], *table[kind][1])]
            required = any(item.name in table[kind][0] for kind in applies)
        elif item.secret and KIND_NONE in kinds:
            applies, required = [kind for kind in kinds if kind != KIND_NONE], item.required
        else:
            applies = list(kinds)
            required = item.required or (table is not None and item.name in (descriptor.usable_field, mode_field))
        result[item.name] = {"auth_kinds": applies, "required": required}
    return result


def _present(config: Mapping[str, Any], name: str) -> bool:
    return any(config.get(key) not in (None, "", [], {}) for key in (name, secret_ref_field_name(name)))


def chosen_kind(descriptor: ConnectorDescriptor, kinds: list[str], mode_field: str | None,
                config: Mapping[str, Any], explicit: object = None) -> object:
    """The sign-in kind of ``config``: its auth mode; else ``explicit`` (``access.auth``); else ``none`` when a type
    that allows it stores no credential; else the type's one kind."""
    if mode_field:
        return config.get(mode_field)
    if explicit is not None:
        return explicit
    if KIND_NONE in kinds and not has_credentials(descriptor.connector, config):
        return KIND_NONE
    return kinds[0] if kinds else None


def missing_required(descriptor: ConnectorDescriptor, kinds: list[str], mode_field: str | None,
                     config: Mapping[str, Any], chosen: object = None) -> list[str]:
    """The fields the chosen kind requires that ``config`` lacks (a stored secret ref counts as set)."""
    chosen = chosen if chosen is not None else chosen_kind(descriptor, kinds, mode_field, config)
    fields = field_kinds(descriptor, kinds, mode_field)
    return [name for name, entry in fields.items()
            if entry["required"] and chosen in entry["auth_kinds"] and not _present(config, name)]


__all__ = [
    "CODE_LEVEL_REQUIRES_CREDENTIALS",
    "KIND_NONE",
    "KIND_TOKEN",
    "PUBLIC_TYPES",
    "chosen_kind",
    "field_kinds",
    "kind_fields",
    "missing_required",
]
